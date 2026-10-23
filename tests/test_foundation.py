import asyncio
import hashlib
import html
import json
import re
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from quartermaster.api.limits import MAX_REQUEST, BodyLimitMiddleware
from quartermaster.app import create_app
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.sources import CaseMapping
from quartermaster.db import connect
from quartermaster.ingestion import MAX_UPLOAD
from quartermaster.sources import blob_path
from tests.test_ingestion import workbook_bytes

ORIGIN = {"Origin": "http://testserver"}
CSV = b"tool,status,paid_after,ideal_advice\ndrill,current,12,check first\nsaw,overdue,,withhold\n"
MD = (
    b"# Safety\nCurrent inspection is required before using rental tools.\n"
    b"\n# Damage\nAsk about reported damage.\n<script>never execute</script>\n"
)


@pytest.fixture
def project(client, project_fixture):
    return client.post("/api/projects", json=project_fixture).json()["id"]


def upload(client, project, data=CSV, name="observations.csv", label="observations", **options):
    return client.post(
        f"/api/projects/{project}/sources",
        files={"file": (name, data, "application/octet-stream")},
        data={"label": label, "encoding": "utf-8-sig", "delimiter": ",", **options},
        headers=ORIGIN,
    )


def ref(source, field, sheet="CSV"):
    return {"source_id": source["id"], "sheet": sheet, "field": field}


def mapping_for(source):
    return {
        "primary": {"source_id": source["id"], "sheet": "CSV"},
        "grain": "one rental request",
        "decision_time": "before handover",
        "inputs": [ref(source, "tool"), ref(source, "status")],
        "outcomes": [ref(source, "paid_after")],
        "targets": [ref(source, "ideal_advice")],
        "confirmed": True,
        "inputs_available_at_decision": True,
    }


def select_knowledge(client, project, source_ids, expected=None):
    return client.post(
        f"/api/projects/{project}/knowledge",
        json={"source_ids": source_ids, "expected_revision": expected},
    )


def test_adviser_revisions_rename_goal_and_stale_edit(client, project):
    path = f"/api/projects/{project}"
    original = client.get(path).json()
    assert original["schema_version"] == "quartermaster.adviser/v1"
    assert original["revision"] == 1
    assert original["model"]["base_revision"] == "2fc06364715b967f1860aea9cf38778875588b17"
    assert client.get(f"/projects/{project}").status_code == 200
    edit = {
        "name": "Updated",
        "mission": "Ask before deciding",
        "business_goal": "Reduce wasted rentals",
        "expected_revision": 1,
    }
    changed = client.patch(path, json=edit)
    assert changed.status_code == 200
    assert changed.json()["revision"] == 2
    assert changed.json()["business_goal"] == edit["business_goal"]
    assert changed.json()["created_at"].endswith("Z")
    assert client.get(path + "/revisions").json()[0] == original
    assert client.patch(path, json=edit).status_code == 409
    assert client.get("/api/projects").json()[0]["name"] == "Updated"
    assert client.get("/").text.count(f"/projects/{project}") == 1
    page = client.get(f"/projects/{project}").text
    assert "Reduce wasted rentals" in page and "Mission history" in page
    assert len(client.get(path + "/revisions").json()) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"mission": ""},
        {"name": 4},
        {"business_goal": 4},
        {"business_goal": " "},
        {"expected_revision": "1"},
        {"unexpected": "private-secret"},
        {"schema_version": "future/v2"},
    ],
)
def test_invalid_edits_are_safe_and_leave_history(client, project, change):
    data = {"name": "Demo", "mission": "Help", "expected_revision": 1, **change}
    response = client.patch(f"/api/projects/{project}", json=data)
    assert response.status_code == 422
    assert "private-secret" not in response.text
    assert len(client.get(f"/api/projects/{project}/revisions").json()) == 1


def test_adviser_contract_rejects_unknown_model_and_naive_timestamp(client, project):
    spec = client.get(f"/api/projects/{project}").json()
    for change in (
        {"schema_version": "future/v1"},
        {"revision": 0},
        {"inputs": "arbitrary"},
        {"created_at": "2026-01-01T12:00:00"},
        {"model": {"base_revision": "main"}},
        {"unknown": "field"},
    ):
        with pytest.raises(ValidationError):
            AdviserSpec.model_validate_json(json.dumps({**spec, **change}))


