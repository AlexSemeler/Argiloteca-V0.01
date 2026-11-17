"""Framework-independent preparation of temporary external DRX curves."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from argiloteca.drx.contracts.external_curve import ExternalCurveRequest, PreparedExternalCurve
from argiloteca.services.drx import (
    apply_two_theta_axis_alignment,
    calculate_quartz_axis_offset,
    infer_diffractogram_sample_base,
    infer_diffractogram_treatment,
    parse_diffractogram_bytes,
)


class ExternalCurveValidationError(ValueError):
    pass


def validate_external_curve_request(request: ExternalCurveRequest) -> ExternalCurveRequest:
    if not request.content:
        raise ExternalCurveValidationError("Arquivo vazio.")
    if request.max_points < 1 or request.max_points > 5000:
        raise ExternalCurveValidationError("max_points deve estar entre 1 e 5000.")
    if not math.isfinite(float(request.wavelength_angstrom)) or float(request.wavelength_angstrom) <= 0:
        raise ExternalCurveValidationError("Comprimento de onda invalido.")
    return request


def prepare_external_curve(request: ExternalCurveRequest) -> PreparedExternalCurve:
    request = validate_external_curve_request(request)
    filename = Path(request.filename).name
    parsed = parse_diffractogram_bytes(request.content, filename=filename)
    sample_code = str(request.sample_code or Path(filename).stem)
    treatment = infer_diffractogram_treatment(sample_code, filename)
    is_raw = Path(filename).suffix.lower() == ".raw"
    declared_axis = parsed.metadata.get('axis_provenance') == 'declared_range_start_2theta_float64'
    current_start = parsed.metadata.get("two_theta_start")
    external_target_start = None
    if (
        is_raw
        and not declared_axis
        and treatment.get("type") == "glicolado"
        and current_start is not None
        and abs(float(current_start) - 3.0) <= 0.25
    ):
        external_target_start = 2.0
    quartz_offset = (
        None
        if not is_raw or declared_axis or external_target_start is not None
        else calculate_quartz_axis_offset(parsed.two_theta, parsed.intensity)
    )
    if external_target_start is not None or quartz_offset:
        parsed = apply_two_theta_axis_alignment(
            parsed,
            filename=filename,
            sample_code=sample_code,
            sample_base=infer_diffractogram_sample_base(sample_code, filename),
            treatment=treatment.get("type"),
            target_start=external_target_start,
            absolute_offset=quartz_offset,
            manual_corrections={},
        )
        if external_target_start is not None and parsed.metadata.get("two_theta_offset_applied") is not None:
            parsed.metadata["two_theta_alignment_method"] = "ngc_external_glycolated_start_heuristic"
            parsed.metadata["curve_source"] = "arquivo_externo_com_eixo_ajustado"
        elif quartz_offset and parsed.metadata.get("two_theta_offset_applied") is not None:
            parsed.metadata["curve_source"] = "arquivo_externo_calibrado_por_quartzo_101"
    return PreparedExternalCurve(
        parsed=parsed,
        filename=filename,
        sample_code=sample_code,
        treatment=treatment,
        source_sha256=hashlib.sha256(request.content).hexdigest(),
        is_raw=is_raw,
    )
