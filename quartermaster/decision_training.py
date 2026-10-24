"""Offline preparation and scoring for the isolated synthetic selector experiment."""

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from uuid import uuid4

from quartermaster.contracts.advice import DecisionOnly
from quartermaster.contracts.decision_training import (
    DecisionJob,
    DecisionReviewPack,
    content_hash,
)

ACTIONS = ("answer", "clarify", "abstain")


def read_pack(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 2_000_000:
        raise ValueError("DECISION_PACK: Use a bounded regular review file")
    return DecisionReviewPack.model_validate_json(path.read_bytes())


def dataset(pack):
    """Exact captured system/context, minimal target; no review/rationale/domain in messages."""
    rows = []
    for example in sorted(pack.examples, key=lambda e: str(e.id)):
        rows.append(
            {
                "id": str(example.id),
                "messages": [
                    {"role": "system", "content": pack.system},
                    {"role": "user", "content": example.context},
                    {"role": "assistant", "content": example.target.model_dump_json()},
                ],
            }
        )
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode() for row in rows
    )


def checked_evaluation(suite):
    DecisionReviewPack.model_validate_json(suite.model_dump_json())
    counts = Counter(e.target.decision for e in suite.examples)
    if (
        suite.purpose != "evaluation"
        or len(suite.examples) != 30
        or counts != dict.fromkeys(ACTIONS, 10)
        or len({e.domain for e in suite.examples}) < 5
        or any(e.review.status != "approved" for e in suite.examples)
    ):
        raise ValueError("DECISION_EVALUATION: Review all thirty balanced frozen references")


def freeze(teaching, evaluation, destination, *, independent_owner_review=False):
    """No GPU, database or automatic approvals. Fail before writing on unresolved reviews."""
    if independent_owner_review is not True:
        raise ValueError("DECISION_REVIEW: Independent owner evaluation review is required")
    teaching = DecisionReviewPack.model_validate_json(teaching.model_dump_json())
    evaluation = DecisionReviewPack.model_validate_json(evaluation.model_dump_json())
    if teaching.purpose != "teaching" or any(
        e.review.status not in {"approved", "rejected"} for e in teaching.examples
    ):
        raise ValueError("DECISION_REVIEW: Resolve pending and revised teaching examples")
    checked_evaluation(evaluation)
    selected = DecisionReviewPack(
        purpose="teaching",
        system=teaching.system,
        examples=[e for e in teaching.examples if e.review.status == "approved"],
    )
    if {e.id for e in selected.examples} & {e.id for e in evaluation.examples} or {
        e.identity() for e in selected.examples
    } & {e.identity() for e in evaluation.examples}:
        raise ValueError("DECISION_HELD_OUT: Evaluation content cannot enter supervision")
    unseen = {e.domain for e in evaluation.examples} - {e.domain for e in selected.examples}
    if len(unseen) < 2 or sum(e.domain in unseen for e in evaluation.examples) < 10:
        raise ValueError("DECISION_DOMAINS: Reserve two unseen domains and ten cases")
    raw = dataset(selected)
    evaluation_bytes = evaluation.model_dump_json().encode()
    job = DecisionJob(
        id=uuid4(),
        supervision=selected,
        evaluation_sha256=hashlib.sha256(evaluation_bytes).hexdigest(),
        dataset_sha256=hashlib.sha256(raw).hexdigest(),
    )
    destination = Path(destination)
    destination.mkdir(exist_ok=False)
    (destination / "input").mkdir()
    write_new(destination / "input/job.json", job.model_dump_json().encode())
    write_new(destination / "input/train.jsonl", raw)
    # A sibling, never part of the trainer's /input bind mount.
    write_new(destination / "evaluation.json", evaluation_bytes)
    write_new(
        destination / "freeze.json",
        json.dumps(
            {
                "schema_version": "quartermaster.decision-freeze/v1",
                "job_sha256": hashlib.sha256(job.model_dump_json().encode()).hexdigest(),
                "evaluation_sha256": job.evaluation_sha256,
                "source_review_pack_sha256": content_hash(teaching.model_dump(mode="json")),
                "independent_owner_review": True,
                "rejected_ids": [
                    str(e.id) for e in teaching.examples if e.review.status == "rejected"
                ],
                "automatic_promotion": False,
            },
            indent=2,
        ).encode(),
    )
    return job


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)


def load_job(directory):
    directory = Path(directory)
    if {p.name for p in directory.iterdir()} != {"job.json", "train.jsonl"}:
        raise ValueError("DECISION_INPUT: Mount only the reviewed job and training rows")
    job_path, rows_path = directory / "job.json", directory / "train.jsonl"
    if any(p.is_symlink() or p.stat().st_size > 2_000_000 for p in (job_path, rows_path)):
        raise ValueError("DECISION_INPUT: Use bounded regular job files")
    job = DecisionJob.model_validate_json(job_path.read_bytes())
    rows = rows_path.read_bytes()
    if hashlib.sha256(rows).hexdigest() != job.dataset_sha256 or rows != dataset(job.supervision):
        raise ValueError("DECISION_DATASET: Dataset differs from reviewed job")
    return job, [json.loads(line) for line in rows.splitlines()]


