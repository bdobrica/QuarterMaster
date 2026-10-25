"""Published collections become portable knowledge and explicit personal teaching targets."""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError

from quartermaster.contracts.advice import Case
from quartermaster.contracts.muster import MusterImport, OwnerDecision
from quartermaster.contracts.sources import KnowledgeSelection, ParseOptions
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.holdouts import require_eligible
from quartermaster.knowledge import current_knowledge, revise_knowledge
from quartermaster.muster_bundle import Bundle, controlled, load_bundle, read_json, sha_file
from quartermaster.projects import read_spec, require_target
from quartermaster.sources import read_source, source_bytes, upload_source


def publications(settings):
    """Only inspect public manifests; never open Muster's mutable database."""
    root = settings.muster_storage.absolute() / "publications"
    result = []
    for path in sorted(root.glob("*/v*/manifest.json"))[:1000]:
        try:
            controlled(path)
            if path.stat().st_size > 8 * 1024**2:
                continue
            manifest = read_json(path.read_text(encoding="utf-8"))
            result.append(
                {
                    "digest": sha_file(path),
                    "name": manifest["collection"]["name"],
                    "version": manifest["version"],
                    "counts": manifest["counts"],
                    "path": path.parent,
                }
            )
        except (DomainError, OSError, ValueError, KeyError, TypeError):
            continue
    return result


def publication(settings, digest):
    match = next((p for p in publications(settings) if p["digest"] == digest), None)
    if match is None:
        raise DomainError("MUSTER_MISSING: Publish a collection in Collect, then reload.", 404)
    bundle = load_bundle(match["path"])
    if bundle.digest != digest:
        raise DomainError("MUSTER_CHANGED: The publication changed; check it again.", 409)
    return bundle


def imports(settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM muster_imports WHERE project_id=? ORDER BY rowid DESC",
            (str(project_id),),
        ).fetchall()
    return [MusterImport.model_validate_json(row[0]) for row in rows]


