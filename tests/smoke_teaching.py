"""Run by piping into a fresh web container; only synthetic loopback model servers."""

import json
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from quartermaster.contracts.teaching import GroundedAdvice
from quartermaster.inference import model_alias

ROOT = "http://127.0.0.1:8000"
SHA = "a" * 64
CALLS = {"advice": 0, "builder": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, value):
        data = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        assert self.path == "/v1/models"
        self.respond({"data": [{"id": model_alias(SHA)}]})

    def do_POST(self):
        assert self.path == "/v1/chat/completions"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        context = json.loads(body["messages"][1]["content"])
        if self.server.server_port == 8091:
            CALLS["builder"] += 1
            assert "observed_outcome" not in context["case"]
            assert "retrieved_evidence" not in context
            content = {
                "applicability": "Tool advice when damage status is missing",
                "instruction": "Ask about damage before advising on tool use.",
            }
        else:
            CALLS["advice"] += 1
            learned = bool(context["approved_lessons"])
            content = {
                "behavior": "clarify" if learned else "recommend",
                "advice": {
                    "schema_version": "quartermaster.advice/v1",
                    "recommendation": "May use subject to checks.",
                    "explanation": "Based on supplied inspection status.",
                    "evidence_refs": [],
                    "clarification_question": "Any damage?" if learned else None,
                    "limitations": [],
                },
                "supporting_quotes": [context["case"]["situation"]],
                "missing_information": ["damage status"] if learned else [],
            }
            GroundedAdvice.model_validate(content)
        self.respond(
            {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(content)}}]}
        )


def request(path, body=None, *, form=False):
    headers = {"Origin": ROOT}
    if form:
        data = urllib.parse.urlencode(body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    else:
        data = None
    req = urllib.request.Request(ROOT + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode()
        return json.loads(raw) if response.headers.get_content_type() == "application/json" else raw


def main():
    servers = [ThreadingHTTPServer(("127.0.0.1", port), Handler) for port in (8091, 8092)]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert request("/healthz")["status"] == "ok"
        project = request(
            "/api/projects", {"name": "Synthetic M4 smoke", "mission": "Advise on rental tools."}
        )["id"]
        base = f"/api/projects/{project}"
        htmlbase = f"/projects/{project}"
        assert "Test advice and teach a lesson" in request(htmlbase)
        request(htmlbase + "/test", {"situation": "Drill inspection is current."}, form=True)
        run = request(base + "/tests")[0]
        assert run["advice"] and not run["lessons"]
        correction = "  Ask about damage first.\nPreserve this text.  "
        request(
            htmlbase + f"/tests/{run['id']}/feedback",
            {"category": "should_ask", "correction": correction},
            form=True,
        )
        lesson = request(base + "/lessons")[0]
        assert request(base + f"/feedback/{lesson['feedback_id']}")["correction"] == correction
        prefix = htmlbase + f"/lessons/{lesson['id']}"
        request(prefix + "/prepare", {"expected_revision": lesson["revision"]}, form=True)
        lesson = request(base + "/lessons")[0]
        assert CALLS["builder"] == 0
        html = request(htmlbase + "/test")
        assert "Business context" in html and "consent" in html
        request(
            prefix + "/send",
            {
                "expected_revision": lesson["revision"],
                "turn_id": lesson["id"],
                "disclosure_sha256": lesson["disclosure"]["disclosure_sha256"],
                "consent": "yes",
            },
            form=True,
        )
        lesson = request(base + "/lessons")[0]
        assert lesson["origin"] == "AI_DRAFT" and lesson["status"] == "pending"
        before = request(base + "/tests", {"situation": "Sander inspection is current."})
        assert before["lessons"] == []
        request(
            prefix + "/review",
            {
                "expected_revision": lesson["revision"],
                "action": "apply",
                "applicability": lesson["text"]["applicability"],
                "instruction": lesson["text"]["instruction"],
            },
            form=True,
        )
        after = request(base + "/tests", {"situation": "Mixer inspection is current."})
        assert after["lessons"] and after["advice"]["clarification_question"]
        assert after["advice"]["recommendation"].startswith("Withhold")
        assert after["adviser"]["model"] == run["adviser"]["model"]
        # Manual draft and rejection exercise the offline forms and HTML escaping.
        rejected = request(
            base + f"/tests/{after['id']}/feedback",
            {"category": "weak_explanation", "correction": "<script>untrusted correction</script>"},
        )
        prefix = htmlbase + f"/lessons/{rejected['id']}"
        request(
            prefix + "/manual",
            {
                "expected_revision": rejected["revision"],
                "applicability": "All situations",
                "instruction": "Ask first.",
            },
            form=True,
        )
        rejected = request(base + "/lessons")[-1]
        request(
            prefix + "/review",
            {"expected_revision": rejected["revision"], "action": "reject"},
            form=True,
        )
        html = request(htmlbase + "/test")
        assert "&lt;script&gt;untrusted correction&lt;/script&gt;" in html
        assert "context, not model weights" in html and "Clarification needed" in html
        assert request(base + f"/tests/{run['id']}") == run
        assert CALLS == {"advice": 3, "builder": 1}
        print(
            "M4 fresh-container HTTP smoke passed: baseline, exact consent, pending exclusion, "
            "edited approval, unseen retest, manual rejection, escaping and unchanged snapshots."
        )
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