def test_upload_multiple_types_previews_original_bytes_and_restart(client, settings, project):
    csv = upload(client, project).json()
    xlsx_data = workbook_bytes()
    xlsx_response = upload(client, project, xlsx_data, "book.xlsx", "examples")
    assert xlsx_response.status_code == 201
    xlsx = xlsx_response.json()
    md_response = upload(client, project, MD, "policy.md", "knowledge")
    assert md_response.status_code == 201
    md = md_response.json()
    assert csv["sheets"][0]["row_count"] == 2
    assert csv["sheets"][0]["fields"][2]["missing"] == 1
    assert [s["name"] for s in xlsx["sheets"]] == ["Requests", "Empty", "Details"]
    for source, original in [(csv, CSV), (xlsx, xlsx_data), (md, MD)]:
        assert blob_path(settings.artifact_root, source["sha256"]).read_bytes() == original
        assert source["sha256"] == hashlib.sha256(original).hexdigest()
        page = client.get(f"/projects/{project}/sources/{source['id']}")
        assert page.status_code == 200
        downloaded = client.get(f"/projects/{project}/sources/{source['id']}/original")
        assert downloaded.content == original
        assert downloaded.headers["x-content-type-options"] == "nosniff"
        assert downloaded.headers["content-type"] == "application/octet-stream"
        assert "attachment" in downloaded.headers["content-disposition"]
    md_page = client.get(f"/projects/{project}/sources/{md['id']}").text
    assert "<script>never execute</script>" not in md_page
    assert "&lt;script&gt;never execute&lt;/script&gt;" in md_page
    with TestClient(create_app(settings)) as restarted:
        assert len(restarted.get(f"/api/projects/{project}/sources").json()) == 3
        assert restarted.get(f"/projects/{project}").status_code == 200


def test_content_addressed_dedup_and_hostile_name(client, settings, project):
    one = upload(client, project, MD, "../../<script>.md", "knowledge").json()
    two = upload(client, project, MD, "other.md", "knowledge").json()
    assert one["id"] != two["id"]
    assert one["sha256"] == two["sha256"]
    assert len(list((settings.artifact_root / "sources").rglob(one["sha256"]))) == 1
    assert one["display_name"] == "<script>.md"
    assert "&lt;script&gt;.md" in client.get(f"/projects/{project}").text
    assert not (settings.data_dir.parent / "<script>.md").exists()


@pytest.mark.parametrize(
    "name,data",
    [
        ("file.py", b"print(1)"),
        ("bad.csv", b"\x00secret"),
        ("bad.xlsx", b"private-cell"),
        ("empty.md", b""),
    ],
)
def test_invalid_uploads_leave_no_metadata_or_artifacts(client, settings, project, name, data):
    response = upload(client, project, data, name)
    assert response.status_code == 422
    assert "private-cell" not in response.text
    assert client.get(f"/api/projects/{project}/sources").json() == []
    assert not (settings.artifact_root / "sources").exists()


@pytest.mark.parametrize(
    "headers", [{}, {"Origin": "https://evil.test"}, {**ORIGIN, "Sec-Fetch-Site": "cross-site"}]
)
def test_uploads_require_same_origin_before_parsing(client, project, headers):
    response = client.post(
        f"/api/projects/{project}/sources",
        files={"file": ("a.csv", CSV)},
        data={"label": "observations", "encoding": "utf-8-sig", "delimiter": ","},
        headers=headers,
    )
    assert response.status_code == 403
    assert client.get(f"/api/projects/{project}/sources").json() == []


