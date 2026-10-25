import io
import json
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from muster.app import create_app
from muster.imports import parse_import
from muster.storage import connect
from tests.muster.test_app import token


def test_csv_features_duplicate_context_and_persistence(tmp_path):
    content = 'url,price,condition,notes,code\nhttps://example.com/a,90000,good,"Needs a kitchen, keep my judgment",0012\nhttps://EXAMPLE.com/a#photo,92000,fair,Second estimate,0013\n'
    result = parse_import("list.csv", content.encode(), "")
    assert result["duplicates"] == 1
    assert len(result["records"]) == 1
    assert [row["cells"]["price"] for row in result["records"][0]["input_rows"]] == [
        "90000",
        "92000",
    ]
    assert result["records"][0]["input_rows"][0]["cells"]["code"] == "0012"
    assert (
        result["records"][0]["input_rows"][0]["cells"]["notes"]
        == "Needs a kitchen, keep my judgment"
    )
    with TestClient(create_app(tmp_path)) as client:
        csrf = token(client.get("/"))
        page = client.post(
            "/imports/preview", data={"csrf": csrf}, files={"spreadsheet": ("list.csv", content)}
        )
        assert "Second estimate" in page.text
        action = re.search(r'action="(/imports/[^\"]+/confirm)"', page.text)[1]
        assert client.post(action, data={"csrf": csrf}).status_code == 200
    with TestClient(create_app(tmp_path)):
        with connect(tmp_path) as db:
            job = db.execute("SELECT * FROM jobs").fetchone()
            rows = json.loads(job["input_rows"])
            assert len(rows) == 2
            assert rows[1]["row"] == 2
            assert rows[1]["cells"]["condition"] == "fair"


def test_xlsx_keeps_native_types_and_formulas_without_evaluating():
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["url", "price", "balcony", "listed", "notes", "estimate"])
    sheet.append(
        ["https://example.com", 90000.5, True, date(2026, 10, 25), "My own opinion", "=1+2"]
    )
    buffer = io.BytesIO()
    workbook.save(buffer)
    row = parse_import("list.xlsx", buffer.getvalue(), "")["records"][0]["input_rows"][0]
    assert row["cells"]["price"] == 90000.5
    assert row["cells"]["balcony"] is True
    assert row["cells"]["listed"].startswith("2026-10-25")
    assert row["cells"]["estimate"] == "=1+2"
    assert row["kinds"]["estimate"] == "formula"
    assert row["kinds"]["price"] == "number"


@pytest.mark.parametrize(
    "content",
    [
        "url,price,Price\nhttps://example.com,1,2",
        "url,\nhttps://example.com,9",
        "url\nhttps://example.com,9",
    ],
)
def test_ambiguous_columns_are_rejected(content):
    with pytest.raises(ValueError):
        parse_import("list.csv", content.encode(), "")


def test_schema_samples_include_all_supplied_feature_rows(tmp_path):
    from uuid import uuid4

    from muster.schema import sample_pages
    from muster.storage import initialize

    initialize(tmp_path)
    record = parse_import(
        "list.csv",
        b"url,price,category,notes\nhttps://example.com,90000,flat,Personal judgement\nhttps://example.com,95000,flat,Second estimate",
        "",
    )["records"][0]
    capture_id = uuid4().hex
    with connect(tmp_path) as db:
        collection = db.execute("INSERT INTO collections(name) VALUES('Features')").lastrowid
        job = db.execute(
            "INSERT INTO jobs(collection_id,url,input_rows,status) VALUES(?,?,?,'captured')",
            (collection, record["url"], json.dumps(record["input_rows"])),
        ).lastrowid
        directory = tmp_path / "sources" / str(job) / capture_id
        directory.mkdir(parents=True)
        (directory / "page.html").write_text("<p>Apartment listing</p>")
        db.execute(
            "INSERT INTO captures(id,job_id,captured_at,final_url,status,metadata) VALUES(?,?,? ,?,'captured','{}')",
            (capture_id, job, "2026-10-25", record["url"]),
        )
    sample = sample_pages(tmp_path, collection)[0]
    assert [row["cells"]["price"] for row in sample["input_rows"]] == ["90000", "95000"]
    assert sample["input_rows"][0]["cells"]["notes"] == "Personal judgement"
