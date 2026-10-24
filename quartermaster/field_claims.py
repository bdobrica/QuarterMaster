"""Exact checks on explicit claims, never keyword-based certification of adviser prose."""

from quartermaster.contracts.reliability import FieldClaimCheck, FieldClaims, ReliabilityRun


def check_claims(run: ReliabilityRun, action: FieldClaims) -> FieldClaimCheck:
    facts = {fact.field: fact for fact in run.interpretations}
    results = []
    for claim in action.claims:
        fact = facts.get(claim.field)
        mismatches = []
        if fact is None:
            mismatches.append("unconfigured_field")
        else:
            for key in ("state", "value", "unit", "citation_id"):
                actual, asserted = getattr(fact, key), getattr(claim, key)
                if actual != asserted or type(actual) is not type(asserted):
                    mismatches.append(key)
        results.append({"field": claim.field, "matches": not mismatches, "mismatches": mismatches})
    return FieldClaimCheck(
        run_id=run.id,
        rules_sha256=run.rules_sha256,
        all_claims_match=all(result["matches"] for result in results),
        results=results,
    )
