"""Opt-in HTTP smoke script: run inside a fresh, network-isolated web container."""

import hashlib
import importlib.util
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import uuid4

from openpyxl import Workbook

BASE = "http://127.0.0.1:8000"


def request(path, data=None, method=None, content_type=None, origin=False):
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if origin:
        headers["Origin"] = BASE
    response = urllib.request.urlopen(
        urllib.request.Request(BASE + path, data=data, method=method, headers=headers), timeout=15
    )
    return response.read(), response.headers


def api(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    raw, _ = request(path, data, method, "application/json" if data is not None else None)
    return json.loads(raw)


def upload(pid, name, data, label):
    boundary = uuid4().hex
    parts = []
    for key, value in {"label": label, "encoding": "utf-8-sig", "delimiter": ","}.items():
        parts.append(
            (
                f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'
            ).encode()
        )
    parts.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"'
            "\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    raw, _ = request(
        f"/api/projects/{pid}/sources",
        b"".join(parts),
        content_type=f"multipart/form-data; boundary={boundary}",
        origin=True,
    )
    return json.loads(raw)


for attempt in range(30):
    try:
        assert api("/healthz") == {"status": "ok"}
        break
    except (OSError, urllib.error.URLError):
        if attempt == 29:
            raise
        time.sleep(0.1)
assert importlib.util.find_spec("torch") is None
project = api(
    "/api/projects",
    {
        "name": "Synthetic container check",
        "mission": "Check inspection status before advising.",
        "business_goal": "Prepare reviewed cases.",
    },
)
pid = project["id"]
base = f"/api/projects/{pid}"
assert api(base)["schema_version"] == "quartermaster.adviser/v1"
assert (
    api(
        base,
        {
            "name": "Updated synthetic adviser",
            "mission": "Ask if inspection status is missing.",
            "business_goal": None,
            "expected_revision": 1,
        },
        "PATCH",
    )["revision"]
    == 2
)
csv = b"tool,status,paid_after\ndrill,current,12\nsaw,overdue,0\n"
md = (
    b"# Inspection\nA current inspection is required.\n\n# Damage\n"
    b"Ask about damage.\n<script>untrusted</script>\n"
)
book = Workbook()
book.active.title = "Requests"
book.active.append(["tool", "status", "formula"])
book.active.append(["drill", "current", "=1+1"])
book.create_sheet("Other").append(["field"])
buffer = io.BytesIO()
book.save(buffer)
book.close()
xlsx = buffer.getvalue()
sources = [
    upload(pid, "cases.csv", csv, "observations"),
    upload(pid, "book.xlsx", xlsx, "examples"),
    upload(pid, "policy.md", md, "knowledge"),
]
assert sources[0]["sheets"][0]["row_count"] == 2
assert len(sources[1]["sheets"]) == 2
assert sources[1]["sheets"][0]["fields"][2]["formulas"] == 1
assert len(api(base + "/sources")) == 3
for source, original in zip(sources, [csv, xlsx, md], strict=True):
    assert source["sha256"] == hashlib.sha256(original).hexdigest()
    original_path = f"/projects/{pid}/sources/{source['id']}/original"
    raw, headers = request(original_path)
    assert raw == original and headers["X-Content-Type-Options"] == "nosniff"
    source_page, _ = request(f"/projects/{pid}/sources/{source['id']}")
    assert b"<script>untrusted</script>" not in source_page
source_id = sources[0]["id"]


def ref(field):
    return {"source_id": source_id, "sheet": "CSV", "field": field}


mapping = {
    "primary": {"source_id": source_id, "sheet": "CSV"},
    "grain": "one request",
    "decision_time": "before handover",
    "inputs": [ref("tool"), ref("status")],
    "outcomes": [ref("paid_after")],
    "confirmed": True,
    "inputs_available_at_decision": True,
}
preview = api(base + "/mappings/preview", mapping)
assert preview["case_count"] == 2 and api(base + "/mappings") == []
saved = api(base + "/mappings", mapping)
assert saved == api(base + "/mappings", mapping)
cases = api(base + f"/mappings/{saved['mapping_id']}/cases")
assert "paid_after" not in cases[0]["case"]["situation"]
assert "paid_after" in cases[0]["case"]["observed_outcome"]
assert cases[0]["source_rows"][0]["source_sha256"] == sources[0]["sha256"]
form = urllib.parse.urlencode(
    {
        "primary": "0",
        "grain": "one request",
        "decision_time": "before handover",
        "available": "yes",
        "role_0": "input",
        "role_1": "input",
        "role_2": "outcome",
    }
).encode()
review, _ = request(
    f"/projects/{pid}/mappings/preview",
    form,
    content_type="application/x-www-form-urlencoded",
    origin=True,
)
assert b"Review 2 proposed cases" in review and b"cases.csv (upload 1)" in review
revision = api(base + "/knowledge", {"source_ids": [sources[2]["id"]], "expected_revision": None})
results = api(base + "/knowledge/search?q=inspection")
assert len(results) == 1
chunk = results[0]["chunk"]
assert md.decode()[chunk["start"] : chunk["end"]] == chunk["text"]
citation_path = base + f"/citations/{chunk['citation_id']}"
assert api(citation_path)["chunk"] == chunk
request(f"/projects/{pid}/citations/{chunk['citation_id']}?revision={revision['id']}")
request(f"/projects/{pid}/knowledge/search?q=damage")
request(f"/projects/{pid}/mappings/new")
request(f"/projects/{pid}")
api(base + "/knowledge", {"source_ids": [], "expected_revision": revision["id"]})
assert api(base + "/knowledge/search?q=inspection") == []
try:
    api(citation_path)
    raise AssertionError("removed citation still current")
except urllib.error.HTTPError as exc:
    assert exc.code == 404
assert api(citation_path + "?revision=" + revision["id"])["chunk"] == chunk
assert len(api(base + "/revisions")) == 4
print(
    json.dumps(
        {
            "result": "passed",
            "sources": 3,
            "derived_cases": len(cases),
            "knowledge_revisions": len(api(base + "/knowledge/revisions")),
            "network": "none",
            "torch_installed": False,
        }
    )
)
