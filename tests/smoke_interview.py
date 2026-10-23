"""Opt-in stdlib HTTP smoke in a disposable web container; never a real provider.

Start the container with QM_BUILDER_BASE_URL=http://127.0.0.1:8091/v1 and
QM_BUILDER_MODEL=synthetic-smoke. Pipe this script into docker exec -i ... python -.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = "http://127.0.0.1:8000"
CALLS = []
ANSWERS = {
    "mission": "Advise on rental-tool use.",
    "business_goal": "Support safe use without a business-lift claim.",
    "available_choices": "Recommend use, withhold use or ask for missing facts.",
    "target_behavior": "Require current inspection and no damage; ask if unknown.",
    "case_grain": "One tool request.",
    "decision_inputs": "Inspection and damage before use. Later incidents are outcomes.",
    "success_and_harm": "Record later incidents separately; owner preference is not proof.",
}
INTERPRETATION = {
    "name": "Synthetic interview smoke",
    "mission": ANSWERS["mission"],
    "business_goal": ANSWERS["business_goal"],
    "decision_definition": {
        k: v for k, v in ANSWERS.items() if k not in {"mission", "business_goal"}
    },
}


class FakeProvider(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(body)
        assert body["model"] == "synthetic-smoke"
        assert body["store"] is False and body["max_completion_tokens"] == 2048
        assert body["response_format"]["json_schema"]["strict"] is True
        schema_name = body["response_format"]["json_schema"]["name"]
        content = json.dumps({"ok": True} if schema_name == "Probe" else INTERPRETATION)
        if len(CALLS) == 2:
            content = "deliberately invalid JSON"
        result = json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(result)))
        self.end_headers()
        self.wfile.write(result)


def request(path, payload=None, expected=200):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "Origin": BASE}
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        raw = response.read()
        assert response.status == expected, (response.status, raw[:300])
        return (
            json.loads(raw)
            if response.headers.get("Content-Type", "").startswith("application/json")
            else raw.decode()
        )


def main():
    server = HTTPServer(("127.0.0.1", 8091), FakeProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert request("/healthz")["status"] == "ok"
        project = request("/api/projects", {"name": "Synthetic interview", "mission": "Help"}, 201)[
            "id"
        ]
        root = f"/api/projects/{project}"
        path = root + "/interview"
        assert "Define your adviser" in request(f"/projects/{project}/interview")
        assert not CALLS
        state = request(path)
        for topic, answer in ANSWERS.items():
            state = request(
                path + "/answers",
                {"expected_revision": state["revision"], "topic": topic, "answer": answer},
            )
        state = request(path + "/manual", {"expected_revision": state["revision"]})
        assert state["proposal_origin"] == "OWNER_DRAFT"
        state = request(
            path + "/review", {"expected_revision": state["revision"], "action": "reject"}
        )
        assert request(root)["revision"] == 1
        assert not CALLS
        assert request("/api/builder/test", {"consent": True})["status"] == "ok"
        assert len(CALLS) == 1
        for outcome in ("failed", "review"):
            state = request(path + "/prepare", {"expected_revision": state["revision"]})
            context = state["prepared"]["context"]
            assert len(CALLS) == (1 if outcome == "failed" else 2)
            consent = {
                "expected_revision": state["revision"],
                "turn_id": state["prepared"]["id"],
                "disclosure_sha256": state["prepared"]["disclosure_sha256"],
                "consent": True,
            }
            request(path + "/send", {**consent, "consent": False}, 422)
            state = request(path + "/send", consent)
            assert state["status"] == outcome and state["answers"] == ANSWERS
            assert CALLS[-1]["messages"][1]["content"] == context
            request(path + "/send", consent, 409)
            assert request(root)["revision"] == 1
            if outcome == "failed":
                assert "BUILDER_JSON" in state["error"]
        assert state["proposal_origin"] == "AI_DRAFT"
        assert "Full proposed spec" in request(f"/projects/{project}/interview")
        edited = {**INTERPRETATION, "mission": "Owner-reviewed synthetic mission"}
        state = request(
            path + "/review",
            {"expected_revision": state["revision"], "action": "apply", "edited": edited},
        )
        assert state["status"] == "applied" and state["readiness"] == "needs_examples"
        spec = request(root)
        assert spec["revision"] == 2 and spec["mission"] == edited["mission"]
        assert spec["model"]["adapter_artifact"] is None
        assert len(request(root + "/revisions")) == 2
        assert len(request(path + "/revisions")) == 16
        assert "Reviewed decision definition" in request(f"/projects/{project}")
        print(
            json.dumps(
                {
                    "result": "passed",
                    "provider_requests": len(CALLS),
                    "provider": "local synthetic HTTP fake",
                    "network": "none",
                    "manual_and_AI_review": True,
                    "invalid_JSON_recovery": True,
                }
            )
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
