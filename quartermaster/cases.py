"""Small, deterministic reviewed column mapping; no label inference or fuzzy joins."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from quartermaster.config import Settings
from quartermaster.contracts.advice import Case
from quartermaster.contracts.sources import (
    CaseMapping,
    DerivedCase,
    FieldRef,
    MappingPreview,
    SourceRow,
)
from quartermaster.db import connect
from quartermaster.errors import DomainError
from quartermaster.ingestion import candidate_role
from quartermaster.projects import read_spec
from quartermaster.sources import parsed_source, read_source


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def table_key(ref):
    return (ref.source_id, ref.sheet)


def field_key(ref):
    return canonical([str(ref.source_id), ref.sheet, ref.field])


def mapping_id(mapping: CaseMapping) -> UUID:
    return uuid5(NAMESPACE_URL, canonical(mapping.model_dump(mode="json")))


def build_cases(settings: Settings, project_id, mapping: CaseMapping):
    tables = {}
    sources = {}
    refs = [mapping.primary] + [join.table for join in mapping.joins]
    if len({table_key(r) for r in refs}) != len(refs):
        raise DomainError("MAPPING_TABLE: Select each table only once.")
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        for ref in refs:
            if ref.source_id not in sources:
                sources[ref.source_id] = read_source(connection, project_id, ref.source_id)
    for ref in refs:
        source = sources[ref.source_id]
        if source.label == "knowledge":
            raise DomainError("MAPPING_LABEL: Upload case tables as observations or examples.")
        parsed = parsed_source(settings, source)
        table = next((t for t in parsed.tables if t.name == ref.sheet), None)
        if table is None or not table.fields:
            raise DomainError("MAPPING_SHEET: Choose a nonempty spreadsheet sheet.")
        tables[table_key(ref)] = table

    selected = mapping.inputs + mapping.outcomes + mapping.targets
    for ref in selected:
        if table_key(ref) not in tables:
            raise DomainError("JOIN_REQUIRED: Add explicit join keys for every additional table.")
        table = tables[table_key(ref)]
        if ref.field not in table.fields:
            raise DomainError("MAPPING_FIELD: Choose fields shown in the source preview.")
        if any(ref.field in row.formulas for row in table.rows):
            raise DomainError(
                "MAPPING_FORMULA: Map literal values; formula cells are not evaluated."
            )

    warnings = []
    decision_refs = list(mapping.inputs)
    for join in mapping.joins:
        decision_refs.extend(
            [
                join.left,
                FieldRef(
                    source_id=join.table.source_id, sheet=join.table.sheet, field=join.right_key
                ),
            ]
        )
    warned = set()
    for ref in decision_refs:
        if field_key(ref) in warned:
            continue
        warned.add(field_key(ref))
        if candidate_role(ref.field) != "input":
            warnings.append(
                f"{ref.sheet} / {ref.field}: may be a target or a later outcome. "
                f"Confirm it was known at {mapping.decision_time}; otherwise change its role."
            )
    if mapping.targets:
        warnings.append(
            "Target columns are unreviewed candidates, not ideal advice or training labels."
        )
    bundles = [{table_key(mapping.primary): row} for row in tables[table_key(mapping.primary)].rows]
    available = {table_key(mapping.primary)}
    for join in mapping.joins:
        right = tables[table_key(join.table)]
        left_key = table_key(join.left)
        if left_key not in available or join.left.field not in tables[left_key].fields:
            raise DomainError(
                "JOIN_LEFT: The left join key must belong to an already selected table."
            )
        if join.right_key not in right.fields:
            raise DomainError("JOIN_RIGHT: Choose a right join key from the joined table.")
        lookup = {}
        for row in right.rows:
            value = row.values[join.right_key]
            if (
                join.right_key in row.formulas
                or value is None
                or not value.strip()
                or value in lookup
            ):
                raise DomainError(
                    "JOIN_AMBIGUOUS: Right keys must be literal, nonempty and unique."
                )
            lookup[value] = row
        for bundle in bundles:
            left = bundle[left_key]
            value = left.values[join.left.field]
            if join.left.field in left.formulas or value not in lookup:
                raise DomainError(
                    "JOIN_UNMATCHED: Every primary row needs an exact literal key match."
                )
            bundle[table_key(join.table)] = lookup[value]
        available.add(table_key(join.table))

    mid = mapping_id(mapping)
    cases = []
    try:
        for bundle in bundles:

            def values(refs, rows=bundle):
                return {field_key(r): rows[table_key(r)].values[r.field] for r in refs}

            inputs = canonical(
                {
                    "grain": mapping.grain,
                    "decision_time": mapping.decision_time,
                    "fields": values(mapping.inputs),
                }
            )
            outcomes = values(mapping.outcomes)
            provenance = [
                SourceRow(
                    source_id=source_id,
                    source_sha256=sources[source_id].sha256,
                    sheet=sheet,
                    row=row.number,
                    line_start=row.line_start,
                    line_end=row.line_end,
                )
                for (source_id, sheet), row in bundle.items()
            ]
            identity = canonical([mid.hex, [p.model_dump(mode="json") for p in provenance]])
            case = Case(
                case_id=uuid5(mid, identity),
                situation=inputs,
                observed_outcome=canonical(outcomes) if outcomes else None,
            )
            cases.append(
                DerivedCase(
                    case=case,
                    mapping_id=mid,
                    source_rows=provenance,
                    target_candidate=values(mapping.targets),
                )
            )
    except ValidationError:
        raise DomainError(
            "CASE_TOO_LONG: Select fewer or shorter fields (4,000 characters per case)."
        ) from None
    return cases, warnings


def preview_mapping(settings: Settings, project_id, mapping: CaseMapping) -> MappingPreview:
    cases, warnings = build_cases(settings, project_id, mapping)
    return MappingPreview(
        mapping=mapping, warnings=warnings, case_count=len(cases), samples=cases[:5]
    )


def apply_mapping(settings: Settings, project_id, mapping: CaseMapping) -> dict:
    cases, warnings = build_cases(settings, project_id, mapping)
    if not cases:
        raise DomainError("MAPPING_EMPTY: Select a table with at least one data row.")
    mid = mapping_id(mapping)
    with connect(settings.database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT project_id FROM case_mappings WHERE id=?", (str(mid),)
        ).fetchone()
        if existing is not None:
            if existing["project_id"] != str(project_id):
                raise DomainError("MAPPING_PROJECT: Choose sources from this project.")
        else:
            connection.execute(
                "INSERT INTO case_mappings VALUES (?, ?, ?, ?)",
                (
                    str(mid),
                    str(project_id),
                    mapping.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.executemany(
                "INSERT INTO derived_cases VALUES (?, ?, ?)",
                [(str(c.case.case_id), str(mid), c.model_dump_json()) for c in cases],
            )
    content_hash = hashlib.sha256(
        canonical([c.model_dump(mode="json") for c in cases]).encode()
    ).hexdigest()
    return {
        "mapping_id": str(mid),
        "case_count": len(cases),
        "sha256": content_hash,
        "warnings": warnings,
    }


def list_mappings(settings: Settings, project_id):
    with connect(settings.database_path) as connection:
        read_spec(connection, project_id)
        rows = connection.execute(
            "SELECT id, document, created_at, (SELECT COUNT(*) FROM derived_cases WHERE mapping_id="
            "case_mappings.id) AS case_count FROM case_mappings WHERE project_id=? ORDER BY rowid",
            (str(project_id),),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "mapping": CaseMapping.model_validate_json(row["document"]),
            "created_at": row["created_at"],
            "case_count": row["case_count"],
        }
        for row in rows
    ]


def saved_cases(settings: Settings, project_id, mid):
    with connect(settings.database_path) as connection:
        row = connection.execute(
            "SELECT id FROM case_mappings WHERE project_id=? AND id=?", (str(project_id), str(mid))
        ).fetchone()
        if row is None:
            raise DomainError("MAPPING_MISSING: Open a saved mapping from this project.", 404)
        rows = connection.execute(
            "SELECT document FROM derived_cases WHERE mapping_id=? ORDER BY rowid", (str(mid),)
        ).fetchall()
    return [DerivedCase.model_validate_json(row["document"]) for row in rows]
