"""Exact, owner-configured scalar interpretation. No inference, code or domain defaults."""

import re

from quartermaster.contracts.reliability import FieldInterpretation
from quartermaster.errors import DomainError


def interpret(values, rules, evidence):
    """Validate every rule's attribution before interpreting any value.

    A verbatim quote establishes provenance, not semantic truth of the owner's rule.
    No cross-field repair, fuzzy matching, case folding or unknown-to-negative coercion.
    """
    excerpts = {item.citation_id: item.text for item in evidence}
    for rule in rules.rules:
        if rule.citation_id not in excerpts or rule.source_quote not in excerpts[rule.citation_id]:
            raise DomainError(
                "FIELD_RULE_SOURCE: Link each definition to an accessible verbatim excerpt."
            )
    results = []
    for rule in rules.rules:
        raw = values.get(rule.field)
        value, unit = None, None
        if rule.field not in values:
            state, meaning = "absent", "Field was not supplied."
        elif raw is None or raw == "":
            state, meaning = "missing", "Field was supplied without a value."
        elif raw in rule.unknown_values:
            state, meaning = "unknown", "Value is explicitly unknown; no negative fact established."
        elif raw in rule.sentinels:
            state, meaning = "sentinel", rule.sentinels[raw]
        elif rule.kind == "integer" and re.fullmatch(r"[0-9]{1,12}", raw):
            state, meaning, value, unit = "value", rule.definition, int(raw), rule.unit
        elif rule.kind == "category" and raw in rule.categories:
            state, meaning, value = "value", rule.categories[raw], raw
        else:
            state, meaning = "invalid", "Value does not match the reviewed field definition."
        results.append(
            FieldInterpretation(
                field=rule.field,
                raw_value=raw,
                state=state,
                value=value,
                unit=unit,
                meaning=meaning,
                citation_id=rule.citation_id,
                source_quote=rule.source_quote,
            )
        )
    return results
