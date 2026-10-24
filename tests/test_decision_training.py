"""Synthetic unit fixtures only; never owner approvals or a protected evaluation suite."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from quartermaster.contracts.decision_training import (
    DecisionExample,
    DecisionJob,
    DecisionRecipe,
    DecisionReviewPack,
)
from quartermaster.decision_training import checked_bundle, dataset, freeze, load_job, score, wilson
from quartermaster.decision_worker import command, run_stage
from quartermaster.decoding_probe import VISIBLE_DECISION_CONTRACT
from quartermaster.reliability import CONTRACT_SYSTEM

SYSTEM = CONTRACT_SYSTEM + VISIBLE_DECISION_CONTRACT
IMAGE = "sha256:" + "a" * 64


def reviewed(example):
    data = example.model_dump(mode="json")
    data["review"] = {
        "status": "approved",
        "reviewer": "owner",
        "content_sha256": example.content_sha256(),
        "notes": "Unit-test approval only, not an actual owner review.",
    }
    return DecisionExample.model_validate(data)


def pack(purpose="teaching", *, approved=True):
    n = 45 if purpose == "teaching" else 30
    examples = []
    for i in range(n):
        context = {
            "case": {"situation": f"{purpose} unit fixture question {i}?"},
            "structured_inputs": {"count": i},
            "reference_definitions": [
                {
                    "id": "fixture",
                    "text": "Count is a count.",
                    "origin": "AI_DRAFT_SYNTHETIC_DEFINITION",
                }
            ],
            "approved_lessons": [],
        }
        example = DecisionExample(
            id=uuid4(),
            label=f"fixture-{i}",
            domain=f"domain-{i % (3 if purpose == 'teaching' else 5)}",
            origin="AI_DRAFT",
            context=json.dumps(context),
            target={"decision": ("answer", "clarify", "abstain")[i % 3]},
        )
        examples.append(reviewed(example) if approved else example)
    return DecisionReviewPack(purpose=purpose, system=SYSTEM, examples=examples)


def test_freeze_excludes_evaluation_and_binds_exact_reviewed_rows(tmp_path):
    teaching, evaluation = pack(), pack("evaluation")
    root = tmp_path / "frozen"
    job = freeze(teaching, evaluation, root, independent_owner_review=True)
    loaded, rows = load_job(root / "input")
    assert loaded == job and len(rows) == 45
    assert set(p.name for p in (root / "input").iterdir()) == {"job.json", "train.jsonl"}
    assert (root / "evaluation.json").is_file()
    wire = (root / "input/job.json").read_text() + (root / "input/train.jsonl").read_text()
    assert all(str(e.id) not in wire and e.context not in wire for e in evaluation.examples)
    for row in rows:
        assert row["messages"][0] == {"role": "system", "content": SYSTEM}
        assert set(json.loads(row["messages"][2]["content"])) == {"decision"}
        assert "Unit-test approval" not in json.dumps(row)
    with pytest.raises(FileExistsError):
        freeze(teaching, evaluation, root, independent_owner_review=True)
    (root / "input/train.jsonl").write_bytes(dataset(teaching) + b"\n")
    with pytest.raises(ValueError, match="DECISION_DATASET"):
        load_job(root / "input")


@pytest.mark.parametrize(
    "change", ["pending", "revise", "evaluation", "overlap", "no_independence", "unseen"]
)
def test_invalid_reviews_or_leakage_fail_before_writing(tmp_path, change):
    teaching, evaluation = pack(), pack("evaluation")
    independent = True
    if change in {"pending", "revise"}:
        data = teaching.model_dump(mode="json")
        data["examples"][0]["review"]["status"] = change
        teaching = DecisionReviewPack.model_validate(data)
    if change == "evaluation":
        evaluation = pack("evaluation", approved=False)
    if change == "overlap":
        evaluation = evaluation.model_copy(
            update={"examples": [teaching.examples[0], *evaluation.examples[1:]]}
        )
    if change == "no_independence":
        independent = False
    if change == "unseen":
        evaluation = DecisionReviewPack(
            purpose="evaluation",
            system=SYSTEM,
            examples=[
                reviewed(e.model_copy(update={"domain": f"domain-{i % 3}"}))
                for i, e in enumerate(evaluation.examples)
            ],
        )
    with pytest.raises(ValueError):
        freeze(
            teaching, evaluation, tmp_path / "must-not-exist", independent_owner_review=independent
        )
    assert not (tmp_path / "must-not-exist").exists()


def test_approval_is_invalidated_by_case_label_or_origin_changes():
    example = pack().examples[0]
    for changes in (
        {"domain": "changed"},
        {"target": {"decision": "abstain"}},
        {"context": example.context.replace('"count": 0', '"count": 1')},
        {"origin": "OWNER_DRAFT"},
    ):
        data = {**example.model_dump(mode="json"), **changes}
        with pytest.raises(ValidationError, match="Approval"):
            DecisionExample.model_validate(data)
    for field in ("reviewer", "content_sha256"):
        data = example.model_dump(mode="json")
        data["review"][field] = None
        with pytest.raises(ValidationError):
            DecisionExample.model_validate(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"steps": 12},
        {"seconds": 7200},
        {"max_length": 4096},
        {"rank": 8},
        {"precision": "float16"},
        {"epochs": 9},
    ],
)
def test_recipe_cannot_silently_expand_or_reinterpret_existing_presets(changes):
    with pytest.raises(ValidationError):
        DecisionRecipe(**changes)


def test_drafts_and_unbalanced_targets_are_not_jobs():
    for supervision in (
        pack(approved=False),
        pack().model_copy(update={"examples": pack().examples[:44]}),
    ):
        with pytest.raises(ValidationError):
            DecisionJob(
                id=uuid4(),
                supervision=supervision,
                evaluation_sha256="a" * 64,
                dataset_sha256="b" * 64,
            )
    data = pack(approved=False).model_dump(mode="json")
    data["system"] += "another variant"
    with pytest.raises(ValidationError):
        DecisionReviewPack.model_validate(data)


def test_scores_include_all_failures_raw_counts_and_descriptive_uncertainty():
    suite = pack("evaluation")
    base = {str(e.id): '{"decision":"answer"}' for e in suite.examples}
    candidate = {str(e.id): e.target.model_dump_json() for e in suite.examples}
    result = score(suite, base, candidate)
    assert result["baseline"]["correct"] == 10
    assert result["candidate"]["correct"] == 30
    assert result["all_proposed_gates_passed"]
    assert result["automatic_promotion"] is False and result["advice_quality_evaluated"] is False
    assert result["candidate"]["unsupported_false_answer_wilson_95"][1] > 0.25
    unsupported = [e for e in suite.examples if e.target.decision == "abstain"]
    candidate[str(unsupported[0].id)] = '{"decision":"answer"}'
    candidate[str(unsupported[1].id)] = '{"decision":"answer","decision":"abstain"}'
    candidate[str(unsupported[2].id)] = None
    result = score(suite, base, candidate)
    assert result["candidate"]["total"] == 30 and result["candidate"]["invalid"] == 2
    assert result["candidate"]["confusion_matrix"]["abstain"] == dict(
        answer=1, clarify=0, abstain=7, invalid=2
    )
    assert result["all_proposed_gates_passed"] is False
    assert "not a general reliability guarantee" in result["uncertainty_note"]
    candidate.pop(str(unsupported[0].id))
    with pytest.raises(ValueError, match="every frozen case"):
        score(suite, base, candidate)
    assert wilson(0, 10)[1] > 0.25 and wilson(30, 30)[0] < 0.9


def test_cpu_command_cannot_acquire_gpu_or_mount_frozen_evaluation(tmp_path):
    for stage in ("cpu", "cpu-drafts"):
        args = command(
            stage,
            IMAGE,
            tmp_path / "base",
            tmp_path / "input",
            tmp_path / "output",
            "qm-decision-abcd",
        )
        text = " ".join(args)
        assert "--gpus" not in text and "/dev/dxg" not in text and "evaluation" not in text
        assert "--network=none" in args and "--memory=10g" in args
        assert args[-2:] == [IMAGE, stage]
    with pytest.raises(ValueError):
        command("cpu", "mutable:latest", tmp_path, tmp_path, tmp_path, "qm-decision-abcd")


def test_cpu_stage_has_durable_failure_and_no_automatic_retry(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    (root / "input").mkdir(parents=True)
    (root / "input/pack.json").write_text(pack(approved=False).model_dump_json())
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if args[1] == "run":
            raise subprocess.TimeoutExpired(args, 330)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", execute)
    with pytest.raises(subprocess.TimeoutExpired):
        run_stage(root, tmp_path / "base", IMAGE, "cpu-drafts")
    assert (root / "output/cpu-drafts/failed.json").exists()
    assert not (root / "output/cpu-drafts/completed.json").exists()
    with pytest.raises(FileExistsError):
        run_stage(root, tmp_path / "base", IMAGE, "cpu-drafts")
    assert len(calls) == 2 and calls[1][:3] == ["docker", "rm", "-f"]


def test_gpu_stages_refuse_drafts_and_absent_command_approval(tmp_path, monkeypatch):
    teaching, suite = pack(), pack("evaluation")
    root = tmp_path / "bundle"
    freeze(teaching, suite, root, independent_owner_review=True)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: pytest.fail("No GPU or Docker call authorized")
    )
    for stage in ("gpu-preflight", "train"):
        with pytest.raises(ValueError, match="DECISION_GPU_AUTH"):
            run_stage(root, tmp_path / "base", IMAGE, stage)
    assert not (root / "output").exists()
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps(dict(approved=True, reviewer="owner", job_sha256="0" * 64, commands={}))
    )
    with pytest.raises(ValueError, match="does not bind"):
        run_stage(root, tmp_path / "base", IMAGE, "train", run_gpu=True, authorization=auth)


def test_context_duplicate_keys_extra_fields_and_nonfinite_values_are_refused():
    example = pack(approved=False).examples[0]
    for context in (
        example.context.replace('"count": 0', '"count":0,"count":1'),
        example.context.replace('"count": 0', '"count":NaN'),
        example.context[:-1] + ',"observed_outcome":"do not send"}',
    ):
        with pytest.raises(ValidationError):
            DecisionExample.model_validate({**example.model_dump(mode="json"), "context": context})


def test_mutating_an_approved_nested_model_does_not_bypass_freeze_review(tmp_path):
    teaching = pack()
    changed = teaching.examples[0].model_copy(update={"domain": "changed after approval"})
    teaching = teaching.model_copy(update={"examples": [changed, *teaching.examples[1:]]})
    with pytest.raises(ValidationError, match="Approval"):
        freeze(teaching, pack("evaluation"), tmp_path / "no", independent_owner_review=True)
    assert not (tmp_path / "no").exists()


def test_host_refuses_modified_frozen_evaluation_before_execution(tmp_path):
    root = tmp_path / "job"
    job = freeze(pack(), pack("evaluation"), root, independent_owner_review=True)
    checked_bundle(root, job)
    (root / "evaluation.json").write_text((root / "evaluation.json").read_text() + "\n")
    with pytest.raises(ValueError, match="DECISION_FREEZE"):
        checked_bundle(root, job)
    (root / "input/evaluation.json").write_text("not permitted in trainer mount")
    with pytest.raises(ValueError, match="Mount only"):
        load_job(root / "input")


def test_cpu_cleanup_failure_blocks_completion(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    (root / "input").mkdir(parents=True)
    path = root / "input/pack.json"
    path.write_text(pack(approved=False).model_dump_json())
    sha = hashlib.sha256(path.read_bytes()).hexdigest()

    def execute(args, **kwargs):
        if args[1] == "run":
            report = root / "output/cpu-drafts/cpu-preflight.json"
            report.write_text(
                json.dumps(
                    dict(input_sha256=sha, training_started=False, gpu_capability_checked=False)
                )
            )
            assert kwargs["timeout"] == 330
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(subprocess, "run", execute)
    run_stage(root, tmp_path, IMAGE, "cpu-drafts")
    assert (root / "output/cpu-drafts/cleanup-required.json").exists()
    assert not (root / "output/cpu-drafts/completed.json").exists()


def test_container_tokenization_preserves_exact_prompt_and_blocks_overlength(monkeypatch):
    trainer = Path(__file__).resolve().parents[1] / "trainer"
    monkeypatch.syspath_prepend(str(trainer))
    spec = importlib.util.spec_from_file_location(
        "selector_container_worker", trainer / "decision_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = [json.loads(line) for line in dataset(pack(approved=False)).splitlines()]

    class Tokenizer:
        eos_token = "<|im_end|>"

        def apply_chat_template(self, messages, **kwargs):
            assert kwargs == dict(tokenize=False, add_generation_prompt=True, enable_thinking=False)
            return messages[0]["content"] + messages[1]["content"]

        def __call__(self, value, **kwargs):
            assert kwargs == {"add_special_tokens": False}
            return {"input_ids": list(range(100))}

    data, diagnostics = module.tokenized_rows(rows, Tokenizer())
    assert len(data) == len(diagnostics) == 45
    assert (
        data[0]["prompt"] == rows[0]["messages"][0]["content"] + rows[0]["messages"][1]["content"]
    )
    assert data[0]["completion"] == rows[0]["messages"][2]["content"] + "<|im_end|>"
    monkeypatch.setattr(Tokenizer, "__call__", lambda *a, **kw: {"input_ids": [0] * 2049})
    with pytest.raises(ValueError, match="DECISION_SEQUENCE_LENGTH"):
        module.tokenized_rows(rows, Tokenizer())
    expected = dict(
        max_steps=120,
        max_length=2048,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=1,
        learning_rate=1e-5,
        seed=17,
        fp16=False,
        bf16=False,
        completion_only_loss=True,
        use_cpu=True,
    )
    monkeypatch.setattr(module, "training_args", lambda *a, **kw: SimpleNamespace(**expected))
    assert module.cpu_recipe_check(Path("/unused")) == expected
    expected["max_steps"] = 12
    with pytest.raises(ValueError, match="DECISION_RECIPE_DRIFT"):
        module.cpu_recipe_check(Path("/unused"))
