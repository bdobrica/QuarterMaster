"""Offline experiment preparation, not app preprocessing or approved supervision.

Run: uv run --locked python -m tests.prepare_bank_marketing \
    --dataset-dir ~/bank-marketing --output data/bank-marketing/acceptance-01
"""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

from quartermaster.contracts.sources import ParseOptions
from quartermaster.ingestion import MAX_CELLS, MAX_ROWS, MAX_UPLOAD, parse

INPUTS = (
    "age",
    "job",
    "marital",
    "education",
    "default",
    "housing",
    "loan",
    "pdays",
    "previous",
    "poutcome",
)
# A conservative proxy, NOT an identity: repeated customers cannot be identified.
GROUP = INPUTS[:7]
HEADERS = (
    "age",
    "job",
    "marital",
    "education",
    "default",
    "housing",
    "loan",
    "contact",
    "month",
    "day_of_week",
    "duration",
    "campaign",
    "pdays",
    "previous",
    "poutcome",
    "emp.var.rate",
    "cons.price.idx",
    "cons.conf.idx",
    "euribor3m",
    "nr.employed",
    "y",
)
EXCLUDED = {
    "y": "Later subscription outcome; never an input or ideal-advice label.",
    "duration": "Known only after the current call.",
    "campaign": "Includes the current contact; not a pre-call count.",
    "contact": "Recorded last-contact channel, not an independently confirmed plan.",
    "month": "Recorded last-contact month, not an independently confirmed plan.",
    "day_of_week": "Recorded last-contact day, not an independently confirmed plan.",
    "emp.var.rate": "Point-in-time publication availability not established here.",
    "cons.price.idx": "Point-in-time publication availability not established here.",
    "cons.conf.idx": "Point-in-time publication availability not established here.",
    "euribor3m": "Point-in-time publication availability not established here.",
    "nr.employed": "Point-in-time publication availability not established here.",
}
MISSION = (
    "Help a marketing analyst review the information available before a bank term-deposit "
    "campaign call. Explain relevant prior-contact facts, identify missing evidence, and ask "
    "a focused question before offering unsupported prioritization advice."
)
GOAL = (
    "Test useful, evidence-grounded pre-call advice and improvement after reviewed corrections; "
    "do not claim conversion probabilities, permission to contact, or increased subscriptions."
)
KNOWLEDGE = """# Bank marketing: experiment reference (AI-drafted summary)

This is a reviewable summary of the downloaded data dictionary and experiment boundaries,
not bank policy, customer permission, investment advice, or approved SFT supervision.

## Prior campaign history: pdays, previous and poutcome

For bank-additional, pdays=999 means the client was not previously contacted. It does
not mean a previous contact occurred 999 days ago. previous counts contacts before
the current campaign. poutcome describes a previous campaign, not the current result.
A past success does not establish a current subscription. Unknown values indicate
missing information; do not silently turn them into a negative answer.

## Before a current call

duration is measured after the current call and cannot inform pre-call advice. y is
the later subscription outcome, never an ideal recommendation. campaign includes the
current contact; this experiment excludes it rather than assuming a pre-call count.
Recorded last-contact channel/calendar fields and economic indicators are also excluded
until their availability at decision time is established. Customer profile fields are
assumed available for this offline exercise only; the CSV is not a point-in-time audit.
Do not infer consent, eligibility, current preferences or contact permission from these
fields: the dataset does not supply them. Ask for information relevant to the question.

## What this exercise can establish

These historical rows contain observations, not expert target advice. They can test
uploading, provenance, missing-information questions, source citations and reviewed lessons.
They do not establish whom a bank should call, a causal effect of contacting a customer,
or a calibrated probability. No current bank policy or independently validated predictor
has been supplied. An unsupported request may require clarification or abstention.

## Source and attribution

Moro, S., Rita, P., & Cortez, P. (2014). Bank Marketing [Dataset]. UCI Machine Learning
Repository. https://doi.org/10.24432/C5K306. CC BY 4.0.
https://archive.ics.uci.edu/dataset/222/bank+marketing
Dictionary: bank-additional/bank-additional-names.txt in the owner's local download.
Related paper: A Data-Driven Approach to Predict the Success of Bank Telemarketing,
Decision Support Systems (2014), https://doi.org/10.1016/j.dss.2014.03.001.
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def vector(row, fields=INPUTS):
    return tuple(row[field] for field in fields)


def csv_bytes(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def spaced(rows, limit):
    """Cover the available ordered period without using outcomes or random state."""
    count = min(len(rows), limit)
    if count <= 1:
        return rows[:count]
    return [rows[i * (len(rows) - 1) // (count - 1)] for i in range(count)]


def prepare(dataset_dir, output, *, development_limit=4000, reserve_limit=24):
    if output.exists():
        raise ValueError("Choose a new output directory; previous experiment bytes are immutable")
    if not 1 <= development_limit <= 4000 or not 1 <= reserve_limit <= 100:
        raise ValueError("Use 1–4000 development and 1–100 reserved rows")
    path = dataset_dir / "bank-additional/bank-additional-full.csv"
    original = path.read_bytes()
    reader = csv.DictReader(io.StringIO(original.decode("utf-8-sig")), delimiter=";")
    if tuple(reader.fieldnames or ()) != HEADERS:
        raise ValueError("Expected the original bank-additional-full.csv 21-column schema")
    rows = list(reader)
    if len(rows) < 10 or any(
        set(row) != set(HEADERS) or None in row.values() or row["y"] not in {"yes", "no"}
        for row in rows
    ):
        raise ValueError("Expected complete historical records with yes/no outcomes")
    # The upstream dictionary says rows are time-ordered, but no exact date or client ID exists.
    cut = len(rows) * 4 // 5
    prefix_groups = {vector(row, GROUP) for row in rows[:cut]}
    seen = set()
    development, reserve = [], []
    for index, row in enumerate(rows):
        fingerprint = vector(row)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        record = {"source_row": str(index + 2), **row}
        if index < cut:
            development.append(record)
        elif index >= cut and vector(row, GROUP) not in prefix_groups:
            reserve.append(record)
    development = spaced(development, development_limit)
    reserve = spaced(reserve, reserve_limit)
    if not development or not reserve:
        raise ValueError("Not enough disjoint later cases; no fallback to a random split")
    files = {
        "observations.csv": csv_bytes(development, ("source_row", *INPUTS, "y")),
        "reserved-inputs.csv": csv_bytes(reserve, ("source_row", *INPUTS)),
        "reserved-outcomes.csv": csv_bytes(reserve, ("source_row", "y")),
        "knowledge.md": KNOWLEDGE.encode(),
    }
    # Prove the generated upload meets the actual parser contract, without raising app limits.
    parsed = parse(files["observations.csv"], "csv", ParseOptions())
    assert len(parsed.tables[0].rows) == len(development)
    report = {
        "schema_version": "quartermaster.bank-experiment/v1",
        "source": {
            "file": str(path.relative_to(dataset_dir)),
            "sha256": digest(original),
            "rows": len(rows),
            "columns": len(HEADERS),
            "bytes": len(original),
        },
        "original_fits_upload_limits": (
            len(rows) <= MAX_ROWS
            and len(rows) * len(HEADERS) <= MAX_CELLS
            and len(original) <= MAX_UPLOAD
        ),
        "subscription_counts_audit_only": dict(Counter(row["y"] for row in rows)),
        "unknown_counts": {field: sum(row[field] == "unknown" for row in rows) for field in INPUTS},
        "decision_inputs": list(INPUTS),
        "outcomes": ["y"],
        "excluded": EXCLUDED,
        "split": {
            "method": "systematically spaced unique inputs within first 80% / last 20% pools",
            "cut_after_data_row": cut,
            "development_rows": len(development),
            "reserved_rows": len(reserve),
            "group_proxy_fields": list(GROUP),
            "exact_input_overlap": 0,
            "profile_proxy_overlap_with_entire_prefix": 0,
            "limitations": [
                "No client IDs: entity independence is not proven.",
                "No exact timestamps: ordering follows upstream documentation.",
                "Similar profiles can remain; no semantic deduplication claim.",
                "Profile exclusion and bounded selection are not representative sampling.",
                "Reserved rows are not app-frozen until explicitly saved and frozen.",
            ],
        },
        "mission_draft": MISSION,
        "business_goal_draft": GOAL,
        "mapping_requires_owner_confirmation": True,
        "knowledge_status": "AI_DRAFT source summary, not a bank policy",
        "sft_examples": 0,
        "training_jobs": 0,
        "files": {
            name: {"sha256": digest(data), "bytes": len(data)} for name, data in files.items()
        },
    }
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "preparation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.dataset_dir.expanduser(), args.output)
    print(
        json.dumps(
            {"output": str(args.output), "source": report["source"], "split": report["split"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
