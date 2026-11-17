from __future__ import annotations

from typing import Any

from .common import as_mapping, number, optional_text, validate_version

PEAK_SCHEMA = "argiloteca.drx.peak.v1"


def validate_peak(payload: Any) -> dict:
    row = as_mapping(payload, "peak")
    validate_version(row)
    for field in ("two_theta_deg", "d_spacing_angstrom", "intensity"):
        row[field] = number(row, field)
    row["relative_intensity"] = number(row, "relative_intensity", required=False)
    row["fwhm"] = number(row, "fwhm", required=False)
    row["detection_method"] = optional_text(row, "detection_method")
    return row
