"""Optional CPU candidate gateway. Standard library only; no builder DB or credentials."""

import argparse
import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

if __package__:
    from quartermaster.local_runtime import sha256, thread_count
    from quartermaster.model_pins import BASES, ORIGINAL_REVISION, model_limit
else:
    from local_runtime import sha256, thread_count
    from model_pins import BASES, ORIGINAL_REVISION, model_limit


def checked_file(path, maximum):
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError("CANDIDATE_LINK")
    if not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError("CANDIDATE_FILE")
    return path


def verify(artifacts, candidate_id):
    candidate_id = str(UUID(candidate_id))
    manifest = checked_file(artifacts / "candidates" / f"{candidate_id}.json", 4_000_000)
    record = json.loads(manifest.read_bytes())
    if (
        record["schema_version"]
        not in {"quartermaster.adviser-version/v1", "quartermaster.adviser-version/v2"}
        or record["id"] != candidate_id
        or record["status"] != "candidate"
        or record["smoke_passed"] is not True
    ):
        raise ValueError("CANDIDATE_MANIFEST")
    run_id = str(UUID(record["training_run_id"]))
    directory = artifacts / "training" / run_id / "output/portable"
    revision = ORIGINAL_REVISION
    if record["schema_version"] == "quartermaster.adviser-version/v2":
        baseline = record["baseline"]
        revision = baseline["base_revision"]
        if revision not in BASES or BASES[revision] != baseline["base_model_id"]:
            raise ValueError("CANDIDATE_BASE")
    # The application additionally verifies the exact job/adapter lineage before selection.
    model = checked_file(directory / "model.gguf", model_limit(revision))
    license_file = checked_file(directory / "LICENSE.model", 100_000)
    if (
        model.stat().st_size != record["model_size_bytes"]
        or sha256(model) != record["model_sha256"]
        or sha256(license_file) != record["license_sha256"]
    ):
        raise ValueError("CANDIDATE_HASH")
    with model.open("rb") as stream:
        if stream.read(8) != b"GGUF\x03\x00\x00\x00":
            raise ValueError("CANDIDATE_GGUF")
    return model, f"qm-candidate-{record['model_sha256']}"


class Gateway:
    def __init__(self, artifacts, threads=4):
        self.artifacts = artifacts
        self.threads = thread_count(threads)
        self.lock = threading.Lock()
        self.process = None
        self.selected = None

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.selected = None

    def select(self, candidate_id):
        if self.selected == candidate_id and self.process and self.process.poll() is None:
            return self.alias
        self.stop()
        model, alias = verify(self.artifacts, candidate_id)
        self.process = subprocess.Popen(
            [
                "llama-server",
                "-m",
                str(model),
                "--alias",
                alias,
                "--host",
                "127.0.0.1",
                "--port",
                "8081",
                "-c",
                "8192",
                "-t",
                str(self.threads),
                "-ngl",
                "0",
                "--parallel",
                "1",
                "--jinja",
                "--chat-template-kwargs",
                '{"enable_thinking":false}',
                "--no-webui",
                "--log-disable",
                "-n",
                "1024",
                "--no-context-shift",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # The larger verified bundle can exceed the old 30-second cold-start window.
        # Keep a finite 90-second bound; the client's complete request is also bounded.
        for _ in range(180 if model.stat().st_size > 3_000_000_000 else 60):
            if self.process.poll() is not None:
                break
            try:
                with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=1):
                    self.selected, self.alias = candidate_id, alias
                    return alias
            except (OSError, urllib.error.URLError):
                time.sleep(0.5)
        self.stop()
        raise ValueError("CANDIDATE_START")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            return self.respond(200, b'{"status":"ok"}')
        self.proxy("GET")

    def do_POST(self):
        self.proxy("POST")

    def proxy(self, method):
        self.connection.settimeout(10)
        gateway = self.server.gateway
        if not gateway.lock.acquire(blocking=False):
            return self.respond(409, b'{"error":"CANDIDATE_BUSY"}')
        try:
            parts = self.path.split("/")
            if not (
                (len(parts) == 4 and parts[2:] == ["v1", "models"] and method == "GET")
                or (
                    len(parts) == 5
                    and parts[2:] == ["v1", "chat", "completions"]
                    and method == "POST"
                )
            ):
                raise ValueError("CANDIDATE_PATH")
            candidate_id = str(UUID(parts[1]))
            length = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Transfer-Encoding") or not 0 <= length <= 48000:
                raise ValueError("CANDIDATE_INPUT")
            data = self.rfile.read(length) if method == "POST" else None
            alias = gateway.select(candidate_id)
            if data and json.loads(data).get("model") != alias:
                raise ValueError("CANDIDATE_MODEL")
            endpoint = "models" if method == "GET" else "chat/completions"
            request = urllib.request.Request(
                "http://127.0.0.1:8081/v1/" + endpoint,
                data=data,
                method=method,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read(131073)
            if len(body) > 131072:
                raise ValueError("CANDIDATE_SIZE")
            self.respond(200, body)
        except (OSError, ValueError, KeyError, TypeError, RecursionError, urllib.error.URLError):
            gateway.stop()
            self.respond(
                503,
                b'{"error":"CANDIDATE_UNAVAILABLE: Verify candidate files and runtime resources."}',
            )
        finally:
            gateway.lock.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("/data/artifacts"))
    parser.add_argument("--threads", type=thread_count, default=os.getenv("QM_LOCAL_THREADS", "4"))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.gateway = Gateway(args.artifacts, args.threads)
    try:
        server.serve_forever()
    finally:
        server.gateway.stop()
        server.server_close()


if __name__ == "__main__":
    main()
