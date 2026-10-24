"""Project-scoped exclusion shared by teaching and future dataset/prompt selection."""

import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher

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
    # A conservative lexical guard, not semantic paraphrase detection. Fetch only
    # decision-time cases; targets, rubrics and outcomes never become prompt context.
    rows = connection.execute(
        "SELECT t.document FROM test_runs t JOIN evaluation_holdouts h "
        "ON t.id=h.test_id WHERE h.project_id=?",
        (str(project_id),),
    ).fetchall()
    from quartermaster.contracts.teaching import TestRun

    reserved = [TestRun.model_validate_json(row[0]).case for row in rows]
    if any(near_duplicate(case, other) for case in cases for other in reserved):
        raise DomainError(
            "EVALUATION_NEAR_DUPLICATE: This case is too similar to a holdout. "
            "Use a distinct teaching situation.",
            409,
        )


def near_duplicate(first, second):
    def tokens(case):
        text = unicodedata.normalize("NFKC", case.situation).casefold()
        return re.findall(r"\w+", text)

    a, b = tokens(first), tokens(second)
    if not a or not b:
        return False
    # Preserve order and compare token sets to catch minor edits and reordered copies.
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.9 or (
        len(set(a) & set(b)) / len(set(a) | set(b)) >= 0.9
    )