def test_upload_limits_files_and_actual_bytes(client, project):
    oversized = b"x" * (MAX_UPLOAD + 1)
    assert upload(client, project, oversized).status_code == 413
    response = client.post(
        f"/api/projects/{project}/sources",
        files=[("file", ("a.csv", CSV)), ("file", ("b.csv", CSV))],
        data={"label": "observations", "encoding": "utf-8-sig", "delimiter": ","},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert client.get(f"/api/projects/{project}/sources").json() == []


def test_request_limit_counts_stream_without_trusting_content_length():
    async def exercise(headers):
        called = False

        async def app(scope, receive, send):
            nonlocal called
            called = True

        messages = iter(
            [
                {"type": "http.request", "body": b"x" * MAX_REQUEST, "more_body": True},
                {"type": "http.request", "body": b"x", "more_body": False},
            ]
        )
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await BodyLimitMiddleware(app)(
            {"type": "http", "method": "POST", "headers": headers}, receive, send
        )
        assert not called
        assert sent[0]["status"] == 413

    asyncio.run(exercise([]))
    asyncio.run(exercise([(b"content-length", b"1")]))


def test_reviewed_mapping_is_deterministic_provenance_linked_and_keeps_outcomes_out(
    client, project
):
    source = upload(client, project).json()
    mapping = mapping_for(source)
    base = f"/api/projects/{project}/mappings"
    preview = client.post(base + "/preview", json=mapping)
    assert preview.status_code == 200
    assert preview.json()["case_count"] == 2
    assert client.get(base).json() == []
    first = client.post(base, json=mapping)
    assert first.status_code == 201
    assert first.json() == client.post(base, json=mapping).json()
    mid = first.json()["mapping_id"]
    rows = client.get(base + f"/{mid}/cases").json()
    assert len(rows) == 2
    assert rows == preview.json()["samples"]
    row = rows[0]
    situation = json.loads(row["case"]["situation"])
    assert len(situation["fields"]) == 2
    assert "paid_after" not in row["case"]["situation"]
    assert "ideal_advice" not in row["case"]["situation"]
    assert "paid_after" in row["case"]["observed_outcome"]
    assert list(row["target_candidate"].values()) == ["check first"]
    assert row["source_rows"] == [
        {
            "source_id": source["id"],
            "source_sha256": source["sha256"],
            "sheet": "CSV",
            "row": 2,
            "line_start": 2,
            "line_end": 2,
        }
    ]
    assert row["mapping_id"] == mid
    assert UUID(row["case"]["case_id"])
    # Use the actual public decision serializer, not an imitation of it.
    from quartermaster.contracts.advice import Case

    case = Case.model_validate_json(json.dumps(row["case"]))
    assert "observed_outcome" not in case.decision_input()
    assert len(client.get(base).json()) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"confirmed": False},
        {"inputs_available_at_decision": False},
        {"inputs": []},
        {"grain": ""},
        {"decision_time": ""},
        {"unexpected": 1},
        {"schema_version": "future/v2"},
    ],
)
def test_unreviewed_invalid_mapping_cannot_apply(client, project, change):
    source = upload(client, project).json()
    base = f"/api/projects/{project}/mappings"
    assert client.post(base, json={**mapping_for(source), **change}).status_code == 422
    assert client.get(base).json() == []


def test_mapping_rejects_overlapping_roles_and_warns_on_suspicious_input(client, project):
    source = upload(client, project).json()
    mapping = mapping_for(source)
    mapping["inputs"].append(ref(source, "paid_after"))
    with pytest.raises(ValidationError):
        CaseMapping.model_validate_json(json.dumps(mapping))
    mapping["outcomes"] = []
    preview = client.post(f"/api/projects/{project}/mappings/preview", json=mapping)
    assert preview.status_code == 200
    assert any(
        "paid_after" in warning and "later outcome" in warning
        for warning in preview.json()["warnings"]
    )


def test_explicit_exact_join_and_reject_unmatched_ambiguous_or_missing_keys(client, project):
    source = upload(client, project).json()
    other = upload(client, project, b"tool,category\ndrill,power\nsaw,cutting\n").json()
    mapping = mapping_for(source)
    mapping["inputs"].append(ref(other, "category"))
    base = f"/api/projects/{project}/mappings"
    response = client.post(base, json=mapping)
    assert response.status_code == 422 and "JOIN_REQUIRED" in response.text
    mapping["joins"] = [
        {
            "table": {"source_id": other["id"], "sheet": "CSV"},
            "left": ref(source, "tool"),
            "right_key": "tool",
        }
    ]
    response = client.post(base, json=mapping)
    assert response.status_code == 201
    cases = client.get(base + "/" + response.json()["mapping_id"] + "/cases").json()
    assert len(cases[0]["source_rows"]) == 2
    assert "power" in cases[0]["case"]["situation"]
    for data, code in [
        (b"tool,category\ndrill,a\ndrill,b\n", "JOIN_AMBIGUOUS"),
        (b"tool,category\ndrill,a\n", "JOIN_UNMATCHED"),
    ]:
        bad = upload(client, project, data).json()
        mapping["inputs"][-1] = ref(bad, "category")
        mapping["joins"][0]["table"]["source_id"] = bad["id"]
        response = client.post(base, json=mapping)
        assert response.status_code == 422 and code in response.text


