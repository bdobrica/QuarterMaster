import hashlib
import json
import shutil
from uuid import UUID, uuid4

import pytest

from muster.knowledge import save_article
from muster.publication import get_publication, overview, publish
from muster.storage import connect as muster_connect
from quartermaster import muster
from quartermaster.contracts.muster import DecisionInput, UseKnowledge
from quartermaster.db import connect, migrate
from quartermaster.errors import DomainError
from quartermaster.holdouts import case_fingerprint
from quartermaster.knowledge import advice_search
from quartermaster.migrate_muster import migrate_data
from quartermaster.muster_bundle import load_bundle
from quartermaster.projects import get_adviser
from tests.muster.test_app import token
from tests.muster.test_publication import reviewed


@pytest.fixture
def collection(client, settings, project_fixture):
    project_id = UUID(client.post("/api/projects", json=project_fixture).json()["id"])
    root = settings.muster_storage
    cid = reviewed(root, 2)
    save_article(
        root, cid, None, 0, "My policy", "Prefer convenient transport. This is my preference."
    )
    with muster_connect(root) as db:
        db.execute("UPDATE reviews SET status='needs_review',reviewed_at=NULL WHERE job_id=2")
    pid = publish(root, cid, overview(root, cid)["fingerprint"])
    folder = root / get_publication(root, cid, pid)["path"]
    bundle = load_bundle(folder)
    return project_id, cid, bundle


def action(bundle, revision=0, target=None):
    # Leave price out: an observed listing price is not the taught valuation.
    fields = [key for key in bundle.examples[0]["values"] if key != "price"]
    return DecisionInput(
        expected_revision=revision,
        input_fields=fields,
        inputs_available_at_decision=True,
        target=target or {"kind": "number", "value": 72000.0, "unit": "EUR"},
        reasoning="My personal judgment, not a verified transaction.",
    )


