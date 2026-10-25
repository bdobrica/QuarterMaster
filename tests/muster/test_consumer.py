import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from muster.knowledge import save_article
from muster.publication import get_publication, overview, publish
from muster.storage import connect
from tests.muster.test_publication import reviewed


def test_standalone_consumer_without_muster_imports_and_type_rejection(tmp_path):
    data = tmp_path / "data"
    cid = reviewed(data, 2)
    save_article(data, cid, None, 0, "My preference", "This decision is mine.")
    with connect(data) as db:
        db.execute("UPDATE reviews SET status='needs_review',reviewed_at=NULL WHERE job_id=2")
    pid = publish(data, cid, overview(data, cid)["fingerprint"])
    sandbox = tmp_path / "consumer"
    sandbox.mkdir()
    bundle = sandbox / "bundle"
    shutil.copytree(data / get_publication(data, cid, pid)["path"], bundle)
    for script in ("consume_bundle.py", "check_bundle.py"):
        shutil.copyfile(Path("scripts/muster") / script, sandbox / script)
    # -I excludes PYTHONPATH and the repository; -S excludes installed packages.
    # Only the two copied scripts and standard library are reachable.
    command = [
        sys.executable,
        "-I",
        "-S",
        "-c",
        "import sys; sys.path.insert(0,'.'); import consume_bundle; consume_bundle.main()",
        str(bundle),
    ]
    result = subprocess.run(command, cwd=sandbox, capture_output=True, text=True, check=True)
    output = json.loads(result.stdout)
    assert len(output["examples"]) == 1 and output["skipped_unreviewed"] == 1
    assert output["examples"][0]["values"]["price"] == 80001
    assert output["knowledge"][0]["body"] == "This decision is mine."
    result = subprocess.run(
        command + ["--include-unreviewed"], cwd=sandbox, capture_output=True, text=True, check=True
    )
    assert len(json.loads(result.stdout)["examples"]) == 2
    records = [json.loads(line) for line in (bundle / "examples.jsonl").read_text().splitlines()]
    records[0]["values"]["price"] = "not a number"
    (bundle / "examples.jsonl").write_text("".join(json.dumps(record) + "\n" for record in records))
    manifest = json.loads((bundle / "manifest.json").read_text())
    manifest["checksums"]["examples.jsonl"] = hashlib.sha256(
        (bundle / "examples.jsonl").read_bytes()
    ).hexdigest()
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    result = subprocess.run(command, cwd=sandbox, capture_output=True, text=True)
    assert result.returncode == 1 and "Invalid value for field price" in result.stderr
    # Damage is still detected before any consumer output.
    (bundle / "examples.jsonl").write_text("{}\n")
    result = subprocess.run(command, cwd=sandbox, capture_output=True, text=True)
    assert result.returncode == 1 and "Checksum mismatch" in result.stderr and not result.stdout