def test_mapping_formula_fields_rejected(client, project):
    source = upload(client, project, workbook_bytes(), "book.xlsx").json()
    mapping = {
        "primary": {"source_id": source["id"], "sheet": "Requests"},
        "grain": "one request",
        "decision_time": "before use",
        "inputs": [ref(source, "tool", "Requests"), ref(source, "note", "Requests")],
        "confirmed": True,
        "inputs_available_at_decision": True,
    }
    response = client.post(f"/api/projects/{project}/mappings", json=mapping)
    assert response.status_code == 422
    assert "MAPPING_FORMULA" in response.text


def test_mapping_preserves_exact_header_whitespace(client, project):
    source = upload(client, project, b" tool , status \ndrill,current\n").json()
    mapping = {
        "primary": {"source_id": source["id"], "sheet": "CSV"},
        "grain": "one row",
        "decision_time": "before use",
        "inputs": [ref(source, " tool ")],
        "confirmed": True,
        "inputs_available_at_decision": True,
    }
    assert client.post(f"/api/projects/{project}/mappings", json=mapping).status_code == 201


def test_knowledge_revision_citation_replacement_and_removal(client, project):
    source = upload(client, project, MD, "policy.md", "knowledge").json()
    one = select_knowledge(client, project, [source["id"]])
    assert one.status_code == 201
    revision = one.json()["id"]
    assert client.get(f"/api/projects/{project}").json()["knowledge_revision"] == revision
    search_path = f"/api/projects/{project}/knowledge/search"
    results = client.get(search_path, params={"q": "inspection"}).json()
    assert len(results) == 1
    chunk = results[0]["chunk"]
    assert chunk["source_id"] == source["id"]
    assert MD.decode()[chunk["start"] : chunk["end"]] == chunk["text"]
    citation = f"/api/projects/{project}/citations/{chunk['citation_id']}"
    assert client.get(citation).json()["chunk"] == chunk
    rendered = client.get(
        f"/projects/{project}/citations/{chunk['citation_id']}", params={"revision": revision}
    )
    assert rendered.status_code == 200
    assert "Lines" in rendered.text
    # Same-name replacement does not mutate the first source or its old revision.
    replacement = upload(
        client,
        project,
        b"# Updated\nOnly calibrated devices are permitted.\n",
        "policy.md",
        "knowledge",
    ).json()
    two = select_knowledge(client, project, [replacement["id"]], revision).json()
    assert client.get(search_path, params={"q": "inspection"}).json() == []
    assert client.get(citation).status_code == 404
    assert client.get(citation, params={"revision": revision}).status_code == 200
    assert (
        len(client.get(search_path, params={"q": "inspection", "revision": revision}).json()) == 1
    )
    active = client.get(search_path, params={"q": "calibrated"}).json()[0]
    empty = select_knowledge(client, project, [], two["id"])
    assert empty.status_code == 201
    assert client.get(search_path, params={"q": "calibrated"}).json() == []
    assert (
        client.get(
            f"/api/projects/{project}/citations/{active['chunk']['citation_id']}"
        ).status_code
        == 404
    )
    assert len(client.get(f"/api/projects/{project}/knowledge/revisions").json()) == 3
    assert client.get(f"/projects/{project}").status_code == 200


def test_reindex_stable_citations_and_stale_revision(client, settings, project):
    source = upload(client, project, MD, "policy.md", "knowledge").json()
    one = select_knowledge(client, project, [source["id"]]).json()
    path = f"/api/projects/{project}/knowledge/search"
    old = client.get(path, params={"q": "damage"}).json()[0]["chunk"]
    # Demonstrate rebuilding the derived index, not merely retaining existing entries.
    with connect(settings.database_path) as connection:
        connection.execute("DELETE FROM chunks_fts")
        connection.execute("DELETE FROM chunks")
    two = select_knowledge(client, project, [source["id"]], one["id"])
    assert two.status_code == 201
    assert two.json()["id"] != one["id"]
    assert client.get(path, params={"q": "damage"}).json()[0]["chunk"] == old
    assert client.get(path, params={"q": "damage", "revision": one["id"]}).json()[0]["chunk"] == old
    assert select_knowledge(client, project, [], one["id"]).status_code == 409


