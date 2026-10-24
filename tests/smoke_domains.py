"""Opt-in real CPU demo. Uses isolated synthetic data; never queues training or labels SFT."""

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from quartermaster.app import create_app
from quartermaster.config import Settings


def run(config, domain=None):
    if config.data_dir.exists() and any(config.data_dir.iterdir()):
        raise ValueError("Choose a new, empty data directory; existing projects are never touched")
    root = Path(__file__).parents[1] / "quartermaster/ui/static/examples"
    results = []
    with TestClient(create_app(config)) as client:
        # A live check must not apply fixture lessons inside an owner's existing projects.
        assert client.get("/api/projects").json() == [], "Choose a new, empty data directory"

        def call(path, body=None):
            response = client.get(path) if body is None else client.post(path, json=body)
            assert response.status_code in {200, 201}, response.text
            return response.json()

        scenarios = [
            p
            for p in sorted(root.glob("*/scenario.json"))
            if domain is None or p.parent.name == domain
        ]
        assert scenarios, "Choose an included synthetic domain"
        for scenario_file in scenarios:
            scenario = json.loads(scenario_file.read_text())
            project = call(
                "/api/projects",
                {key: scenario[key] for key in ("name", "mission", "business_goal")},
            )["id"]
            api = f"/api/projects/{project}"
            for filename, label in [
                ("observations.csv", "observations"),
                ("knowledge.md", "knowledge"),
            ]:
                response = client.post(
                    api + "/sources",
                    files={"file": (filename, (scenario_file.parent / filename).read_bytes())},
                    data={"label": label, "encoding": "utf-8-sig", "delimiter": ","},
                    headers={"Origin": "http://testserver"},
                )
                assert response.status_code == 201, response.text
                source = response.json()
                if label == "knowledge":
                    call(
                        api + "/knowledge",
                        {"source_ids": [source["id"]], "expected_revision": None},
                    )
                else:

                    def field(name, source_id=source["id"]):
                        return {"source_id": source_id, "sheet": "CSV", "field": name}

                    call(
                        api + "/mappings",
                        {
                            "primary": {"source_id": source["id"], "sheet": "CSV"},
                            "grain": scenario["grain"],
                            "decision_time": scenario["decision_time"],
                            "inputs": [field(name) for name in scenario["inputs"]],
                            "outcomes": [field(name) for name in scenario["outcomes"]],
                            "targets": [],
                            "confirmed": True,
                            "inputs_available_at_decision": True,
                        },
                    )
            state = call(api + "/interview")
            for topic in state["answers"]:
                state = call(
                    api + "/interview/answers",
                    {
                        "expected_revision": state["revision"],
                        "topic": topic,
                        "answer": scenario["grain"] if topic == "case_grain" else scenario[topic],
                    },
                )
            state = call(api + "/interview/manual", {"expected_revision": state["revision"]})
            call(
                api + "/interview/review",
                {"expected_revision": state["revision"], "action": "apply"},
            )
            before = call(api)
            print(json.dumps({"stage": "baseline", "domain": scenario["id"]}), flush=True)
            baseline = call(api + "/tests", {"situation": scenario["baseline"]})
            applied = False
            if baseline["advice"]:
                lesson = call(
                    api + f"/tests/{baseline['id']}/feedback",
                    {
                        "category": "good"
                        if baseline["advice"]["clarification_question"]
                        else "should_ask",
                        "correction": (
                            "AI-drafted synthetic SOFTWARE TEST fixture; no real outcome: "
                            + scenario["correction"]
                        ),
                    },
                )
                path = api + f"/lessons/{lesson['id']}"
                lesson = call(
                    path + "/manual",
                    {"expected_revision": lesson["revision"], "text": scenario["lesson"]},
                )
                lesson = call(
                    path + "/review", {"expected_revision": lesson["revision"], "action": "apply"}
                )
                applied = lesson["status"] == "applied"
            print(json.dumps({"stage": "unseen", "domain": scenario["id"]}), flush=True)
            unseen = call(api + "/tests", {"situation": scenario["unseen"]})
            suite = call(api + "/evaluation-suites", {"name": "Synthetic M8 unseen holdout"})
            holdout = call(api + "/tests", {"situation": scenario["holdout"]})
            path = api + f"/evaluation-suites/{suite['id']}"
            suite = call(
                path + "/cases",
                {
                    "expected_revision": suite["revision"],
                    "test_id": holdout["id"],
                    "rubric": {
                        "expected_behavior": "clarify",
                        "expectation": scenario["holdout_question"],
                    },
                },
            )
            suite = call(path + "/freeze", {"expected_revision": suite["revision"]})
            print(json.dumps({"stage": "evaluate", "domain": scenario["id"]}), flush=True)
            evaluation = call(path + "/run", {"expected_revision": suite["revision"]})
            after = call(api)
            assert before["model"] == after["model"]
            assert call(api + "/training-examples") == [] and call(api + "/training-runs") == []
            for item in suite["inputs"]:
                for arm in ("a", "b"):
                    assert "observed_outcome" not in json.loads(item[arm]["context"])["case"]
                    assert "rubric" not in json.loads(item[arm]["context"])
            results.append(
                {
                    "domain": scenario["id"],
                    "project_id": project,
                    "synthetic_test_only": True,
                    "fixture_lesson_applied": applied,
                    "baseline": baseline,
                    "unseen": unseen,
                    "holdout": holdout,
                    "suite": suite,
                    "evaluation": evaluation,
                    "weights_unchanged": True,
                    "sft_examples": 0,
                    "gpu_jobs": 0,
                }
            )
            (config.data_dir / "verification.json").write_text(json.dumps(results, indent=2))
            print(
                json.dumps(
                    {
                        "stage": "completed",
                        "domain": scenario["id"],
                        "lesson_in_unseen_context": bool(unseen["lessons"]),
                        "evaluation_status": evaluation["status"],
                        "test_errors": [r["error"] for r in (baseline, unseen, holdout)],
                    }
                ),
                flush=True,
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--domain", help="Optional included scenario directory name")
    args = parser.parse_args()
    run(
        Settings(
            data_dir=args.data_dir,
            local_base_url=args.base_url,
            local_model_sha256=args.model_sha256,
            _env_file=None,
        ),
        domain=args.domain,
    )


if __name__ == "__main__":
    main()
