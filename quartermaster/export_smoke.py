"""Verify a fresh standalone archive with an isolated, offline CPU Compose project."""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from uuid import uuid4

from quartermaster.contracts.export import RuntimeAdvice
from quartermaster.errors import DomainError
from quartermaster.export_package import extract_verified, sha256
from quartermaster.exporting import compose_text
from quartermaster.spike.spec import LLAMA_REVISION


def command(args, *, timeout=30, input_text=None):
    try:
        result = subprocess.run(
            args, input=input_text, text=True, capture_output=True, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        raise DomainError(
            "EXPORT_DOCKER: Check Docker availability and the bounded runtime deadline.", 503
        ) from None
    if result.returncode:
        raise DomainError(
            "EXPORT_DOCKER: Container command failed; "
            "check the exact image, resources and original package.",
            503,
        )
    return result.stdout


def verify_image(image, contract="quartermaster.export/v1"):
    try:
        result = json.loads(command(["docker", "image", "inspect", image]))[0]
        labels = result["Config"].get("Labels") or {}
        if (
            result["Id"] != image
            or labels.get("org.opencontainers.image.revision") != LLAMA_REVISION
            or labels.get("io.quartermaster.export-contract")
            not in {
                "quartermaster.export/v1": {
                    "quartermaster.export/v1",
                    "quartermaster.export/v2",
                    "quartermaster.export/v3",
                },
                "quartermaster.export/v2": {"quartermaster.export/v2", "quartermaster.export/v3"},
                "quartermaster.export/v3": {"quartermaster.export/v3"},
            }.get(contract, set())
        ):
            raise ValueError
    except (DomainError, ValueError, KeyError, TypeError, IndexError):
        raise DomainError(
            "EXPORT_IMAGE: Build or load the exact standard "
            "standalone runtime image named in this manifest.",
            409,
        ) from None


def smoke(archive, report_path=None):
    if archive.is_symlink() or not archive.is_file():
        raise DomainError("EXPORT_ARCHIVE: Choose a complete original regular archive file.", 404)
    report_path = report_path or archive.parent / f"export-check-{uuid4()}.json"
    report = {
        "schema_version": "quartermaster.export-check/v1",
        "status": "failed",
        "archive_sha256": sha256(archive),
        "network": "none",
        "gpu": False,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="qm-export-") as temp:
            outer = Path(temp)
            outer.chmod(0o755)
            root = outer / "adviser"
            manifest, _, _, reference = extract_verified(archive, root)
            root.chmod(0o755)
            if (root / "compose.yaml").read_text() != compose_text(manifest.runtime_image):
                raise DomainError(
                    "EXPORT_COMPOSE: Only the fixed standard runtime "
                    "Compose recipe may be executed.",
                    409,
                )
            verify_image(manifest.runtime_image, manifest.schema_version)
            override = outer / "isolation.yaml"
            override.write_text(
                "services:\n  adviser:\n    ports: !reset []\n    network_mode: none\n"
            )
            project = f"qm-export-{uuid4().hex}"
            report["compose_project"] = project
            compose = [
                "docker",
                "compose",
                "--project-name",
                project,
                "--project-directory",
                str(root),
                "-f",
                str(root / "compose.yaml"),
                "-f",
                str(override),
            ]
            try:
                try:
                    command([*compose, "up", "-d", "--wait", "--wait-timeout", "360"], timeout=420)
                except DomainError:
                    raise DomainError(
                        "EXPORT_STARTUP: CPU model startup failed. Check RAM, CPU support "
                        "and restore the original package with its exact runtime image.",
                        503,
                    ) from None
                container = command([*compose, "ps", "-q", "adviser"]).strip()
                state = json.loads(command(["docker", "inspect", container]))[0]
                if (
                    state["Image"] != manifest.runtime_image
                    or state["HostConfig"]["NetworkMode"] != "none"
                    or state["HostConfig"].get("DeviceRequests")
                    or set(m["Destination"] for m in state["Mounts"] if m["Type"] == "bind")
                    != {"/package"}
                    or state["HostConfig"].get("PortBindings")
                ):
                    raise DomainError(
                        "EXPORT_ISOLATION: Runtime did not match the fixed isolation recipe.", 409
                    )
                script = (
                    "import importlib.util,json,sys,urllib.request; "
                    "assert all(importlib.util.find_spec('quartermaster.'+name) is None "
                    "for name in ('db','builder','training','app')); "
                    "body=sys.stdin.buffer.read(); "
                    "opener=urllib.request.build_opener(urllib.request.ProxyHandler({})); "
                    "request=urllib.request.Request('http://127.0.0.1:8080/v1/advise', "
                    "data=body,headers={'Content-Type':'application/json'}); "
                    "print(opener.open(request,timeout=185).read(131073).decode())"
                )
                raw = command(
                    ["docker", "exec", "-i", container, "python", "-c", script],
                    timeout=200,
                    input_text=reference.case.model_dump_json(),
                )
                if len(raw.encode()) > 131_072:
                    raise DomainError(
                        "EXPORT_RESPONSE: Standalone reply exceeded the response bound.", 409
                    )
                response = RuntimeAdvice.model_validate_json(raw)
                response.advice.check_evidence({str(e.citation_id) for e in response.evidence})
                if (
                    response.export_id != manifest.id
                    or response.candidate_id != manifest.candidate_id
                    or response.context_sha256 != reference.context_sha256
                    or [e.citation_id for e in response.evidence] != reference.evidence_ids
                ):
                    raise DomainError(
                        "EXPORT_REFERENCE: Runtime context or citations "
                        "differ from the evaluated snapshot.",
                        409,
                    )
                report.update(
                    status="passed",
                    export_id=str(manifest.id),
                    candidate_id=str(manifest.candidate_id),
                    runtime_image=manifest.runtime_image,
                    context_sha256=response.context_sha256,
                    schema_valid=True,
                    citations_valid=True,
                    database_absent=True,
                    builder_provider_absent=True,
                    evidence_count=len(response.evidence),
                    asks_clarification=bool(response.advice.clarification_question),
                )
            finally:
                try:
                    command([*compose, "down", "--timeout", "10"], timeout=60)
                except DomainError:
                    raise DomainError(
                        "EXPORT_CLEANUP: Restore Docker, then remove the containers labeled "
                        f"com.docker.compose.project={project}. See the separate check report.",
                        503,
                    ) from None
    except DomainError as exc:
        report["error"] = exc.message.split(":", 1)[0]
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        report["error"] = "EXPORT_CHECK"
        raise DomainError(
            "EXPORT_CHECK: Invalid runtime response or verification files.", 409
        ) from None
    finally:
        with report_path.open("x") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        path = smoke(args.archive.resolve(), args.report)
    except DomainError as exc:
        raise SystemExit(exc.message) from None
    print(f"Standalone CPU export check passed. Report: {path}")


if __name__ == "__main__":
    main()
