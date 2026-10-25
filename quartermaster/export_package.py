"""Data-only package verification and standalone retrieval. Never opens builder storage."""

import bisect
import hashlib
import re
import sqlite3
import tarfile

from quartermaster.advice_context import (
    ADVICE_PROMPT_VERSION,
    PROMPT_VERSION,
    assemble_context,
    knowledge_order,
)
from quartermaster.contracts.export import (
    ExportKnowledge,
    ExportManifest,
    ExportReference,
    RuntimeConfiguration,
)
from quartermaster.errors import DomainError

FIXED = {
    "adviser.json",
    "knowledge/chunks.json",
    "model/model.gguf",
    "model/LICENSE.model",
    "LICENSE",
    "compose.yaml",
    "README.md",
    "reference.json",
}
MANIFEST = "manifests/export.json"
MAX_TOTAL = 3_100_000_000


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def safe_name(name):
    return name in FIXED | {MANIFEST} or bool(
        re.fullmatch(r"knowledge/sources/[a-f0-9-]{36}\.md", name)
    )


def checked_path(root, name):
    if not safe_name(name):
        raise ValueError("Unexpected package path")
    path = root / name
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("Missing file or unsupported link")
    return path


def read_small(root, name, limit):
    path = checked_path(root, name)
    if path.stat().st_size > limit:
        raise ValueError("Metadata exceeds size limit")
    return path.read_bytes()


