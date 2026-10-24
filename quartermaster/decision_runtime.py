"""Offline CPU generation consumer. Standard library only; receives no reference labels."""

import argparse
import hashlib
import json
import signal
import subprocess
import time
import urllib.request
from pathlib import Path


def sha256(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def server_command(alias):
    return [
        "llama-server",
        "-m",
        "/model/model.gguf",
        "--alias",
        alias,
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
        "-c",
        "8192",
        "-t",
        "4",
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
    ]


def payload(inputs, case, alias):
    return {
        "model": alias,
        "messages": [
            {"role": "system", "content": inputs["system"]},
            {"role": "user", "content": case["context"]},
        ],
        **inputs["parameters"],
        "stream": False,
        "logprobs": True,
        "top_logprobs": 5,
        "post_sampling_probs": False,
        "return_tokens": True,
        "verbose": True,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "grounded_advice",
                "strict": True,
                "schema": inputs["response_schema"],
            },
        },
    }


def http(path, *, body=None, timeout=1):
    # No environment proxies, redirects, external hosts or runtime-selected destinations.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(
        "http://127.0.0.1:8080" + path,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
    )
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("DECISION_RESPONSE_SIZE")
        return json.loads(raw)


def generate(inputs_path, output, model_sha256, seconds):
    inputs = json.loads(inputs_path.read_bytes())
    input_sha256 = sha256(inputs_path)
    if sha256(Path("/model/model.gguf")) != model_sha256:
        raise ValueError("DECISION_MODEL_HASH")
    alias = "qm-decision-" + model_sha256
    argv = server_command(alias)
    (output / "runtime.json").write_text(json.dumps({"argv": argv, "model_sha256": model_sha256}))
    end = time.monotonic() + seconds
    process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ready = False
    try:
        # Readiness polling is not generation retry. No POST occurs until identity is verified.
        startup_end = min(end, time.monotonic() + 90)
        while process.poll() is None and time.monotonic() < startup_end:
            try:
                models = http("/v1/models")
                if [row["id"] for row in models["data"]] != [alias]:
                    raise ValueError("DECISION_MODEL_IDENTITY")
                ready = True
                break
            except OSError:
                time.sleep(0.2)
        for case in inputs["cases"]:
            request = payload(inputs, case, alias)
            record = {
                "id": case["id"],
                "input_sha256": input_sha256,
                "model_sha256": model_sha256,
                "request": request,
                "response": None,
                "error": None,
                "elapsed_seconds": 0,
            }
            start = time.monotonic()
            if not ready or process.poll() is not None:
                record["error"] = "DECISION_RUNTIME_UNAVAILABLE"
            elif end - start <= 1:
                record["error"] = "DECISION_COMPARISON_DEADLINE"
            else:
                try:
                    record["response"] = http(
                        "/v1/chat/completions", body=request, timeout=min(180, end - start)
                    )
                except (OSError, ValueError):
                    record["error"] = "DECISION_GENERATION_FAILED"
                    # After a request failure, do not queue more requests behind a hung one.
                    ready = False
            record["elapsed_seconds"] = time.monotonic() - start
            with (output / f"{case['id']}.json").open("x") as stream:
                json.dump(record, stream, ensure_ascii=False)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--seconds", type=int, required=True, choices=range(1, 1201))
    args = parser.parse_args()

    def expired(signum, frame):
        raise TimeoutError("DECISION_COMPARISON_DEADLINE")

    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.seconds)
    try:
        generate(Path("/input/inputs.json"), Path("/output"), args.model_sha256, args.seconds)
    except (OSError, ValueError, KeyError, TypeError):
        raise SystemExit("DECISION_COMPARISON_FAILED: Inspect bounded attempt records.") from None


if __name__ == "__main__":
    main()
