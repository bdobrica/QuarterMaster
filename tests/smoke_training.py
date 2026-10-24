"""Pipe into an isolated production web container; synthetic local API flow, no GPU."""

import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from quartermaster.inference import model_alias

ROOT = "http://127.0.0.1:8000"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, value):
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond({"data": [{"id": model_alias("a" * 64)}]})

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        context = json.loads(payload["messages"][1]["content"])
        assert "observed_outcome" not in context["case"]
        self.respond(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "missing_information": [],
                                    "behavior": "recommend",
                                    "supporting_quotes": [context["case"]["situation"]],
                                    "advice": {
                                        "recommendation": "Synthetic API fixture advice.",
                                        "explanation": "Supplied facts.",
                                        "evidence_refs": [],
                                        "clarification_question": None,
                                        "limitations": [],
                                    },
                                }
                            )
                        },
                    }
                ]
            }
        )


def request(path, body=None):
    headers = {"Content-Type": "application/json"}
    response = urllib.request.urlopen(
        urllib.request.Request(
            ROOT + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
        ),
        timeout=10,
    )
    data = response.read()
    return (
        json.loads(data)
        if response.headers["Content-Type"].startswith("application/json")
        else data.decode()
    )


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8092), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    project = request(
        "/api/projects", {"name": "Synthetic M6 smoke", "mission": "Ask for missing safety facts."}
    )["id"]
    api = f"/api/projects/{project}"
    original = request(
        api + "/tests", {"situation": "Compressor safety guard condition is unknown."}
    )
    lesson = request(
        api + f"/tests/{original['id']}/feedback",
        {"category": "should_ask", "correction": "Ask whether the guard is intact."},
    )
    lesson = request(
        api + f"/lessons/{lesson['id']}/manual",
        {
            "expected_revision": lesson["revision"],
            "text": {
                "applicability": "Compressor safety decisions",
                "instruction": "Ask whether the guard is intact before recommending use.",
            },
        },
    )
    lesson = request(
        api + f"/lessons/{lesson['id']}/review",
        {"expected_revision": lesson["revision"], "action": "apply"},
    )
    example = request(
        api + f"/lessons/{lesson['id']}/training-example", {"expected_revision": lesson["revision"]}
    )
    example = request(
        api + f"/training-examples/{example['id']}/target",
        {
            "expected_revision": example["revision"],
            "target": {
                "behavior": "clarify",
                "missing_information": ["guard condition"],
                "supporting_quotes": [],
                "advice": {
                    "recommendation": "Withhold a decision.",
                    "explanation": "Guard condition is missing.",
                    "evidence_refs": [],
                    "clarification_question": "Is the guard intact?",
                    "limitations": ["Missing guard status."],
                },
            },
        },
    )
    example = request(
        api + f"/training-examples/{example['id']}/review",
        {"expected_revision": example["revision"], "action": "approve"},
    )
    assert example["status"] == "approved"
    unseen = request(
        api + "/tests", {"situation": "A workshop fan has an unknown electrical inspection date."}
    )
    suite = request(api + "/evaluation-suites", {"name": "Unseen fan"})
    suite = request(
        api + f"/evaluation-suites/{suite['id']}/cases",
        {
            "expected_revision": suite["revision"],
            "test_id": unseen["id"],
            "rubric": {
                "expected_behavior": "clarify",
                "expectation": "Ask for electrical inspection status.",
            },
        },
    )
    suite = request(
        api + f"/evaluation-suites/{suite['id']}/freeze", {"expected_revision": suite["revision"]}
    )
    before = request(api)
    run = request(
        api + "/training-runs",
        {
            "example_ids": [example["id"]],
            "suite_id": suite["id"],
            "suite_revision": suite["revision"],
            "preset": "quick",
            "acknowledge_small_data": True,
        },
    )
    assert run["status"] == "queued"
    job = request(api + f"/training-runs/{run['id']}/job")
    assert job["examples"][0]["status"] == "approved" and job["holdout_ids"]
    assert len(request(api + f"/training-runs/{run['id']}/dataset").splitlines()) == 1
    canceled = request(
        api + f"/training-runs/{run['id']}/cancel", {"expected_revision": run["revision"]}
    )
    assert canceled["status"] == "canceled" and request(api) == before
    page = request(f"/projects/{project}/train")
    assert "Five examples do not ensure quality" in page and "canceled" in page
    assert request(api + "/adviser-versions") == []
    print(
        json.dumps(
            {
                "synthetic": True,
                "reviewed_examples": 1,
                "queued_then_canceled": True,
                "gpu_or_builder_calls": 0,
                "active_unchanged": True,
            }
        )
    )
    server.shutdown()


if __name__ == "__main__":
    main()