def verify_package(root):
    """Hashes, strict contracts, excerpt provenance and allowlist are all mandatory."""
    try:
        manifest = ExportManifest.model_validate_json(read_small(root, MANIFEST, 128_000))
        if not FIXED <= set(manifest.files) or any(
            not safe_name(name) or name == MANIFEST for name in manifest.files
        ):
            raise ValueError("Unexpected package files")
        if sum(f.size_bytes for f in manifest.files.values()) > MAX_TOTAL:
            raise ValueError("Package too large")
        for name, record in manifest.files.items():
            path = checked_path(root, name)
            if path.stat().st_size != record.size_bytes or sha256(path) != record.sha256:
                raise ValueError("Package hash mismatch")
        config = RuntimeConfiguration.model_validate_json(
            read_small(root, "adviser.json", 8_000_000)
        )
        knowledge = ExportKnowledge.model_validate_json(
            read_small(root, "knowledge/chunks.json", 32_000_000)
        )
        reference = ExportReference.model_validate_json(read_small(root, "reference.json", 64_000))
        if reference.case.case_id is None:
            raise ValueError("The frozen reference needs its original case ID")
        spec = config.adviser
        if (manifest.prompt_version in ("context/v4", "context/v5")) != (
            config.answer_format is not None
        ):
            raise ValueError("Prediction format and package contract differ")
        if (
            manifest.prompt_version in ("context/v4", "context/v5")
            and spec.outputs != "quartermaster.prediction/v1"
        ):
            raise ValueError("Generic packages require a prediction output contract")
        if (
            spec.id != manifest.project_id
            or spec.model.adapter_artifact != manifest.candidate_id
            or spec.revision != manifest.evaluated_adviser_revision
            or spec.knowledge_revision != manifest.knowledge_revision
            or spec.lessons_revision != manifest.lessons_revision
            or len({str(s.id) for s in knowledge.sources}) != len(knowledge.sources)
            or len({str(c.citation_id) for c in knowledge.chunks}) != len(knowledge.chunks)
            or len({str(lesson.id) for lesson in config.lessons}) != len(config.lessons)
            or {str(s.id): s.sha256 for s in knowledge.sources} != manifest.source_hashes
        ):
            raise ValueError("Snapshot lineage mismatch")
        expected_paths = FIXED | {f"knowledge/sources/{s.id}.md" for s in knowledge.sources}
        if set(manifest.files) != expected_paths:
            raise ValueError("Source selection mismatch")
        sources = {}
        for source in knowledge.sources:
            name = f"knowledge/sources/{source.id}.md"
            raw = read_small(root, name, 8 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != source.sha256:
                raise ValueError("Source hash mismatch")
            text = raw.decode("utf-8-sig")
            sources[source.id] = (source, text, [m.start() for m in re.finditer("\n", text)])
        for chunk in knowledge.chunks:
            source, text, newlines = sources[chunk.source_id]
            if (
                source.sha256 != chunk.source_sha256
                or not 0 <= chunk.start < chunk.end <= len(text)
                or text[chunk.start : chunk.end] != chunk.text
                or content_hash(chunk.text) != chunk.sha256
                or bisect.bisect_left(newlines, chunk.start) + 1 != chunk.line_start
                or bisect.bisect_left(newlines, chunk.end - 1) + 1 != chunk.line_end
            ):
                raise ValueError("Excerpt does not correspond to original bytes")
        model = checked_path(root, "model/model.gguf")
        with model.open("rb") as stream:
            if (
                not 1_000_000 < model.stat().st_size < 3_000_000_000
                or stream.read(8) != b"GGUF\3\0\0\0"
            ):
                raise ValueError("Expected bounded GGUF v3")
        if not read_small(root, "model/LICENSE.model", 100_000).strip():
            raise ValueError("Missing model license")
        return manifest, config, knowledge, reference
    except (OSError, ValueError, KeyError, TypeError, RecursionError, UnicodeError):
        raise DomainError(
            "EXPORT_INVALID: Restore an unchanged package; "
            "model, metadata or citation verification failed.",
            409,
        ) from None


class PackageContext:
    def __init__(self, config, knowledge, *, prompt_version=PROMPT_VERSION):
        self.config = config
        self.prompt_version = prompt_version
        self.chunks = {str(c.citation_id): c for c in knowledge.chunks}
        self.sources = {s.id: s for s in knowledge.sources}
        self.index = sqlite3.connect(":memory:", check_same_thread=False)
        self.index.execute(
            "CREATE VIRTUAL TABLE chunks_fts USING fts5(citation_id UNINDEXED, text)"
        )
        self.index.executemany(
            "INSERT INTO chunks_fts VALUES (?, ?)",
            [(str(c.citation_id), c.text) for c in knowledge.chunks],
        )

    def assemble(self, case):
        terms = re.findall(r"\w+", case.situation[:200], re.UNICODE)[:16]
        evidence = []
        if self.prompt_version in (ADVICE_PROMPT_VERSION, "context/v4", "context/v5"):
            evidence = [
                {"chunk": chunk, "source": self.sources[chunk.source_id]}
                for chunk in knowledge_order(self.chunks.values(), case, self.config.adviser)
            ]
        elif terms:
            match = " OR ".join('"' + t + '"' for t in terms)
            ids = self.index.execute(
                "SELECT citation_id FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY bm25(chunks_fts), citation_id LIMIT 10",
                (match,),
            ).fetchall()
            evidence = [
                {"chunk": self.chunks[cid], "source": self.sources[self.chunks[cid].source_id]}
                for (cid,) in ids
            ]
        if self.prompt_version in ("context/v4", "context/v5"):
            from quartermaster.prediction_context import assemble

            item = assemble(
                self.config.adviser,
                case,
                self.config.answer_format,
                evidence,
                prompt_version=self.prompt_version,
            )
            return (
                self.config.adviser,
                item.context,
                item.evidence,
                [],
                (0, len(evidence) - len(item.evidence)),
            )
        return assemble_context(
            self.config.adviser,
            self.config.lessons,
            case,
            evidence,
            prompt_version=self.prompt_version,
        )

    def close(self):
        self.index.close()


def extract_verified(archive, destination):
    """Extract into a new empty directory; no links, duplicate paths or executable files."""
    destination.mkdir(mode=0o700, exist_ok=False)
    try:
        with tarfile.open(archive, "r:") as tar:
            count, total, names = 0, 0, set()
            for entry in tar:
                count += 1
                total += entry.size
                if (
                    count > 110
                    or total > MAX_TOTAL + 128_000
                    or entry.name in names
                    or not safe_name(entry.name)
                    or not entry.isfile()
                    or entry.size < 0
                    or entry.size
                    > (3_000_000_000 if entry.name == "model/model.gguf" else 32_000_000)
                ):
                    raise ValueError("Unsupported archive entry")
                names.add(entry.name)
                path = destination / entry.name
                path.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(entry) as source, path.open("xb") as target:
                    import shutil

                    shutil.copyfileobj(source, target, 1024 * 1024)
                path.chmod(0o644)
        record = verify_package(destination)
        if names != set(record[0].files) | {MANIFEST}:
            raise ValueError("Unexpected archive contents")
        return record
    except (OSError, ValueError, tarfile.TarError):
        raise DomainError("EXPORT_ARCHIVE: Use a complete original export archive.", 409) from None
