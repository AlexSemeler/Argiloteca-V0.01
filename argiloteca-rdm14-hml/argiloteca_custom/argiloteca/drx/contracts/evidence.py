from __future__ import annotations

from typing import Any

from .common import as_mapping, mapping_value, number, optional_text, required_text, validate_version

EVIDENCE_SCHEMA = "argiloteca.drx.evidence.v1"


def validate_evidence(payload: Any) -> dict:
    row = as_mapping(payload, "evidence")
    validate_version(row)
    row["rule_id"] = required_text(row, "rule_id")
    row["kind"] = required_text(row, "kind")
    row["observation"] = required_text(row, "observation")
    row["weight"] = number(row, "weight", required=False) or 0.0
    row["source"] = optional_text(row, "source")
    row["reference"] = optional_text(row, "reference")
    row["provenance"] = mapping_value(row, "provenance")
    return row