def get_import(settings, project_id, import_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        row = connection.execute(
            "SELECT document FROM muster_imports WHERE project_id=? AND id=?",
            (str(project_id), str(import_id)),
        ).fetchone()
    if row is None:
        raise DomainError("MUSTER_IMPORT_MISSING: Choose a collection from this adviser.", 404)
    return MusterImport.model_validate_json(row[0])


def snapshot_path(settings, digest):
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise DomainError("MUSTER_HASH: Choose a saved collection.")
    return controlled(settings.artifact_root.absolute() / "muster" / digest)


def imported_bundle(settings, item):
    # Registration proves the entire publication passed validation. Recheck the
    # digest-bound metadata on use; hash media/provenance when downloaded instead
    # of rereading every image to render each example's text.
    root = snapshot_path(settings, item.manifest_sha256)
    try:
        digest = sha_file(root / "manifest.json")
        if digest != item.manifest_sha256:
            raise ValueError
        reader = Bundle(root, digest, {}, {}, [])
        manifest = read_json(reader.text("manifest.json"))
        reader = Bundle(root, digest, manifest, {}, [])
        schema = read_json(reader.text(manifest["schema"]))
        examples = [
            read_json(line)
            for line in reader.text(manifest["examples"]).splitlines()
            if line.strip()
        ]
        return Bundle(root, digest, manifest, schema, examples)
    except (DomainError, OSError, ValueError, KeyError, TypeError):
        raise DomainError(
            "MUSTER_INTEGRITY: Restore the imported collection from backup.", 503
        ) from None


def import_collection(settings, project_id, digest):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
    bundle = publication(settings, digest)
    iid = uuid5(NAMESPACE_URL, f"quartermaster:muster:{project_id}:{digest}")
    destination = snapshot_path(settings, digest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        # Stage and revalidate the complete copy before registering anything. Source
        # edits during the copy cannot install a partially verified publication.
        with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
            copy = Path(staging) / "bundle"
            shutil.copytree(bundle.root, copy, symlinks=True)
            if load_bundle(copy).digest != digest:
                raise DomainError("MUSTER_CHANGED: Publish again; source bytes changed.", 409)
            try:
                copy.rename(destination)
            except FileExistsError:
                pass  # Another concurrent import installed the identical digest.
    bundle = load_bundle(destination)
    if bundle.digest != digest:
        raise DomainError("MUSTER_INTEGRITY: Restore the imported collection from backup.", 503)
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        read_spec(connection, project_id)
        existing = connection.execute(
            "SELECT document FROM muster_imports WHERE id=?", (str(iid),)
        ).fetchone()
        if existing:
            return MusterImport.model_validate_json(existing[0])
        sources = {}
        for article in bundle.manifest["knowledge"]:
            # Keep exact publication bytes, including line endings. Use safe local
            # filenames; article titles and all provenance remain in the manifest.
            source = upload_source(
                settings,
                project_id,
                f"{article['title'][:150]}.md",
                (bundle.root / article["path"]).read_bytes(),
                "knowledge",
                ParseOptions(),
                connection=connection,
            )
            sources[article["id"]] = source.id
        unreviewed = sum(
            r.get("review_status", "reviewed") == "unreviewed" for r in bundle.examples
        )
        item = MusterImport(
            id=iid,
            project_id=project_id,
            created_at=datetime.now(UTC),
            manifest_sha256=digest,
            collection_name=bundle.manifest["collection"]["name"],
            collection_id=bundle.manifest["collection"]["id"],
            publication_version=bundle.manifest["version"],
            schema_id=bundle.manifest["schema_id"],
            reviewed=len(bundle.examples) - unreviewed,
            unreviewed=unreviewed,
            knowledge_sources=sources,
        )
        connection.execute(
            "INSERT INTO muster_imports VALUES (?, ?, ?)",
            (str(iid), str(project_id), item.model_dump_json()),
        )
    return item


def use_knowledge(settings, project_id, import_id, action):
    item = get_import(settings, project_id, import_id)
    bundle = imported_bundle(settings, item)
    previous = current_knowledge(settings, project_id)
    active = previous.source_ids if previous else []
    with connect(settings.database_path) as connection:
        selected = [read_source(connection, project_id, sid) for sid in active]
    # Never silently combine conflicting revisions of the same text article.
    for other in imports(settings, project_id):
        if other.id == item.id:
            continue
        if set(active) & set(other.knowledge_sources.values()):
            other_bundle = imported_bundle(settings, other)
            titles = {a["title"].casefold() for a in other_bundle.manifest["knowledge"]}
            if titles & {a["title"].casefold() for a in bundle.manifest["knowledge"]}:
                raise DomainError(
                    "MUSTER_KNOWLEDGE_CONFLICT: Another collection has active articles with "
                    "the same titles. Review the knowledge selection in Sources and setup "
                    "to choose which versions to use.",
                    409,
                )
    ids = list(dict.fromkeys([*active, *item.knowledge_sources.values()]))
    if set(ids) == {s.id for s in selected} and action.expected_revision == (
        previous.id if previous else None
    ):
        return previous
    return revise_knowledge(
        settings,
        project_id,
        KnowledgeSelection(
            source_ids=ids,
            expected_revision=action.expected_revision,
        ),
    )


def decision_id(item, example_id):
    return uuid5(item.id, example_id)


def decisions(settings, project_id, import_id=None):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT document FROM owner_decisions d WHERE project_id=? AND revision="
            "(SELECT MAX(revision) FROM owner_decisions WHERE id=d.id) ORDER BY rowid",
            (str(project_id),),
        ).fetchall()
    result = [OwnerDecision.model_validate_json(row[0]) for row in rows]
    return [d for d in result if import_id is None or d.import_id == import_id]


def example(bundle, example_id):
    record = next((r for r in bundle.examples if r["id"] == example_id), None)
    if record is None:
        raise DomainError("MUSTER_EXAMPLE_MISSING: Choose an example from this collection.", 404)
    return record


def verify_record_evidence(bundle, record):
    names = {record["source"]["path"] + "/page.html", record["provenance"]}
    for refs in record["evidence"].values():
        for ref in refs:
            if ref["source"] == "image":
                names.add(record["source"]["path"] + "/" + ref["file"])
    for name in names:
        verify_file(bundle, name)


def verify_file(bundle, name):
    try:
        if sha_file(bundle.root / name) != bundle.manifest["checksums"][name]:
            raise ValueError
    except (OSError, ValueError, KeyError, DomainError):
        raise DomainError(
            "MUSTER_INTEGRITY: Restore this evidence file from backup.", 503
        ) from None


def decision_case(item, record, fields):
    try:
        return Case(
            case_id=decision_id(item, record["id"]),
            situation=json.dumps(
                {key: record["values"][key] for key in fields},
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
        )
    except ValidationError:
        raise DomainError(
            "MUSTER_INPUT_SIZE: Choose fewer details (4,000 characters maximum)."
        ) from None


def save_decision(settings, project_id, import_id, example_id, action):
    item = get_import(settings, project_id, import_id)
    bundle = imported_bundle(settings, item)
    record = example(bundle, example_id)
    verify_record_evidence(bundle, record)
    if record.get("review_status", "reviewed") != "reviewed":
        raise DomainError(
            "MUSTER_UNREVIEWED: Check this example in Collect and publish a new version "
            "before using it for teaching.",
            409,
        )
    if len(set(action.input_fields)) != len(action.input_fields) or not set(
        action.input_fields
    ) <= set(record["values"]):
        raise DomainError("MUSTER_FIELDS: Choose each available decision-time field once.")
    case = decision_case(item, record, action.input_fields)
    did = decision_id(item, example_id)
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        require_target(read_spec(connection, project_id), action.target)
        row = connection.execute(
            "SELECT document FROM owner_decisions WHERE project_id=? AND id=? "
            "ORDER BY revision DESC LIMIT 1",
            (str(project_id), str(did)),
        ).fetchone()
        previous = OwnerDecision.model_validate_json(row[0]) if row else None
        current = previous.revision if previous else 0
        if current != action.expected_revision:
            raise DomainError("MUSTER_DECISION_CHANGED: Reload before saving your judgment.", 409)
        require_eligible(connection, project_id, [case])
        decision = OwnerDecision(
            id=did,
            project_id=project_id,
            import_id=item.id,
            revision=current + 1,
            created_at=datetime.now(UTC),
            manifest_sha256=bundle.digest,
            example_id=example_id,
            input_fields=action.input_fields,
            target=action.target,
            reasoning=action.reasoning,
        )
        if previous and all(
            getattr(previous, key) == getattr(decision, key)
            for key in ("input_fields", "target", "reasoning")
        ):
            return previous
        connection.execute(
            "INSERT INTO owner_decisions VALUES (?, ?, ?, ?)",
            (str(did), str(project_id), decision.revision, decision.model_dump_json()),
        )
    return decision


def freeze_teaching(settings, project_id, import_id):
    """Portable reviewed data; not a runnable historical LoRA job or a model change."""
    if import_id is not None:
        get_import(settings, project_id, import_id)
    records = decisions(settings, project_id, import_id)
    from quartermaster.prediction_reviews import teaching

    reviewed = teaching(settings, project_id)
    if not records and not reviewed:
        raise DomainError("MUSTER_NO_TARGETS: Teach at least one reviewed example first.")
    bundles, items = {}, {}
    for decision in records:
        if decision.import_id not in bundles:
            items[decision.import_id] = get_import(settings, project_id, decision.import_id)
            bundles[decision.import_id] = imported_bundle(settings, items[decision.import_id])
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        spec = read_spec(connection, project_id)
        # Freeze one consistent latest-decision snapshot, including concurrent saves.
        latest = decisions(settings, project_id, import_id)
        if latest != records or teaching(settings, project_id) != reviewed:
            raise DomainError("MUSTER_DECISION_CHANGED: Teaching changed; prepare again.", 409)
        examples = []
        for decision in records:
            bundle, item = bundles[decision.import_id], items[decision.import_id]
            record = example(bundle, decision.example_id)
            verify_record_evidence(bundle, record)
            case = decision_case(item, record, decision.input_fields)
            require_eligible(connection, project_id, [case])
            examples.append(
                {
                    "input": case.decision_input(),
                    "owner_decision": decision.model_dump(mode="json"),
                    "source": {
                        "manifest_sha256": bundle.digest,
                        "example_id": record["id"],
                        "capture": record["source"],
                        "provenance": record["provenance"],
                    },
                }
            )
        examples.extend(
            r.model_dump(mode="json", exclude={"input": {"observed_outcome"}}) for r in reviewed
        )
        knowledge = []
        if spec.knowledge_revision:
            from quartermaster.knowledge import read_revision

            revision = read_revision(connection, project_id, spec.knowledge_revision)
            for sid in revision.source_ids:
                source = read_source(connection, project_id, sid)
                knowledge.append(
                    {
                        "source": source.model_dump(mode="json"),
                        "text": source_bytes(settings, source).decode("utf-8-sig"),
                    }
                )
        payload = {
            "schema_version": "quartermaster.teaching-dataset/v2"
            if reviewed
            else "quartermaster.teaching-dataset/v1",
            "project_id": str(project_id),
            "knowledge_revision": str(spec.knowledge_revision) if spec.knowledge_revision else None,
            "examples": examples,
            "knowledge": knowledge,
            "imports": [items[key].model_dump(mode="json") for key in sorted(items, key=str)],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = controlled(settings.artifact_root.absolute() / "teaching" / f"{digest}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if path.read_bytes() != raw:
                raise DomainError(
                    "MUSTER_DATASET_INTEGRITY: Restore the frozen dataset.", 503
                ) from None
    return digest, path


def bind_collection(settings, collection_id, project_id):
    if not project_id:
        return
    from uuid import UUID

    try:
        project_id = UUID(project_id)
    except ValueError:
        return
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        connection.execute(
            "INSERT OR IGNORE INTO collection_projects VALUES (?, ?, NULL, NULL)",
            (collection_id, str(project_id)),
        )


def collection_owner(settings, collection_id):
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT project_id FROM collection_projects WHERE collection_id=?", (collection_id,)
        ).fetchone()
    return row[0] if row else None


def teach_collection(settings, collection_id):
    # The bundled collector owns its mutable data and public publication API.
    # QuarterMaster consumes the verified immutable bundle, never extraction tables.
    from muster.publication import get_publication, overview, publish
    from quartermaster.contracts.muster import UseKnowledge

    project_id = collection_owner(settings, collection_id)
    if project_id is None:
        raise DomainError(
            "COLLECTION_ADVISER: Open Collect from an adviser before adding material."
        )
    state = overview(settings.muster_storage, collection_id)
    if (
        state["problems"]
        or any(j["decision"] in {"unavailable", "unreviewed"} for j in state["jobs"])
        or state["pending"]
    ):
        raise DomainError(
            "COLLECTION_UNFINISHED: Check every example and finish knowledge reviews. "
            "You can exclude unfinished pages in Advanced before teaching.",
            409,
        )
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT * FROM collection_projects WHERE collection_id=?", (collection_id,)
        ).fetchone()
        # overview's public fingerprint changes on publication; store the post-publication
        # fingerprint. A repeated handoff imports the same immutable version.
        publication_id = row["publication"] if row["fingerprint"] == state["fingerprint"] else None
    if publication_id is None:
        publication_id = publish(settings.muster_storage, collection_id, state["fingerprint"])
        fingerprint = overview(settings.muster_storage, collection_id)["fingerprint"]
        with connect(settings.database_path) as connection:
            connection.execute(
                "UPDATE collection_projects SET fingerprint=?, publication=? WHERE collection_id=?",
                (fingerprint, publication_id, collection_id),
            )
    published = get_publication(settings.muster_storage, collection_id, publication_id)
    item = import_collection(settings, project_id, published["manifest_sha256"])
    previous = current_knowledge(settings, project_id)
    try:
        use_knowledge(
            settings,
            project_id,
            item.id,
            UseKnowledge(expected_revision=previous.id if previous else None),
        )
    except DomainError as exc:
        if not exc.message.startswith("MUSTER_KNOWLEDGE_CONFLICT:"):
            raise
        return f"/projects/{project_id}/teach/{item.id}?knowledge_conflict=yes"
    return f"/projects/{project_id}/teach/{item.id}"