@pytest.mark.parametrize(
    "query",
    [
        '" OR NEAR() *',
        'damage"; DROP TABLE projects; --',
        "<script>damage</script>",
        "NEAR(damage, 2)",
        "NOT OR AND",
    ],
)
def test_search_treats_query_as_literal_terms_and_escapes_source(client, project, query):
    source = upload(client, project, MD, "policy.md", "knowledge").json()
    select_knowledge(client, project, [source["id"]])
    response = client.get(f"/projects/{project}/knowledge/search", params={"q": query})
    assert response.status_code == 200
    assert "<script>damage</script>" not in response.text
    assert "<script>never execute</script>" not in response.text
    assert client.get("/api/projects").status_code == 200


def test_source_corruption_fails_download_retrieval_and_mapping(client, settings, project):
    source = upload(client, project, MD, "policy.md", "knowledge").json()
    select_knowledge(client, project, [source["id"]])
    path = blob_path(settings.artifact_root, source["sha256"])
    path.chmod(0o600)
    path.write_bytes(b"X" * len(MD))
    response = client.get(f"/api/projects/{project}/knowledge/search", params={"q": "inspection"})
    assert response.status_code == 503 and "SOURCE_HASH" in response.text
    assert client.get(f"/projects/{project}/sources/{source['id']}/original").status_code == 503
    assert (
        client.post(
            f"/api/projects/{project}/sources",
            files={"file": ("policy.md", MD)},
            data={"label": "knowledge", "encoding": "utf-8-sig", "delimiter": ","},
            headers=ORIGIN,
        ).status_code
        == 503
    )
    table = upload(client, project).json()
    blob_path(settings.artifact_root, table["sha256"]).unlink()
    assert (
        client.post(f"/api/projects/{project}/mappings", json=mapping_for(table)).status_code == 503
    )


def test_cross_project_sources_mappings_revisions_and_citations_are_inaccessible(
    client, project, project_fixture
):
    other = client.post("/api/projects", json=project_fixture).json()["id"]
    table = upload(client, project).json()
    mapped = client.post(f"/api/projects/{project}/mappings", json=mapping_for(table)).json()
    md = upload(client, project, MD, "policy.md", "knowledge").json()
    revision = select_knowledge(client, project, [md["id"]]).json()["id"]
    cid = client.get(
        f"/api/projects/{project}/knowledge/search", params={"q": "inspection"}
    ).json()[0]["chunk"]["citation_id"]
    assert client.get(f"/api/projects/{other}/sources/{table['id']}").status_code == 404
    assert client.get(f"/projects/{other}/sources/{md['id']}/original").status_code == 404
    assert (
        client.post(f"/api/projects/{other}/mappings", json=mapping_for(table)).status_code == 404
    )
    assert (
        client.get(f"/api/projects/{other}/mappings/{mapped['mapping_id']}/cases").status_code
        == 404
    )
    assert select_knowledge(client, other, [md["id"]]).status_code == 404
    assert (
        client.get(
            f"/api/projects/{other}/knowledge/search",
            params={"q": "inspection", "revision": revision},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/projects/{other}/citations/{cid}", params={"revision": revision}
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/projects/{other}/knowledge/search", params={"q": "inspection"}).json()
        == []
    )
    assert client.get(f"/api/projects/{uuid4()}").status_code == 404


def test_forms_mission_upload_mapping_confirmation_and_knowledge(client, project):
    response = client.post(
        f"/projects/{project}",
        headers=ORIGIN,
        data={
            "name": "Renamed",
            "mission": "Check tools",
            "business_goal": "",
            "expected_revision": "1",
        },
    )
    assert response.status_code == 200 and "Renamed" in response.text
    response = client.post(
        f"/projects/{project}/sources",
        headers=ORIGIN,
        files={"file": ("observations.csv", CSV)},
        data={"label": "observations", "encoding": "utf-8-sig", "delimiter": ","},
    )
    assert response.status_code == 200 and "2 data rows" in response.text
    assert client.get(f"/projects/{project}/mappings/new").status_code == 200
    fields = {
        "primary": "0",
        "grain": "one request",
        "decision_time": "before use",
        "available": "yes",
        "role_0": "input",
        "role_1": "input",
        "role_2": "outcome",
        "role_3": "target",
    }
    preview = client.post(f"/projects/{project}/mappings/preview", data=fields, headers=ORIGIN)
    assert preview.status_code == 200
    assert "Review 2 proposed cases" in preview.text
    match = re.search(r'name="mapping" value="([^"]+)"', preview.text)
    mapping = html.unescape(match[1])
    assert (
        client.post(
            f"/projects/{project}/mappings", data={"mapping": mapping}, headers=ORIGIN
        ).status_code
        == 422
    )
    assert client.get(f"/api/projects/{project}/mappings").json() == []
    confirmed = client.post(
        f"/projects/{project}/mappings", data={"mapping": mapping, "confirm": "yes"}, headers=ORIGIN
    )
    assert confirmed.status_code == 200
    assert len(client.get(f"/api/projects/{project}/mappings").json()) == 1
    md = upload(client, project, MD, "policy.md", "knowledge").json()
    knowledge = client.post(
        f"/projects/{project}/knowledge",
        headers=ORIGIN,
        data={"source_id": md["id"], "expected_revision": ""},
    )
    assert knowledge.status_code == 200
    assert (
        client.get(f"/projects/{project}/knowledge/search", params={"q": "damage"}).status_code
        == 200
    )


@pytest.mark.parametrize("value", [1, "true", None, False])
def test_mapping_confirmations_do_not_coerce_values(client, project, value):
    source = upload(client, project).json()
    mapping = mapping_for(source)
    mapping["confirmed"] = value
    assert client.post(f"/api/projects/{project}/mappings", json=mapping).status_code == 422
    assert client.get(f"/api/projects/{project}/mappings").json() == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"source_ids": []},
        {"source_ids": "not-a-list", "expected_revision": None},
        {"source_ids": [4], "expected_revision": None},
        {"source_ids": [], "expected_revision": "bad"},
        {"source_ids": [], "expected_revision": None, "extra": "sensitive"},
    ],
)
def test_invalid_knowledge_selection_does_not_create_revision(client, project, body):
    response = client.post(f"/api/projects/{project}/knowledge", json=body)
    assert response.status_code == 422
    assert "sensitive" not in response.text
    assert client.get(f"/api/projects/{project}/knowledge/revisions").json() == []


