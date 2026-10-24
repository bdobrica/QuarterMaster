"""Opt-in: real local CPU model via a fresh web container. Synthetic cases only."""

import json
import time
import urllib.request

ROOT = "http://127.0.0.1:8000"


def request(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        ROOT + path, data=data, headers={"Origin": ROOT, "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.loads(response.read())


def main():
    project = request(
        "/api/projects",
        {
            "name": "Synthetic real CPU check",
            "mission": (
                "Advise on rental tool use. Use only when inspection is current and no damage "
                "is reported. If either fact is missing, ask for it before deciding."
            ),
        },
    )["id"]
    base = f"/api/projects/{project}"
    report = []
    for name, situation in [
        ("complete", "Drill: inspection is current; no damage is reported. May it be used?"),
        ("missing", "Sander: inspection is current. Damage status is unknown. May it be used?"),
    ]:
        start = time.monotonic()
        run = request(base + "/tests", {"situation": situation})
        report.append(
            {
                "case": name,
                "seconds": round(time.monotonic() - start, 2),
                "error": run["error"],
                "advice": run["advice"],
                "supporting_quotes": run["draft"]["supporting_quotes"] if run["draft"] else None,
                "clarification_expected": name == "missing",
                "clarification_matches": bool(
                    run["advice"] and run["advice"]["clarification_question"]
                )
                == (name == "missing"),
            }
        )
        print(json.dumps(report[-1]), flush=True)
        assert run["error"] is None and run["advice"] is not None
        if name == "missing":
            assert run["advice"]["clarification_question"]
            assert run["advice"]["recommendation"].startswith("Withhold")
            assert "damage" in run["advice"]["clarification_question"].casefold()
        else:
            # Over-asking is a recorded rubric miss, not a schema/transport failure.
            assert run["draft"]["behavior"] in {"recommend", "clarify", "abstain"}
    print(
        "Real CPU structured advice and missing-information checks passed. Rubric matches: "
        + str([row["clarification_matches"] for row in report]),
        flush=True,
    )


if __name__ == "__main__":
    main()
