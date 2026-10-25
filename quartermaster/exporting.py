"""Package an evaluated candidate's immutable context. No Docker socket or training."""

import json
import shutil
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from quartermaster import evaluations, knowledge, teaching, training
from quartermaster.contracts.adviser import ModelSpec
from quartermaster.contracts.export import (
    ExportKnowledge,
    ExportLesson,
    ExportManifest,
    ExportReference,
    ExportSource,
    RuntimeConfiguration,
    RuntimeInput,
)
from quartermaster.contracts.sources import Chunk
from quartermaster.contracts.teaching import Lesson
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.export_package import (
    FIXED,
    MANIFEST,
    PackageContext,
    checked_path,
    content_hash,
    sha256,
    verify_package,
)
from quartermaster.generation import checked_parameters
from quartermaster.inference import response_schema
from quartermaster.projects import read_spec
from quartermaster.sources import read_source, source_bytes
from quartermaster.training_artifacts import verify_candidate


def directory(settings, project_id, export_id=None):
    path = settings.artifact_root / "exports" / str(UUID(str(project_id)))
    if export_id:
        path /= str(UUID(str(export_id)))
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise DomainError("EXPORT_PATH: Restore the controlled artifact directory.", 409)
    return path


def get_export(settings, project_id, export_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
    path = directory(settings, project_id, export_id)
    try:
        manifest_path = checked_path(path, MANIFEST)
        if manifest_path.stat().st_size > 128_000:
            raise ValueError
        manifest = ExportManifest.model_validate_json(manifest_path.read_bytes())
        if manifest.id != UUID(str(export_id)) or manifest.project_id != UUID(str(project_id)):
            raise ValueError
        fingerprint = path / "archive.json"
        if fingerprint.is_symlink() or fingerprint.stat().st_size > 4096:
            raise ValueError
        record = json.loads(fingerprint.read_bytes())
        archive = path / "adviser.tar"
        if archive.is_symlink() or archive.stat().st_size != record["size_bytes"]:
            raise ValueError
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError(
            "EXPORT_MISSING: Create a new export or restore its original archive.", 404
        ) from None


def list_exports(settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
    root = directory(settings, project_id)
    if not root.exists():
        return []
    result = []
    for path in sorted(root.iterdir(), reverse=True):
        try:
            UUID(path.name)
        except ValueError:
            continue
        # Partial builds deliberately lack archive.json and cannot be downloaded.
        if (path / "archive.json").is_file():
            result.append(get_export(settings, project_id, path.name))
    return sorted(result, key=lambda x: x.created_at, reverse=True)


def archive_path(settings, project_id, export_id):
    get_export(settings, project_id, export_id)
    path = directory(settings, project_id, export_id)
    record = json.loads((path / "archive.json").read_bytes())
    archive = path / "adviser.tar"
    if sha256(archive) != record["sha256"]:
        raise DomainError("EXPORT_HASH: Restore the original archive or create a new export.", 409)
    return archive


def frozen_lessons(connection, project_id, spec):
    if spec.lessons_revision is None:
        return []
    # The pointer is the last applied lesson ID. Applied is terminal, so replaying
    # rows through that event recovers the exact full set, including unretrieved lessons.
    end = connection.execute(
        "SELECT rowid FROM lesson_revisions WHERE project_id=? AND id=? "
        "AND json_extract(document, '$.status')='applied'",
        (str(project_id), str(spec.lessons_revision)),
    ).fetchone()
    if end is None:
        raise DomainError("EXPORT_LESSONS: Restore the evaluated lesson history.", 409)
    rows = connection.execute(
        "SELECT document FROM lesson_revisions WHERE project_id=? AND rowid<=? "
        "AND json_extract(document, '$.status')='applied' ORDER BY rowid",
        (str(project_id), end[0]),
    )
    return [
        ExportLesson(
            id=lesson.id, revision=lesson.revision, created_at=lesson.created_at, text=lesson.text
        )
        for lesson in (Lesson.model_validate_json(row[0]) for row in rows)
    ]


def compose_text(image):
    # Fixed, reviewed application; no interpolated owner text, host paths or commands.
    return f"""services:
  adviser:
    image: {image}
    pull_policy: never
    ports: ["127.0.0.1:8081:8080"]
    volumes: ["./:/package:ro"]
    read_only: true
    cap_drop: ["ALL"]
    security_opt: ["no-new-privileges:true"]
    tmpfs: ["/tmp:rw,nosuid,nodev,size=64m"]
    init: true
    mem_limit: 4g
    cpus: 4
    pids_limit: 128
    logging:
      driver: none
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
      interval: 10s
      timeout: 5s
      start_period: 180s
      retries: 12
"""


def operator_readme(manifest, size):
    lineage = (
        f"Unchanged base; tested snapshot {manifest.source_test_id}.\n"
        "This is a working-adviser snapshot, not a claim of evaluated model improvement.\n"
        "Bounded local thinking is enabled; no training occurred during export."
        if manifest.schema_version == "quartermaster.export/v3"
        else f"Candidate {manifest.candidate_id}; evaluated suite {manifest.suite_id} "
        f"revision {manifest.suite_revision}."
    )
    if manifest.schema_version == "quartermaster.export/v4":
        lineage = (
            f"Candidate {manifest.candidate_id}; reviewed teaching {manifest.teaching_sha256}. "
            "Taught replay measures preference consistency, not unseen accuracy."
        )
    response_field = (
        "prediction" if manifest.schema_version == "quartermaster.export/v4" else "advice"
    )
    return f"""# Standalone adviser

Export {manifest.id}; adviser revision {manifest.evaluated_adviser_revision}.
{lineage}
The package freezes tested context, including its selected knowledge and approved
lessons. Later builder edits are absent. Exporting never trains or converts weights.

## Start

Docker Engine with Compose v2 and this exact local runtime image are required:
`{manifest.runtime_image}`. Obtain the matching standard runtime image from your
operator first (`docker load` from a trusted image bundle on another host).
`docker image inspect {manifest.runtime_image}` must succeed. The package does not
contain the image. A mutable tag or a different image is not a substitute.

Extract the archive into a new directory; run these commands from that directory:

```sh
docker compose up -d --wait --wait-timeout 360
docker compose logs adviser
docker compose down
```

Open http://127.0.0.1:8081. Advice API: `POST /v1/advise` with JSON
`{{"situation":"Describe the decision-time facts", "choices":[]}}`.
The response contains validated `{response_field}`, accessible evidence excerpts and snapshot
identifiers. `GET /healthz` succeeds only after package/model verification and engine startup.
No builder container, database, credentials or frontier API is required. Core advice
uses an internal loopback CPU engine. Logs intentionally omit advice and raw model text.

## Resources and verification

Requires a CPU supporting this portable llama.cpp build, Docker with 4 GiB RAM
available for this service and four CPU threads. Model: {size} bytes; allow at least
twice the archive size for archive plus extraction, plus image space. CPU advice
can take minutes; one request at a time, 180-second limit, no automatic retries.
The pinned engine is {manifest.engine_revision}; GGUF v3 / Q8_0, 8192 context,
{manifest.inference_parameters["max_tokens"]} output tokens.
GPU acceleration and offline image distribution are deferred.

Packaging verifies bytes, provenance and the frozen reference context. It does not
prove this package has started. The operator must run the repository's documented
`make test-export EXPORT=/absolute/adviser.tar` before claiming runtime verification.
That command extracts into a new directory, uses an isolated Compose project with
no external network or host ports and checks health, the reference context, advice
schema and accessible citations. Its JSON report is separate from this immutable archive.

If the image is missing, load the exact image. For model startup failure, check RAM
and CPU support. For EXPORT_INVALID/hash/format errors, restore the original archive
or create a new export; never edit manifest hashes to bypass verification.
Only localhost is published. Authentication and public internet hosting are outside
this local single-user MVP. Selected knowledge, lessons and one decision-time
evaluation case are business content: protect the archive accordingly. No rubric,
observed outcomes, training rows, raw corrections or provider credentials are packaged.
Advice quality is limited; matching schema and citations does not establish correctness
or business lift. Review limitations and missing-information questions.
"""


def create_export(settings, project_id, selection):
    if settings.export_runtime_image is None:
        raise DomainError(
            "EXPORT_IMAGE: Build the standard runtime and set "
            "QM_EXPORT_RUNTIME_IMAGE to its exact sha256 image ID.",
            409,
        )
    version = training.get_version(settings, project_id, selection.candidate_id)
    run = training.get_run(settings, project_id, version.training_run_id)
    if run.status != "completed" or run.candidate_id != version.id or not version.smoke_passed:
        raise DomainError("EXPORT_CANDIDATE: Choose a completed, evaluated candidate.", 409)
    portable = verify_candidate(settings, version)
    if version.schema_version == "quartermaster.adviser-version/v2":
        return create_prediction_export(settings, project_id, version, run, portable)
    suite = evaluations.get_suite(settings, project_id, version.suite_id, version.suite_revision)
    evaluations.verify_frozen(suite)
    if suite.frozen_sha256 != version.suite_sha256 or not suite.inputs:
        raise DomainError("EXPORT_SUITE: Restore the candidate's frozen evaluation.", 409)
    spec = suite.inputs[0].b.adviser
    if any(p.b.adviser != spec for p in suite.inputs):
        raise DomainError(
            "EXPORT_CONTEXT: Evaluation contains inconsistent adviser snapshots.", 409
        )
    if len(version.comparisons) != len(suite.inputs) or any(
        p.case_id != c.case_id or p.b.input_sha256 != c.candidate.input_sha256
        for p, c in zip(suite.inputs, version.comparisons, strict=True)
    ):
        raise DomainError("EXPORT_LINEAGE: Candidate was not evaluated on these inputs.", 409)
    with connect(settings.database_path) as connection:
        lessons = frozen_lessons(connection, project_id, spec)
        revision = (
            knowledge.read_revision(connection, project_id, spec.knowledge_revision)
            if spec.knowledge_revision
            else None
        )
        sources = (
            [read_source(connection, project_id, s) for s in revision.source_ids]
            if revision
            else []
        )
        if {str(s.id): s.sha256 for s in sources} != suite.source_hashes:
            raise DomainError("EXPORT_SOURCE: Restore the evaluated source selection.", 409)
        chunks = []
        for source in sources:
            rows = connection.execute(
                "SELECT document FROM chunks WHERE source_id=? ORDER BY id", (str(source.id),)
            )
            chunks.extend(Chunk.model_validate_json(row[0]) for row in rows)
    frozen = type(spec).model_validate(
        {**spec.model_dump(), "model": ModelSpec(adapter_artifact=version.id)}
    )
    config = RuntimeConfiguration(adviser=frozen, lessons=lessons)
    material = ExportKnowledge(
        sources=[
            ExportSource(id=s.id, display_name=s.display_name, sha256=s.sha256) for s in sources
        ],
        chunks=chunks,
    )
    prompt_version = suite.inputs[0].b.prompt_version
    context = PackageContext(config, material, prompt_version=prompt_version)
    parameters = checked_parameters(suite.inputs[0].b.parameters)
    try:
        for entry, pair in zip(suite.cases, suite.inputs, strict=True):
            _, text, evidence, selected, omitted = context.assemble(entry.case)
            if (
                text != pair.b.context
                or evidence != pair.b.evidence
                or selected != pair.b.lessons
                or omitted != (pair.b.omitted_lessons, pair.b.omitted_excerpts)
                or pair.b.system != teaching.SYSTEM
                or pair.b.parameters != parameters
                or pair.b.response_schema != response_schema(text)
            ):
                raise DomainError(
                    "EXPORT_CONTEXT: Standalone retrieval differs from the frozen evaluation. "
                    "Re-evaluate the selected context before exporting.",
                    409,
                )
    finally:
        context.close()
    first = suite.cases[0].case
    reference = ExportReference(
        case=RuntimeInput(situation=first.situation, choices=first.choices, case_id=first.case_id),
        context_sha256=content_hash(suite.inputs[0].b.context),
        evidence_ids=[e.citation_id for e in suite.inputs[0].b.evidence],
    )
    data = dict(
        schema_version="quartermaster.export/v2",
        prompt_version=prompt_version,
        inference_parameters=parameters,
        id=uuid4(),
        project_id=UUID(str(project_id)),
        created_at=datetime.now(UTC),
        candidate_id=version.id,
        training_run_id=version.training_run_id,
        candidate_sha256=content_hash(version.model_dump_json()),
        job_sha256=version.job_sha256,
        training_manifest_sha256=version.training_manifest_sha256,
        suite_id=version.suite_id,
        suite_revision=version.suite_revision,
        suite_sha256=version.suite_sha256,
        evaluated_adviser_revision=spec.revision,
        knowledge_revision=spec.knowledge_revision,
        lessons_revision=spec.lessons_revision,
        source_hashes=suite.source_hashes,
        runtime_image=settings.export_runtime_image,
        files={},
    )
    return write_package(
        settings,
        project_id,
        config,
        material,
        sources,
        reference,
        portable,
        data,
        version.model_sha256,
        version.license_sha256,
    )


def create_base_export(settings, project_id, selection):
    """Package a successful base test, without inventing candidate/evaluation lineage."""
    from quartermaster.advice_context import ADVICE_PROMPT_VERSION, system_for
    from quartermaster.generation import ADVICE_PARAMETERS
    from quartermaster.inference import model_alias
    from quartermaster.local_runtime import verify

    if settings.export_runtime_image is None:
        raise DomainError("EXPORT_IMAGE: Configure the pinned standalone runtime image.", 409)
    run = teaching.get_test(settings, project_id, selection.test_id)
    if run.provider != "local":
        raise DomainError(
            "EXPORT_HOSTED: Hosted advice is not an offline export. Test a local model first.", 409
        )
    portable = settings.local_model_dir
    try:
        base = verify(portable)
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError(
            "EXPORT_BASE: Restore the pinned base bundle and model directory.", 409
        ) from None
    if (
        run.error
        or run.advice is None
        or run.draft is None
        or run.prompt_version != ADVICE_PROMPT_VERSION
        or run.model_alias != model_alias(base["sha256"])
        or run.model_role == "existing_lora"
        or run.parameters != ADVICE_PARAMETERS
        or run.system != system_for(run.prompt_version)
        or run.response_schema != response_schema(run.context, bounded=True)
    ):
        raise DomainError("EXPORT_TEST: Choose a successful bounded-thinking base test first.", 409)
    spec = run.adviser.model_copy(update={"model": ModelSpec()})
    with connect(settings.database_path) as connection:
        lessons = frozen_lessons(connection, project_id, spec)
        revision = (
            knowledge.read_revision(connection, project_id, spec.knowledge_revision)
            if spec.knowledge_revision
            else None
        )
        sources = (
            [read_source(connection, project_id, s) for s in revision.source_ids]
            if revision
            else []
        )
        chunks = []
        for source in sources:
            rows = connection.execute(
                "SELECT document FROM chunks WHERE source_id=? ORDER BY id", (str(source.id),)
            )
            chunks.extend(Chunk.model_validate_json(row[0]) for row in rows)
    config = RuntimeConfiguration(adviser=spec, lessons=lessons)
    material = ExportKnowledge(
        sources=[
            ExportSource(id=s.id, display_name=s.display_name, sha256=s.sha256) for s in sources
        ],
        chunks=chunks,
    )
    context = PackageContext(config, material, prompt_version=run.prompt_version)
    try:
        _, text, evidence, selected, _ = context.assemble(run.case)
        if text != run.context or evidence != run.evidence or selected != run.lessons:
            raise DomainError("EXPORT_CONTEXT: Restore the tested knowledge and lessons.", 409)
    finally:
        context.close()
    reference = ExportReference(
        case=RuntimeInput(
            situation=run.case.situation, choices=run.case.choices, case_id=run.case.case_id
        ),
        context_sha256=content_hash(run.context),
        evidence_ids=[e.citation_id for e in run.evidence],
    )
    data = dict(
        schema_version="quartermaster.export/v3",
        id=uuid4(),
        project_id=UUID(str(project_id)),
        created_at=datetime.now(UTC),
        candidate_id=None,
        training_run_id=None,
        candidate_sha256=None,
        job_sha256=None,
        training_manifest_sha256=None,
        suite_id=None,
        suite_revision=None,
        suite_sha256=None,
        source_test_id=run.id,
        source_test_sha256=content_hash(run.model_dump_json()),
        evaluated_adviser_revision=spec.revision,
        knowledge_revision=spec.knowledge_revision,
        lessons_revision=spec.lessons_revision,
        source_hashes={str(s.id): s.sha256 for s in sources},
        runtime_image=settings.export_runtime_image,
        prompt_version=run.prompt_version,
        inference_parameters=run.parameters,
        files={},
    )
    return write_package(
        settings,
        project_id,
        config,
        material,
        sources,
        reference,
        portable,
        data,
        base["sha256"],
        base["license_sha256"],
    )


def create_prediction_export(settings, project_id, version, run, portable):
    """Package the exact generic training/replay knowledge, with a typed offline response."""
    from quartermaster.generation import PARAMETERS

    job = training.read_job(settings, run)
    if (
        job.schema_version != "quartermaster.training-job/v2"
        or version.teaching_sha256 != job.teaching_sha256
        or version.answer_format != job.answer_format
    ):
        raise DomainError("EXPORT_TEACHING: Candidate teaching lineage differs.", 409)
    spec = job.adviser.model_copy(update={"model": ModelSpec(adapter_artifact=version.id)})
    with connect(settings.database_path) as connection:
        sources = [
            read_source(connection, project_id, item.source.id) for item in job.teaching.knowledge
        ]
        chunks = []
        for source in sources:
            rows = connection.execute(
                "SELECT document FROM chunks WHERE source_id=? ORDER BY id", (str(source.id),)
            )
            chunks.extend(Chunk.model_validate_json(row[0]) for row in rows)
    if {str(s.id): s.sha256 for s in sources} != job.source_hashes:
        raise DomainError("EXPORT_KNOWLEDGE: Restore the captured knowledge sources.", 409)
    config = RuntimeConfiguration(adviser=spec, lessons=[], answer_format=job.answer_format)
    material = ExportKnowledge(
        sources=[
            ExportSource(id=s.id, display_name=s.display_name, sha256=s.sha256) for s in sources
        ],
        chunks=chunks,
    )
    context = PackageContext(config, material, prompt_version="context/v4")
    first = job.examples[0].input
    try:
        _, text, evidence, _, _ = context.assemble(first.case)
        if text != first.context or evidence != first.evidence:
            raise DomainError("EXPORT_CONTEXT: Restore the exact replayed knowledge.", 409)
    finally:
        context.close()
    reference = ExportReference(
        case=RuntimeInput(situation=first.case.situation, case_id=first.case.case_id),
        context_sha256=content_hash(first.context),
        evidence_ids=[e.citation_id for e in first.evidence],
    )
    data = dict(
        schema_version="quartermaster.export/v4",
        prompt_version="context/v4",
        inference_parameters=PARAMETERS,
        id=uuid4(),
        project_id=UUID(str(project_id)),
        created_at=datetime.now(UTC),
        candidate_id=version.id,
        training_run_id=run.id,
        candidate_sha256=content_hash(version.model_dump_json()),
        job_sha256=run.job_sha256,
        training_manifest_sha256=version.training_manifest_sha256,
        suite_id=None,
        suite_revision=None,
        suite_sha256=None,
        evaluated_adviser_revision=spec.revision,
        knowledge_revision=spec.knowledge_revision,
        lessons_revision=spec.lessons_revision,
        source_hashes=job.source_hashes,
        teaching_sha256=job.teaching_sha256,
        runtime_image=settings.export_runtime_image,
        files={},
    )
    return write_package(
        settings,
        project_id,
        config,
        material,
        sources,
        reference,
        portable,
        data,
        version.model_sha256,
        version.license_sha256,
    )


def write_package(
    settings,
    project_id,
    config,
    material,
    sources,
    reference,
    portable,
    data,
    model_sha256,
    license_sha256,
):
    export_id = data["id"]
    model_size = (portable / "model.gguf").stat().st_size
    root = directory(settings, project_id, export_id)
    required = model_size * 2 + 64_000_000
    if shutil.disk_usage(settings.data_dir).free < required:
        raise DomainError(
            "EXPORT_DISK: Free space for two copies of the model plus 64 MB metadata.", 409
        )
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        for folder in ("model", "knowledge/sources", "manifests"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        for name in ("model.gguf", "LICENSE.model"):
            shutil.copyfile(portable / name, root / "model" / name)
        license_path = Path(__file__).parents[1] / "LICENSE"
        if not license_path.is_file():
            license_path = Path("/app/LICENSE")
        shutil.copyfile(license_path, root / "LICENSE")
        (root / "adviser.json").write_text(config.model_dump_json(indent=2) + "\n")
        (root / "knowledge/chunks.json").write_text(material.model_dump_json(indent=2) + "\n")
        (root / "reference.json").write_text(reference.model_dump_json(indent=2) + "\n")
        for source in sources:
            (root / f"knowledge/sources/{source.id}.md").write_bytes(source_bytes(settings, source))
            for chunk in (c for c in material.chunks if c.source_id == source.id):
                knowledge.verify_excerpt(settings, source, chunk)
        (root / "compose.yaml").write_text(compose_text(settings.export_runtime_image))
        placeholder = ExportManifest(**data)
        (root / "README.md").write_text(operator_readme(placeholder, model_size))
        names = FIXED | {f"knowledge/sources/{s.id}.md" for s in sources}
        data["files"] = {
            name: {"sha256": sha256(root / name), "size_bytes": (root / name).stat().st_size}
            for name in sorted(names)
        }
        manifest = ExportManifest(**data)
        (root / MANIFEST).write_text(manifest.model_dump_json(indent=2) + "\n")
        verify_package(root)
        if (
            manifest.files["model/model.gguf"].sha256 != model_sha256
            or manifest.files["model/LICENSE.model"].sha256 != license_sha256
        ):
            raise DomainError("EXPORT_MODEL: Candidate bytes changed while copying.", 409)
        archive = root / "adviser.tar"
        with tarfile.open(archive, "x", format=tarfile.USTAR_FORMAT) as tar:
            for name in sorted(names | {MANIFEST}):
                info = tarfile.TarInfo(name)
                info.size = (root / name).stat().st_size
                info.mode = 0o644
                info.mtime = 0
                with (root / name).open("rb") as stream:
                    tar.addfile(info, stream)
        (root / "archive.json").write_text(
            json.dumps({"sha256": sha256(archive), "size_bytes": archive.stat().st_size})
        )
        # Keep only immutable archive + manifest + archive fingerprint on builder disk.
        for name in names:
            (root / name).unlink()
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        raise DomainError(
            "EXPORT_BUILD: Packaging failed; check disk space and restore verified artifacts.", 409
        ) from None