def checked_bundle(directory, job):
    """Host-only check; never give the evaluation sibling to the trainer container."""
    directory = Path(directory)
    freeze_path, suite_path = directory / "freeze.json", directory / "evaluation.json"
    if any(p.is_symlink() or p.stat().st_size > 2_000_000 for p in (freeze_path, suite_path)):
        raise ValueError("DECISION_FREEZE: Invalid frozen review files")
    frozen = json.loads(freeze_path.read_bytes())
    if (
        frozen.get("independent_owner_review") is not True
        or frozen.get("job_sha256")
        != hashlib.sha256((directory / "input/job.json").read_bytes()).hexdigest()
        or frozen.get("evaluation_sha256") != job.evaluation_sha256
        or hashlib.sha256(suite_path.read_bytes()).hexdigest() != job.evaluation_sha256
    ):
        raise ValueError("DECISION_FREEZE: Frozen lineage or independent review differs")
    suite = read_pack(suite_path)
    checked_evaluation(suite)
    if {e.identity() for e in suite.examples} & {e.identity() for e in job.supervision.examples}:
        raise ValueError("DECISION_HELD_OUT: Frozen evaluation overlaps supervision")


def wilson(successes, total):
    """Descriptive 95% binomial interval; synthetic cases need not be independent draws."""
    z = 1.959963984540054
    p = successes / total
    d = 1 + z * z / total
    center = (p + z * z / (2 * total)) / d
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / d
    return [max(0.0, center - half), min(1.0, center + half)]


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate decision key")
        result[key] = value
    return result


def score(suite, baseline, candidate):
    """Evaluation only. Invalid/missing generations count as misses; no promotion side effect.

    Values are complete raw decision JSON strings, or None for a failed generation.
    The generation adapter must separately enforce finish_reason=stop and identity.
    """
    checked_evaluation(suite)
    ids = {str(e.id) for e in suite.examples}
    if set(baseline) != ids or set(candidate) != ids:
        raise ValueError("DECISION_OUTPUTS: Supply every frozen case exactly once")

    def summarize(outputs):
        confusion = {a: dict.fromkeys((*ACTIONS, "invalid"), 0) for a in ACTIONS}
        domains = {}
        labels = {}
        for example in suite.examples:
            try:
                data = json.loads(outputs[str(example.id)], object_pairs_hook=unique_keys)
                label = DecisionOnly.model_validate(data).decision
            except (TypeError, ValueError):
                label = "invalid"
            labels[str(example.id)] = label
            expected = example.target.decision
            confusion[expected][label] += 1
            domain = domains.setdefault(example.domain, {"correct": 0, "total": 0})
            domain["total"] += 1
            domain["correct"] += label == expected
        correct = sum(confusion[a][a] for a in ACTIONS)
        invalid = sum(confusion[a]["invalid"] for a in ACTIONS)
        per_class = {}
        for action in ACTIONS:
            n = sum(confusion[action].values())
            per_class[action] = {
                "correct": confusion[action][action],
                "total": n,
                "recall": confusion[action][action] / n,
                "wilson_95": wilson(confusion[action][action], n),
            }
        for d in domains.values():
            d.update(accuracy=d["correct"] / d["total"], wilson_95=wilson(d["correct"], d["total"]))
        return {
            "total": len(ids),
            "correct": correct,
            "invalid": invalid,
            "accuracy": correct / len(ids),
            "macro_recall": sum(v["recall"] for v in per_class.values()) / 3,
            "wilson_95": wilson(correct, len(ids)),
            "confusion_matrix": confusion,
            "per_class": per_class,
            "per_domain": domains,
            "false_answer_on_abstain": confusion["abstain"]["answer"],
            "false_answer_on_clarify": confusion["clarify"]["answer"],
            "unnecessary_clarify": confusion["answer"]["clarify"],
            "unsupported_false_answer_wilson_95": wilson(confusion["abstain"]["answer"], 10),
            "labels": labels,
        }

    base, attempted = summarize(baseline), summarize(candidate)
    improvement = (attempted["correct"] - base["correct"]) / len(ids)
    gates = {
        "all_structurally_valid": attempted["invalid"] == 0,
        "macro_recall_at_least_90_percent": attempted["macro_recall"] >= 0.9,
        "every_class_recall_at_least_80_percent": all(
            v["recall"] >= 0.8 for v in attempted["per_class"].values()
        ),
        "every_domain_accuracy_at_least_80_percent": all(
            v["accuracy"] >= 0.8 for v in attempted["per_domain"].values()
        ),
        "absolute_improvement_at_least_15_points": improvement >= 0.15,
        "zero_false_answer_on_abstain": attempted["false_answer_on_abstain"] == 0,
        "no_increase_unnecessary_clarify": (
            attempted["unnecessary_clarify"] <= base["unnecessary_clarify"]
        ),
    }
    return {
        "schema_version": "quartermaster.decision-comparison/v1",
        "baseline": base,
        "candidate": attempted,
        "paired_changes": [
            {"id": key, "baseline": base["labels"][key], "candidate": attempted["labels"][key]}
            for key in sorted(ids)
        ],
        "absolute_improvement": improvement,
        "provisional_experimental_gates": gates,
        "all_proposed_gates_passed": all(gates.values()),
        "uncertainty_note": (
            "Wilson 95% binomial intervals are descriptive under independent-trial assumptions. "
            "Authored synthetic cases may be correlated and are not a population sample; "
            "these intervals and a thirty-case pass are not a general reliability guarantee."
        ),
        "automatic_promotion": False,
        "advice_quality_evaluated": False,
    }
