"""Explicit, attributed development views; no model-based relevance or domain logic."""

from quartermaster.contracts.reliability import DefinitionSpan


def selected_views(data, action, facts, evidence):
    fields = (action.context_selection or action.decision_contract).fields
    rules = {r.field: r for r in action.field_rules.rules}
    originals = {e.citation_id: e.text for e in evidence}
    spans = []
    for field in fields:
        rule = rules[field]
        # interpret() already verified the quote and accessible source membership.
        start = originals[rule.citation_id].index(rule.source_quote)
        spans.append(
            DefinitionSpan(
                field=field,
                citation_id=rule.citation_id,
                start=start,
                end=start + len(rule.source_quote),
                text=rule.source_quote,
            )
        )
    raw = {
        "case": {**data["case"], "situation": action.situation},
        "approved_lessons": [],
        "structured_inputs": {
            f: action.decision_inputs[f] for f in fields if f in action.decision_inputs
        },
        "field_rules": {
            **action.field_rules.model_dump(mode="json"),
            "rules": [rules[f].model_dump(mode="json") for f in fields],
        },
        "retrieved_evidence": [{"citation_id": str(s.citation_id), "text": s.text} for s in spans],
    }
    by_field = {f.field: f for f in facts}
    interpreted = {
        **raw,
        "field_interpretations": [by_field[f].model_dump(mode="json") for f in fields],
    }
    return raw, interpreted, spans
