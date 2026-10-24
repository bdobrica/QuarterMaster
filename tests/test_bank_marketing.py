"""Experiment transforms use tiny invented records; no downloaded rows are checked in."""

import csv
import io
import json

import pytest

from tests.prepare_bank_marketing import HEADERS, INPUTS, csv_bytes, digest, prepare


def downloaded(tmp_path, rows=None):
    root = tmp_path / "download"
    folder = root / "bank-additional"
    folder.mkdir(parents=True)
    rows = rows or [
        {
            **dict.fromkeys(HEADERS, "unknown"),
            "age": str(20 + i),
            "duration": "12345",
            "y": "yes" if i % 3 else "no",
            "pdays": "999",
            "previous": "0",
            "poutcome": "nonexistent",
        }
        for i in range(20)
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, HEADERS, delimiter=";", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path = folder / "bank-additional-full.csv"
    path.write_text(stream.getvalue())
    return root, path, rows


def read_csv(path):
    return list(csv.DictReader(io.StringIO(path.read_text())))


def test_bounded_chronological_split_provenance_and_separate_outcomes(tmp_path):
    root, original, rows = downloaded(tmp_path)
    before = original.read_bytes()
    output = tmp_path / "experiment"
    report = prepare(root, output, development_limit=5, reserve_limit=3)
    dev = read_csv(output / "observations.csv")
    reserve = read_csv(output / "reserved-inputs.csv")
    assert len(dev) == 5 and len(reserve) == 3
    assert dev[0]["source_row"] == "2" and reserve[0]["source_row"] == "18"
    assert dev[-1]["source_row"] == "17" and reserve[-1]["source_row"] == "21"
    assert all("duration" not in row and "campaign" not in row for row in dev + reserve)
    assert all("y" not in row for row in reserve)
    for row in dev:
        source = rows[int(row["source_row"]) - 2]
        assert all(row[field] == source[field] for field in (*INPUTS, "y"))
    assert original.read_bytes() == before
    assert report["source"]["sha256"] == digest(before)
    assert report["mapping_requires_owner_confirmation"]
    assert report["sft_examples"] == report["training_jobs"] == 0
    assert json.loads((output / "preparation.json").read_text()) == report
    for name, entry in report["files"].items():
        assert digest((output / name).read_bytes()) == entry["sha256"]


def test_split_does_not_use_outcomes_or_duration_and_never_overwrites(tmp_path):
    root, path, rows = downloaded(tmp_path)
    first, second = tmp_path / "a", tmp_path / "b"
    prepare(root, first)
    for row in rows:
        row["y"] = "no" if row["y"] == "yes" else "yes"
        row["duration"] = "0"
    path.write_bytes(csv_bytes(rows, HEADERS).replace(b",", b";"))
    prepare(root, second)
    assert (first / "reserved-inputs.csv").read_bytes() == (
        second / "reserved-inputs.csv"
    ).read_bytes()
    assert [r["source_row"] for r in read_csv(first / "observations.csv")] == [
        r["source_row"] for r in read_csv(second / "observations.csv")
    ]
    with pytest.raises(ValueError, match="immutable"):
        prepare(root, first)


def test_exclude_profiles_from_entire_earlier_pool_not_only_uploaded_subset(tmp_path):
    root, path, rows = downloaded(tmp_path)
    # Row 17 shares a customer-profile proxy with an unselected development row.
    rows[16] = {**rows[7], "previous": "9", "y": "yes"}
    path.write_bytes(csv_bytes(rows, HEADERS).replace(b",", b";"))
    output = tmp_path / "experiment"
    prepare(root, output, development_limit=2)
    assert "18" not in [r["source_row"] for r in read_csv(output / "reserved-inputs.csv")]


def test_ambiguous_entity_overlap_does_not_fall_back_to_random_split(tmp_path):
    root, path, rows = downloaded(tmp_path)
    rows = [rows[0]] * 20
    path.write_bytes(csv_bytes(rows, HEADERS).replace(b",", b";"))
    output = tmp_path / "experiment"
    with pytest.raises(ValueError, match="disjoint"):
        prepare(root, output)
    assert not output.exists()


@pytest.mark.parametrize("change", ["schema", "label", "missing"])
def test_bad_source_leaves_no_output(tmp_path, change):
    root, path, _ = downloaded(tmp_path)
    value = path.read_text()
    if change == "schema":
        value = value.replace("day_of_week", "day")
    elif change == "label":
        value = value.replace(";yes\n", ";maybe\n")
    else:
        value = value.replace(";no\n", "\n", 1)
    path.write_text(value)
    output = tmp_path / "experiment"
    with pytest.raises(ValueError):
        prepare(root, output)
    assert not output.exists()