def test_source_label_is_explicit_and_only_markdown_knowledge_is_retrieved(client, project):
    assert upload(client, project, label="unreviewed").status_code == 422
    table = upload(client, project).json()
    assert select_knowledge(client, project, [table["id"]]).status_code == 422
    markdown = upload(client, project, MD, "policy.md", "observations").json()
    assert select_knowledge(client, project, [markdown["id"]]).status_code == 422
    md = upload(client, project, MD, "policy.md", "knowledge").json()
    assert select_knowledge(client, project, [md["id"], md["id"]]).status_code == 422
    assert (
        client.get(f"/api/projects/{project}/knowledge/search", params={"q": "inspection"}).json()
        == []
    )
    assert select_knowledge(client, project, [md["id"]]).status_code == 201


@pytest.mark.parametrize("kind", ["field", "sheet", "source"])
def test_mapping_invalid_references_are_rejected(client, project, kind):
    source = upload(client, project).json()
    mapping = mapping_for(source)
    if kind == "field":
        mapping["inputs"][0]["field"] = "missing"
    elif kind == "sheet":
        mapping["primary"]["sheet"] = "missing"
    else:
        mapping["primary"]["source_id"] = str(uuid4())
    response = client.post(f"/api/projects/{project}/mappings", json=mapping)
    assert response.status_code in (404, 422)
    assert client.get(f"/api/projects/{project}/mappings").json() == []


def test_tampered_derived_citation_fails_closed_and_reindex_repairs(client, settings, project):
    source = upload(client, project, MD, "policy.md", "knowledge").json()
    revision = select_knowledge(client, project, [source["id"]]).json()["id"]
    chunk = client.get(
        f"/api/projects/{project}/knowledge/search", params={"q": "inspection"}
    ).json()[0]["chunk"]
    modified = {**chunk, "line_start": 999}
    with connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE chunks SET document=? WHERE id=?", (json.dumps(modified), chunk["citation_id"])
        )
    response = client.get(f"/api/projects/{project}/citations/{chunk['citation_id']}")
    assert response.status_code == 503 and "CITATION_INVALID" in response.text
    assert select_knowledge(client, project, [source["id"]], revision).status_code == 201
    assert (
        client.get(f"/api/projects/{project}/citations/{chunk['citation_id']}").json()["chunk"]
        == chunk
    )


