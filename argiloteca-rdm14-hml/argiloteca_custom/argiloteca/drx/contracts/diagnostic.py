from __future__ import annotations

from typing import Any

from ..domain.enums import ScientificStatus
from .common import as_mapping, enum_value, list_value, mapping_value, number, optional_text, required_text, validate_version

MINERAL_CANDIDATE_SCHEMA = "argiloteca.drx.mineral_candidate.v1"
DIAGNOSTIC_SCHEMA = "argiloteca.drx.diagnostic.v1"


def validate_mineral_candidate(payload: Any) -> dict:
    row = as_mapping(payload, "mineral_candidate")
    validate_version(row)
    row["mineral"] = required_text(row, "mineral")
    row["family"] = optional_text(row, "family")
    row["score"] = number(row, "score", required=False) or 0.0
    row["confidence"] = optional_text(row, "confidence")
    row["status"] = enum_value(
        ScientificStatus, row.get("status", ScientificStatus.INFERRED.value), "status"
    )
    for field in ("evidence", "alternatives", "limitations"):
        row[field] = list_value(row, field)
    return row


def validate_diagnostic(payload: Any) -> dict:
    row = as_mapping(payload, "diagnostic")
    validate_version(row)
    row["status"] = enum_value(
        ScientificStatus, row.get("status", ScientificStatus.INCONCLUSIVE.value), "status"
    )
    for field in ("calculated", "inferred", "reviewed", "confirmed", "warnings", "recommended_tests"):
        row[field] = list_value(row, field)
    row["provenance"] = mapping_value(row, "provenance")
    return row
