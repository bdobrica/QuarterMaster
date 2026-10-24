"""Pipe into a fresh web container. Synthetic cases only; no builder provider.

Default: network-isolated loopback fake server. --live: existing pinned local CPU
server configured by the operator; record behavior checks without asserting quality.
"""

import json
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from quartermaster.inference import model_alias

ROOT = "http://127.0.0.1:8000"
CALLS = []


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
        assert self.path == "/v1/models"
        self.respond({"data": [{"id": model_alias("a" * 64)}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        context = json.loads(body["messages"][1]["content"])
        assert "observed_outcome" not in context["case"] and "rubric" not in context
        CALLS.append(context)
        ask = "mission" in context and "unknown" in context["case"]["situation"]
        content = {
            "missing_information": ["damage status"] if ask else [],
            "behavior": "clarify" if ask else "recommend",
            "supporting_quotes": [] if ask else [context["case"]["situation"]],
            "advice": {
                "recommendation": "May use subject to normal checks.",
                "explanation": "Based on the supplied facts.",
                "evidence_refs": [],
                "clarification_question": "Is damage reported?" if ask else None,
                "limitations": [],
            },
        }
        self.respond(
            {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}
        )


def request(path, body=None, *, form=False):
    headers = {"Origin": ROOT}
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    with urllib.request.urlopen(
        urllib.request.Request(ROOT + path, data=data, headers=headers), timeout=600
    ) as response:
        raw = response.read().decode()
        return json.loads(raw) if response.headers.get_content_type() == "application/json" else raw


def main():
    live = "--live" in sys.argv
    server = None
    if not live:
        server = ThreadingHTTPServer(("127.0.0.1", 8092), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        pid = request(
            "/api/projects",
            {
                "name": "Synthetic M5 smoke",
                "mission": (
                    "Advise on tool use. Require a current inspection and "
                    "no reported damage; ask for missing facts."
                ),
            },
        )["id"]
        api, ui = f"/api/projects/{pid}", f"/projects/{pid}"
        original = request(api)
        request(ui + "/evaluation-suites", {"name": "<script>holdouts</script>"}, form=True)
        suite = request(api + "/evaluation-suites")[0]
        situations = [
            "A drill has a current inspection and no reported damage.",
            "A sander has a current inspection. Damage status is unknown.",
        ]
        for situation, expected in zip(situations, ["recommend", "clarify"], strict=True):
            request(ui + "/test", {"situation": situation}, form=True)
            test = request(api + "/tests")[0]
            assert "Save as evaluation case" in request(ui + "/test")
            request(
                ui + f"/evaluation-suites/{suite['id']}/cases",
                {
                    "expected_revision": suite["revision"],
                    "test_id": test["id"],
                    "expected_behavior": expected,
                    "expectation": (
                        "Follow the inspection and damage rule. "
                        "Owner-authored software-test rubric."
                    ),
                },
                form=True,
            )
            suite = request(api + "/evaluation-suites")[0]
            try:
                request(
                    api + f"/tests/{test['id']}/feedback",
                    {"category": "wrong_call", "correction": "Do not teach from a holdout"},
                )
                raise AssertionError("holdout accepted for teaching")
            except urllib.error.HTTPError as exc:
                assert exc.code == (409 if test["advice"] else 422)
            assert "Held out for evaluation" in request(ui + "/test")
        request(
            ui + f"/evaluation-suites/{suite['id']}/freeze",
            {"expected_revision": suite["revision"]},
            form=True,
        )
        suite = request(api + "/evaluation-suites")[0]
        html = request(
            ui + f"/evaluation-suites/{suite['id']}/run",
            {"expected_revision": suite["revision"]},
            form=True,
        )
        run = request(api + "/evaluation-runs")[0]
        assert run["status"] == "completed" and len(run["outputs"]) == 4
        assert "A · Base only" in html and "B · Base plus context" in html
        assert (
            "&lt;script&gt;holdouts&lt;/script&gt;" in html
            and "<script>holdouts</script>" not in html
        )
        assert "2 unreviewed" in html
        for entry, preference in zip(suite["cases"], ["a_better", "b_better"], strict=True):
            request(
                ui + f"/evaluation-runs/{run['id']}/ratings/{entry['id']}",
                {
                    "expected_revision": 0,
                    "preference": preference,
                    "category": "should_ask",
                    "rationale": (
                        "Synthetic UI workflow preference only; no business outcome measured."
                    ),
                },
                form=True,
            )
        html = request(ui + f"/evaluations?run_id={run['id']}")
        assert "1 improved · 1 regressed" in html and "0 unreviewed" in html
        assert request(api) == original
        assert request(api + "/lessons") == []
        assert not run["weight_improvement_assessed"]
        if not live:
            assert len(CALLS) == 6
            assert all(o["error"] is None for o in run["outputs"])
            assert run["outputs"][2]["checks"]["expected_behavior_passed"] is False
            assert run["outputs"][3]["checks"]["expected_behavior_passed"] is True
        print(
            json.dumps(
                {
                    "check": "milestone-5-http",
                    "live_local_cpu": live,
                    "cases": 2,
                    "outputs": 4,
                    "builder_calls": 0,
                    "checks": [
                        {"variant": o["variant"], "error": o["error"], "checks": o["checks"]}
                        for o in run["outputs"]
                    ],
                    "active_adviser_unchanged": True,
                    "weights_unchanged": True,
                }
            )
        )
    finally:
        if server:
            server.shutdown()
            server.server_close()


main()
