from __future__ import annotations

from typing import Any

from ..domain.enums import Preparation
from .common import as_mapping, enum_value, list_value, mapping_value, optional_text, required_text, validate_version

SAMPLE_SCHEMA = "argiloteca.drx.sample.v1"
TREATMENT_SERIES_SCHEMA = "argiloteca.drx.treatment_series.v1"


def validate_sample(payload: Any) -> dict:
    row = as_mapping(payload, "sample")
    validate_version(row)
    row["identifier"] = required_text(row, "identifier")
    row["sample_code"] = optional_text(row, "sample_code")
    row["sample_base"] = optional_text(row, "sample_base")
    row["record_id"] = optional_text(row, "record_id")
    row["sha256"] = optional_text(row, "sha256")
    row["preparation"] = enum_value(
        Preparation, row.get("preparation", Preparation.UNDETERMINED.value), "preparation"
    )
    row["provenance"] = mapping_value(row, "provenance")
    return row


def validate_treatment_series(payload: Any) -> dict:
    row = as_mapping(payload, "treatment_series")
    validate_version(row)
    for field in ("natural", "glicolada", "calcinada", "indeterminada", "missing"):
        row[field] = list_value(row, field)
    row["duplicates"] = mapping_value(row, "duplicates")
    return row
