"""Opt-in, bounded local check of typed answers; never training data or a benchmark.

Run with --run-live --report /path/to/new-report.json. These synthetic development
policies define personal choices, not market truth. Expected results stay outside
the model context. No database, provider, training, promotion or retries are used.
"""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from quartermaster.config import Settings
from quartermaster.contracts.advice import Case
from quartermaster.contracts.adviser import AdviserSpec
from quartermaster.contracts.answers import CategoryAnswer, NumberAnswer
from quartermaster.generation import ADVICE_PARAMETERS
from quartermaster.inference import LocalInference
from quartermaster.prediction_context import assemble, digest
from quartermaster.predictions import generate

NUMBER = NumberAnswer(kind="number", unit="EUR")
CATEGORY = CategoryAnswer(kind="category", choices=["Visit", "Pass"])
PRICE_POLICY = (
    "Help me decide my personal preferred apartment price. My rule is 1000 EUR per "
    "square metre, minus 5000 EUR when repairs are needed. This is my preference."
)
VISIT_POLICY = (
    "Help me decide my personal Visit or Pass choice. Visit only if an apartment is quiet "
    "and its asking price is at most 80000 EUR. Otherwise Pass. If quietness or price is "
    "unknown and prevents the choice, ask me for it."
)
# Fixed development controls. Do not present these as reviewed owner material or
# mix them into any training dataset or reserved user evaluation suite.
CASES = [
    ("price-repair", NUMBER, PRICE_POLICY, "60 square metres; repairs needed.", 55000),
    ("price-no-repair", NUMBER, PRICE_POLICY, "72 square metres; no repairs needed.", 72000),
    ("price-missing-area", NUMBER, PRICE_POLICY, "Repairs needed; floor area unknown.", "area"),
    (
        "price-missing-condition",
        NUMBER,
        PRICE_POLICY,
        "60 square metres; repair needs unknown.",
        "repair",
    ),
    ("visit", CATEGORY, VISIT_POLICY, "Quiet apartment; asking price 75000 EUR.", "Visit"),
    ("pass-budget", CATEGORY, VISIT_POLICY, "Quiet apartment; asking price 90000 EUR.", "Pass"),
    (
        "visit-missing-price",
        CATEGORY,
        VISIT_POLICY,
        "Quiet apartment; asking price unknown.",
        "price",
    ),
    # An irrelevant missing fact must not block an otherwise supported choice.
    (
        "visit-irrelevant-unknown",
        CATEGORY,
        VISIT_POLICY,
        "Quiet apartment; asking price 75000 EUR; wall colour unknown.",
        "Visit",
    ),
    # False short-circuit: quietness cannot change the decision above the budget.
    (
        "pass-irrelevant-quietness",
        CATEGORY,
        VISIT_POLICY,
        "Asking price 90000 EUR; quietness unknown.",
        "Pass",
    ),
    (
        "unsupported-outcome",
        NUMBER,
        "Predict the exact sale price next year, not my personal valuation.",
        "The future buyer, market conditions and sale terms cannot be known.",
        "abstain",
    ),
    (
        "time-allowance",
        NumberAnswer(kind="number", unit="hours"),
        "My personal allowance is 2 hours per item plus 1 hour setup, once per batch.",
        "One batch contains 3 items. What total time would I allow?",
        7,
    ),
    (
        "time-missing-count",
        NumberAnswer(kind="number", unit="hours"),
        "My personal allowance is 2 hours per item plus 1 hour setup, once per batch.",
        "One batch contains an unknown number of items. What total time would I allow?",
        "count",
    ),
]


def check(prediction, fmt, expected):
    if prediction is None:
        return False
    if expected == "abstain":
        return prediction.behavior == "abstain"
    if expected in ("area", "repair", "price", "count"):
        terms = {
            "area": ("area", "metre", "meter", "size"),
            "repair": ("repair", "condition"),
            "price": ("price", "cost", "asking"),
            "count": ("how many", "number of", "count", "quantity"),
        }[expected]
        return prediction.behavior == "clarify" and any(
            term in prediction.question.casefold() for term in terms
        )
    return (
        prediction.behavior == "answer"
        and prediction.target.kind == fmt.kind
        and prediction.target.value == expected
    )


async def run(settings, report_path, *, thinking=False):
    adapter = LocalInference(settings)
    report = {
        "purpose": "synthetic development capability check; not unseen accuracy or LoRA quality",
        "model_sha256": settings.local_model_sha256,
        "thinking": thinking,
        "results": [],
    }
    for index, (name, fmt, mission, situation, expected) in enumerate(CASES, 1):
        spec = AdviserSpec(
            id=UUID(int=1),
            revision=1,
            created_at=datetime(2026, 10, 25, tzinfo=UTC),
            name="Synthetic capability control",
            mission=mission,
            answer_format=fmt,
        )
        item = assemble(spec, Case(case_id=UUID(int=index + 1), situation=situation), fmt, [])
        if thinking:
            # Explicit diagnostic comparison only; never change production defaults.
            fields = dict(
                system=item.system,
                context=item.context,
                parameters=ADVICE_PARAMETERS,
                response_schema=item.response_schema,
            )
            item = item.model_copy(
                update={"parameters": ADVICE_PARAMETERS, "input_sha256": digest(fields)}
            )
        started = time.monotonic()
        result = await generate(adapter, item)
        passed = check(result.prediction, fmt, expected)
        report["results"].append(
            {
                "case": name,
                "input": item.model_dump(mode="json"),
                "expected": expected,
                "result": result.model_dump(mode="json"),
                "seconds": round(time.monotonic() - started, 3),
                "passed": passed,
            }
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"{name}: {'pass' if passed else 'FAIL'}", flush=True)
    return all(row["passed"] for row in report["results"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-live", action="store_true", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--thinking", action="store_true")
    args = parser.parse_args()
    if args.report.exists() or not args.report.parent.is_dir():
        parser.error("Use a new report file in an existing directory.")
    if not asyncio.run(run(Settings(), args.report, thinking=args.thinking)):
        raise SystemExit("Capability check failed; inspect final answers before any demonstration.")


if __name__ == "__main__":
    main()
