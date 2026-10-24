"""Build a CPU runtime fixture using an existing M1 model and MOCK M6 lineage.

This is not training, a registered real M6 candidate, an owner dataset approval or
a model-quality test. Every synthetic job/adapter/evaluation record is a test double.
The unchanged M1 GGUF was trained and verified separately. Keep this fixture out of
ordinary application data. Run the real package check with make test-export afterward.
"""

import argparse
import json
import shutil
import tarfile
from pathlib import Path
from uuid import uuid4

from quartermaster import exporting, training, training_worker
from quartermaster.config import Settings
from quartermaster.contracts.export import ExportSelection
from quartermaster.export_package import MANIFEST, extract_verified, sha256
from quartermaster.spike.artifacts import extract_verified as extract_spike
from tests import test_teaching, test_training
from tests.test_foundation import select_knowledge, upload


def build_fixture(source, image, output):
    output.mkdir(parents=True, exist_ok=False)
    # Only data extraction and original M1 hashes are trusted, never archive scripts.
    original = extract_spike(source, output / "m1")
    generator = test_teaching.workshop.__wrapped__(
        Settings(data_dir=output / "mock-builder", _env_file=None)
    )
    workshop = next(generator)
    try:
        client, project, _, _, config = workshop
        config.export_runtime_image = image
        selected = upload(
            client,
            project,
            b"# Rental inspection\nA current inspection and no reported damage are required.\n",
            "synthetic-safety.md",
            "knowledge",
        ).json()
        select_knowledge(client, project, [selected["id"]])
        example = test_training.approve(
            workshop, test_training.set_target(workshop, test_training.new_example(workshop))
        )
        test_training.queue(workshop, [example])

        class ExistingModelFixture(test_training.FakeEngine):
            def convert(self, run, job):
                self.stage("converting")
                portable = training.directory(config, run.id) / "output/portable"
                for name in ("model.gguf", "LICENSE.model"):
                    shutil.copyfile(output / "m1" / name, portable / name)

        run = training_worker.execute_next(config, ExistingModelFixture(workshop))
        if run.status != "completed":
            raise RuntimeError("Mock fixture preparation failed")
        manifest = exporting.create_export(
            config,
            project,
            ExportSelection(candidate_id=run.candidate_id, acknowledge_contents=True),
        )
        archive = exporting.archive_path(config, project, manifest.id)
        root = output / "extracted-fixture"
        extract_verified(archive, root)
        readme = root / "README.md"
        readme.write_text(
            "TEST FIXTURE ONLY: M6 job, adapter and evaluation lineage below is MOCKED. "
            "The model bytes are the unchanged previously trained M1 model. "
            "This fixture proves runtime plumbing only; never use it as M6 acceptance evidence.\n\n"
            + readme.read_text()
        )
        record = json.loads((root / MANIFEST).read_bytes())
        record["files"]["README.md"] = {
            "sha256": sha256(readme),
            "size_bytes": readme.stat().st_size,
        }
        (root / MANIFEST).write_text(json.dumps(record, indent=2) + "\n")
        destination = output / "synthetic-lineage-runtime-fixture.tar"
        with tarfile.open(destination, "x", format=tarfile.USTAR_FORMAT) as tar:
            for name in sorted(set(record["files"]) | {MANIFEST}):
                info = tarfile.TarInfo(name)
                info.size = (root / name).stat().st_size
                info.mode = 0o644
                with (root / name).open("rb") as stream:
                    tar.addfile(info, stream)
        (output / "fixture-record.json").write_text(
            json.dumps(
                {
                    "scope": "CPU runtime integration only; M6 lineage mocked; no training",
                    "source_m1_archive_sha256": sha256(source),
                    "source_m1_model_sha256": original["files"]["model.gguf"]["sha256"],
                    "fixture_archive_sha256": sha256(destination),
                    "runtime_image": image,
                },
                indent=2,
            )
            + "\n"
        )
        return destination
    finally:
        generator.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-spike", type=Path, required=True)
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path("data/export-smoke-fixtures") / str(uuid4())
    )
    args = parser.parse_args()
    print(build_fixture(args.source_spike.resolve(), args.runtime_image, args.output.resolve()))


if __name__ == "__main__":
    main()