@pytest.mark.parametrize("route", ["mission", "mapping", "knowledge"])
def test_mutation_forms_require_origin(client, project, route):
    routes = {
        "mission": f"/projects/{project}",
        "mapping": f"/projects/{project}/mappings",
        "knowledge": f"/projects/{project}/knowledge",
    }
    assert client.post(routes[route], data={}).status_code == 403


def test_mapping_never_truncates_long_cases(client, project):
    source = upload(
        client,
        project,
        b"tool,status,paid_after,ideal_advice\n" + b"x" * 3900 + b"," + b"y" * 200 + b",12,check\n",
    ).json()
    response = client.post(f"/api/projects/{project}/mappings", json=mapping_for(source))
    assert response.status_code == 422 and "CASE_TOO_LONG" in response.text
    assert client.get(f"/api/projects/{project}/mappings").json() == []


def test_form_join_uses_explicit_keys(client, project):
    upload(client, project)
    upload(client, project, b"tool,category\ndrill,power\nsaw,cutting\n")
    response = client.post(
        f"/projects/{project}/mappings/preview",
        headers=ORIGIN,
        data={
            "primary": "0",
            "grain": "request",
            "decision_time": "before use",
            "available": "yes",
            "join_table": "1",
            "left_key": "0",
            "right_key": "4",
            "role_0": "input",
            "role_1": "input",
            "role_5": "input",
        },
    )
    assert response.status_code == 200
    assert "power" in response.text and "cutting" in response.text
    assert client.get(f"/api/projects/{project}/mappings").json() == []


@pytest.mark.parametrize("boundary", ["bytes", "chunks"])
def test_knowledge_resource_limits_leave_active_revision_unchanged(
    client, project, monkeypatch, boundary
):
    from quartermaster import knowledge

    source = upload(client, project, MD, "policy.md", "knowledge").json()
    revision = select_knowledge(client, project, [source["id"]]).json()["id"]
    monkeypatch.setattr(
        knowledge, "MAX_KNOWLEDGE_BYTES" if boundary == "bytes" else "MAX_KNOWLEDGE_CHUNKS", 1
    )
    response = select_knowledge(client, project, [source["id"]], revision)
    assert response.status_code == 422
    assert client.get(f"/api/projects/{project}/knowledge").json()["id"] == revision
    assert len(client.get(f"/api/projects/{project}/knowledge/revisions").json()) == 1


def test_openapi_exposes_versioned_foundation_contracts(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {
        "AdviserSpec",
        "Source",
        "CaseMapping",
        "DerivedCase",
        "KnowledgeRevision",
        "Evidence",
    } <= schemas.keys()


def test_join_cannot_use_declared_outcome_as_key_and_warns_about_unmapped_later_keys(
    client, project
):
    source = upload(client, project).json()
    other = upload(client, project, b"paid_after,category\n12,power\n0,cutting\n").json()
    mapping = mapping_for(source)
    mapping["inputs"].append(ref(other, "category"))
    mapping["joins"] = [
        {
            "table": {"source_id": other["id"], "sheet": "CSV"},
            "left": ref(source, "paid_after"),
            "right_key": "paid_after",
        }
    ]
    path = f"/api/projects/{project}/mappings"
    assert client.post(path, json=mapping).status_code == 422
    mapping["outcomes"] = []
    response = client.post(path + "/preview", json=mapping)
    # The second primary row has an empty outcome and cannot match the right key.
    assert response.status_code == 422 and "JOIN_UNMATCHED" in response.text
    # Use a table with exact matching keys solely to exercise the leakage warning.
    source = upload(client, project, b"tool,paid_after\ndrill,12\nsaw,0\n").json()
    mapping["primary"]["source_id"] = source["id"]
    mapping["inputs"] = [ref(source, "tool"), ref(other, "category")]
    mapping["targets"] = []
    mapping["joins"][0]["left"] = ref(source, "paid_after")
    response = client.post(path + "/preview", json=mapping)
    assert response.status_code == 200
    assert any("paid_after" in warning for warning in response.json()["warnings"])
    assert client.get(path).json() == []