def test_mounted_collect_import_forms_and_assets(client, settings):
    page = client.get("/collect/")
    assert page.status_code == 200
    assert 'action="/collect/imports/preview"' in page.text
    csrf = token(page)
    preview = client.post(
        "/collect/imports/preview",
        data={
            "csrf": csrf,
            "name": "My collection",
            "links": "https://example.com/one",
        },
    )
    assert preview.status_code == 200
    assert 'action="/collect/imports/' in preview.text
    import re

    confirm = re.search(r'action="([^"]+/confirm)"', preview.text)[1]
    response = client.post(confirm, data={"csrf": csrf}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/collect/collections/")
    assert client.get(response.headers["location"]).status_code == 200
    assert client.get("/collect/static/review.js").status_code == 200
    assert client.post("/collect/imports/preview", data={"name": "No token"}).status_code == 403
    assert not client.app.state.muster_app.state.collector.active


def test_collection_to_knowledge_teaching_snapshot_and_no_implicit_training(
    client, settings, collection
):
    project_id, _, bundle = collection
    teach = f"/projects/{project_id}/teach"
    assert bundle.digest in client.get(teach).text
    item = muster.import_collection(settings, project_id, bundle.digest)
    assert muster.import_collection(settings, project_id, bundle.digest) == item
    assert len(muster.imports(settings, project_id)) == 1
    assert (item.reviewed, item.unreviewed) == (1, 1)
    assert muster.decisions(settings, project_id) == []
    assert get_adviser(settings.database_path, project_id).knowledge_revision is None
    muster.use_knowledge(settings, project_id, item.id, UseKnowledge(expected_revision=None))
    spec = get_adviser(settings.database_path, project_id)
    case = muster.decision_case(item, bundle.examples[0], action(bundle).input_fields)
    excerpts = advice_search(settings, spec, case)
    assert "convenient transport" in excerpts[0]["chunk"].text
    decision = muster.save_decision(settings, project_id, item.id, "1", action(bundle))
    assert decision.target.value == 72000.0
    with pytest.raises(DomainError, match="UNREVIEWED"):
        muster.save_decision(settings, project_id, item.id, "2", action(bundle))
    digest, path = muster.freeze_teaching(settings, project_id, item.id)
    original = path.read_bytes()
    dataset = json.loads(original)
    assert hashlib.sha256(original).hexdigest() == digest
    assert len(dataset["examples"]) == 1
    assert "price" not in json.loads(dataset["examples"][0]["input"]["situation"])
    assert dataset["examples"][0]["owner_decision"]["target"]["unit"] == "EUR"
    assert dataset["knowledge"][0]["text"] == excerpts[0]["chunk"].text
    assert not any("Human checked" in json.dumps(e["input"]) for e in dataset["examples"])
    revised = muster.save_decision(
        settings,
        project_id,
        item.id,
        "1",
        action(
            bundle,
            1,
            {
                "kind": "category",
                "value": "Consider negotiating",
            },
        ),
    )
    assert revised.revision == 2 and revised.target.kind == "category"
    with pytest.raises(DomainError, match="CHANGED"):
        muster.save_decision(settings, project_id, item.id, "1", action(bundle))
    assert (
        muster.save_decision(
            settings,
            project_id,
            item.id,
            "1",
            action(
                bundle,
                2,
                {
                    "kind": "category",
                    "value": "Consider negotiating",
                },
            ),
        )
        == revised
    )
    assert path.read_bytes() == original
    assert muster.freeze_teaching(settings, project_id, item.id)[0] != digest
    with connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM owner_decisions").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM training_runs").fetchone()[0] == 0
    assert get_adviser(settings.database_path, project_id).model == spec.model
    response = client.get(f"{teach}/{item.id}/examples/0")
    assert response.status_code == 200 and "Consider negotiating" in response.text
    download = client.get(
        f"{teach}/{item.id}/files/" + bundle.examples[0]["source"]["path"] + "/page.html"
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert "sandbox" in download.headers["content-security-policy"]
    assert client.get(f"{teach}/{item.id}").status_code == 200
    assert (
        client.post(
            f"{teach}/{item.id}/dataset", headers={"origin": "http://testserver"}
        ).status_code
        == 200
    )
    # QuarterMaster's snapshot survives deletion of the original publication.
    shutil.rmtree(bundle.root)
    assert muster.imported_bundle(settings, item).digest == bundle.digest


def test_holdout_blocks_supervision_and_refreeze(client, settings, collection):
    project_id, _, bundle = collection
    item = muster.import_collection(settings, project_id, bundle.digest)
    case = muster.decision_case(item, bundle.examples[0], action(bundle).input_fields)
    muster.save_decision(settings, project_id, item.id, "1", action(bundle))
    with connect(settings.database_path) as db:
        db.execute(
            "INSERT INTO evaluation_holdouts VALUES (?, ?, ?, ?)",
            (
                str(project_id),
                str(case.case_id),
                case_fingerprint(case),
                str(uuid4()),
            ),
        )
    with pytest.raises(DomainError, match="HELD_OUT"):
        muster.freeze_teaching(settings, project_id, item.id)
    with pytest.raises(DomainError, match="HELD_OUT"):
        muster.save_decision(settings, project_id, item.id, "1", action(bundle, 1))


def test_project_scoping_and_api_validation(client, settings, collection, project_fixture):
    project_id, _, bundle = collection
    path = f"/api/projects/{project_id}/muster"
    assert client.post(path, json={"publication": "bad"}).status_code == 422
    assert client.post(path, json={"publication": bundle.digest, "extra": True}).status_code == 422
    assert (
        client.post(
            path, json={"publication": bundle.digest}, headers={"origin": "https://evil.test"}
        ).status_code
        == 403
    )
    item = muster.import_collection(settings, project_id, bundle.digest)
    second_id = UUID(client.post("/api/projects", json=project_fixture).json()["id"])
    assert client.get(f"/projects/{second_id}/teach/{item.id}").status_code == 404
    other = muster.import_collection(settings, second_id, bundle.digest)
    assert other.id != item.id
    endpoint = path + f"/{item.id}/examples/0/decision"
    data = action(bundle).model_dump(mode="json")
    for changed in (
        {"input_fields": []},
        {"inputs_available_at_decision": 1},
        {"inputs_available_at_decision": False},
        {"target": {"kind": "number", "value": "7", "unit": "EUR"}},
        {"reasoning": 5},
    ):
        assert client.post(endpoint, json=data | changed).status_code == 422
    assert client.post(endpoint, json=data).status_code == 200


@pytest.mark.parametrize(
    "damage", ["hash", "type", "version", "path", "symlink", "duplicate_json", "schema"]
)
def test_bundle_rejects_damaged_or_unsupported_data(collection, damage, tmp_path):
    _, _, bundle = collection
    root = tmp_path / "bad"
    shutil.copytree(bundle.root, root)
    manifest = json.loads((root / "manifest.json").read_text())
    if damage == "hash":
        (root / manifest["examples"]).write_text("{}\n")
    elif damage == "type":
        records = bundle.examples
        records[0]["values"]["price"] = True
        raw = "".join(json.dumps(r) + "\n" for r in records)
        (root / manifest["examples"]).write_text(raw)
        manifest["checksums"][manifest["examples"]] = hashlib.sha256(raw.encode()).hexdigest()
    elif damage == "version":
        manifest["format_version"] = 2
    elif damage == "path":
        manifest["checksums"]["../secret"] = "a" * 64
    elif damage == "symlink":
        (root / "extra").symlink_to(bundle.root / "manifest.json")
    elif damage == "schema":
        schema = bundle.schema | {"$ref": "https://evil.test/schema"}
        raw = json.dumps(schema).encode()
        (root / manifest["schema"]).write_bytes(raw)
        manifest["checksums"][manifest["schema"]] = hashlib.sha256(raw).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    if damage == "duplicate_json":
        raw = (root / "manifest.json").read_text()
        (root / "manifest.json").write_text('{"format_version":1,' + raw[1:])
    with pytest.raises(DomainError, match="MUSTER_BUNDLE"):
        load_bundle(root)


def test_old_review_default_and_knowledge_conflict(settings, collection):
    project_id, cid, bundle = collection
    first = muster.import_collection(settings, project_id, bundle.digest)
    knowledge = muster.use_knowledge(
        settings, project_id, first.id, UseKnowledge(expected_revision=None)
    )
    save_article(settings.muster_storage, cid, None, 0, "Other policy", "A different preference.")
    publish(settings.muster_storage, cid, overview(settings.muster_storage, cid)["fingerprint"])
    latest = muster.publications(settings)[-1]
    second = muster.import_collection(settings, project_id, latest["digest"])
    assert second.id != first.id
    with pytest.raises(DomainError, match="CONFLICT"):
        muster.use_knowledge(
            settings, project_id, second.id, UseKnowledge(expected_revision=knowledge.id)
        )
    assert muster.imported_bundle(settings, first).digest == bundle.digest


def test_migrate_muster_data_preserves_history_without_credentials(settings, collection, tmp_path):
    _, _, bundle = collection
    source = settings.muster_storage
    (source / "browser-profile" / "cookie-secret").write_text("private cookie")
    (source / ".env").write_text("MUSTER_AI_API_KEY=private-key")
    destination = tmp_path / "independent" / "muster"
    migrate_data(source, destination)
    assert (destination / "muster.sqlite3").is_file()
    assert not (destination / "browser-profile").exists()
    assert not (destination / ".env").exists()
    assert load_bundle(destination / bundle.root.relative_to(source)).digest == bundle.digest
    assert (source / "browser-profile" / "cookie-secret").read_text() == "private cookie"
    with pytest.raises(DomainError, match="MIGRATION"):
        migrate_data(source, destination)


def test_v9_migration_preserves_existing_document_bytes(settings, collection):
    project_id, _, _ = collection
    with connect(settings.database_path) as db:
        before = db.execute("SELECT document FROM adviser_revisions ORDER BY rowid").fetchall()
        db.execute("DROP TABLE owner_decisions")
        db.execute("DROP TABLE muster_imports")
        db.execute("PRAGMA user_version = 9")
    migrate(settings.database_path)
    with connect(settings.database_path) as db:
        assert [tuple(r) for r in before] == [
            tuple(r) for r in db.execute("SELECT document FROM adviser_revisions ORDER BY rowid")
        ]
    assert get_adviser(settings.database_path, project_id).name


def test_import_rollback_and_tampered_snapshot_errors(client, settings, collection, monkeypatch):
    project_id, _, bundle = collection
    original_upload = muster.upload_source

    def fail(*args, **kwargs):
        original_upload(*args, **kwargs)
        raise DomainError("TEST_STORAGE: Simulated import failure.")

    with monkeypatch.context() as patch:
        patch.setattr(muster, "upload_source", fail)
        with pytest.raises(DomainError, match="TEST_STORAGE"):
            muster.import_collection(settings, project_id, bundle.digest)
    with connect(settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM muster_imports").fetchone()[0] == 0
    item = muster.import_collection(settings, project_id, bundle.digest)
    snapshot = muster.snapshot_path(settings, bundle.digest)
    page = bundle.examples[0]["source"]["path"] + "/page.html"
    (snapshot / page).write_text("changed source")
    endpoint = f"/projects/{project_id}/teach/{item.id}"
    assert client.get(endpoint + "/files/" + page).status_code == 503
    # Media is verified on access; unchanged metadata remains usable without
    # rereading every image for a page of example text.
    assert client.get(endpoint).status_code == 200
    (snapshot / "examples.jsonl").write_text("{}\n")
    assert client.get(endpoint).status_code == 503
