"""Project-scoped exclusion shared by teaching and future dataset/prompt selection."""

import hashlib
import json
import unicodedata

from quartermaster.errors import DomainError


def case_fingerprint(case):
    # Ignore IDs, outcomes, casing and whitespace so a copied test cannot evade holdout.
    def normalized(text):
        return " ".join(unicodedata.normalize("NFKC", text).casefold().split())

    value = {
        "situation": normalized(case.situation),
        "choices": sorted(map(normalized, case.choices)),
    }
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def require_eligible(connection, project_id, cases):
    """Call inside the write transaction at selection AND dataset freeze in M6.

    Also applies before builder example/lesson prompts. No fuzzy similarity claim.
    """
    held = connection.execute(
        "SELECT case_id, case_sha256 FROM evaluation_holdouts WHERE project_id=?",
        (str(project_id),),
    ).fetchall()
    ids, hashes = {row[0] for row in held}, {row[1] for row in held}
    if any(str(case.case_id) in ids or case_fingerprint(case) in hashes for case in cases):
        raise DomainError(
            "EVALUATION_HELD_OUT: This situation is reserved for evaluation; "
            "use a different teaching example. It cannot enter training or builder lesson prompts.",
            409,
        )
