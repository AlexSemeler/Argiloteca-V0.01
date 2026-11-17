from __future__ import annotations

from typing import Any

from .common import ContractValidationError, as_mapping, list_value, mapping_value, number, optional_text, validate_version

CURVE_SCHEMA = "argiloteca.drx.curve.v1"


def validate_curve(payload: Any) -> dict:
    row = as_mapping(payload, "curve")
    validate_version(row)
    x = list_value(row, "two_theta_deg")
    y = list_value(row, "intensity")
    if not x or len(x) != len(y):
        raise ContractValidationError("two_theta_deg e intensity devem ter o mesmo tamanho não vazio.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in x + y):
        raise ContractValidationError("Os pontos da curva devem ser numéricos.")
    row["two_theta_deg"] = [float(v) for v in x]
    row["intensity"] = [float(v) for v in y]
    row["wavelength"] = number(row, "wavelength", required=False)
    row["wavelength_unit"] = optional_text(row, "wavelength_unit") or "angstrom"
    row["processing"] = mapping_value(row, "processing")
    row["provenance"] = mapping_value(row, "provenance")
    return row
