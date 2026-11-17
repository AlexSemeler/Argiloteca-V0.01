"""Scientific analysis orchestration for one prepared external DRX curve."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from argiloteca.services.drx import infer_diffractogram_sample_base
from argiloteca.services.drx_analysis import build_drx_analysis_run
from argiloteca.services.drx_report import build_drx_technical_report


@dataclass(frozen=True)
class ExternalCurveAnalysisResult:
    identification: dict
    analysis_run: dict
    technical_report: dict
    diagnostic_evidence: dict
    advanced_processing: dict
    advanced_summary: dict
    advanced_curve: dict
    preclassification: dict


def _peak_number(peak, keys, default=None):
    for key in keys:
        try:
            value = float((peak or {}).get(key))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value
    return default


def infer_external_d060(peaks):
    candidates = []
    for peak in peaks or []:
        d_value = _peak_number(peak, ("d_angstrom", "d", "d_spacing", "center_d_angstrom", "d_A"))
        if d_value is None or not 1.485 <= d_value <= 1.555:
            continue
        intensity = _peak_number(peak, ("relative_intensity", "intensity", "i_abs", "height", "amplitude"), 0.0)
        candidates.append({
            "d060": round(d_value, 5),
            "two_theta": (peak or {}).get("two_theta") or (peak or {}).get("center_2theta"),
            "intensity": intensity,
            "source": "inferred_from_external_curve_peak_window",
            "status": "inferred_auxiliary",
            "distance_to_reference_centers": round(min(abs(d_value - center) for center in (1.50, 1.52, 1.54)), 5),
            "warning": "d060 inferido de amostra externa; evidência auxiliar. Verificar montagem em pó aleatório e interferência de quartzo perto de 1.541 Å.",
        })
    if not candidates:
        return {
            "status": "unavailable",
            "reason": "no_peak_in_060_window",
            "warning": "Nenhum pico detectado entre 1.485 e 1.555 Å; classificação 060 permanece indisponível.",
        }
    candidates.sort(key=lambda row: (row["distance_to_reference_centers"], -row["intensity"]))
    return candidates[0]


def build_preclassification(*, prepared, temporary_path, advanced_processing, identification):
    peaks = advanced_processing.get("peaks") or identification.get("peaks") or []
    d060 = infer_external_d060(peaks)
    metadata = {
        **(prepared.parsed.metadata or {}),
        "source": "external_curve_preclassification",
        "source_sha256": prepared.source_sha256,
        "temporary_upload_path": str(temporary_path),
        "sample_code": prepared.sample_code,
        "original_filename": prepared.filename,
        "preparation": prepared.treatment.get("type"),
        "curve_points": len(prepared.parsed.two_theta),
        "d060_status": d060.get("status"),
        "d060_warning": d060.get("warning"),
    }
    if d060.get("status") == "inferred_auxiliary":
        metadata.update({"d060": d060.get("d060"), "d060_source": d060.get("source"),
                         "d060_two_theta": d060.get("two_theta"), "d060_intensity": d060.get("intensity")})
    item = {
        "id": f"external_curve:{prepared.source_sha256[:16]}",
        "filename": prepared.filename,
        "sample_code": prepared.sample_code,
        "sample_base": infer_diffractogram_sample_base(prepared.sample_code, prepared.filename),
        "preparation": prepared.treatment.get("type"),
        "peaks": peaks,
        "advanced_peaks": advanced_processing.get("peaks") or [],
        "targeted_basal_peaks": advanced_processing.get("targeted_basal_peaks") or [],
        "fit_results": advanced_processing.get("fit_results") or [],
        "metadata": metadata,
        "warnings": [d060.get("warning")] if d060.get("warning") else [],
    }
    return {"available": True, "schema_version": "argiloteca.drx.external_curve_preclassification.v1",
            "policy": "argiloteca_rule_based_diagnostic", "item": item, "d060": d060}


def analyze_external_curve(*, prepared, temporary_path, max_points: int, wavelength_angstrom: float,
                           identify_candidates: Callable) -> ExternalCurveAnalysisResult:
    parsed = prepared.parsed
    identification = identify_candidates(parsed.two_theta, parsed.intensity)
    analysis_payload = build_drx_analysis_run(
        filename=prepared.filename, sample_code=prepared.sample_code, source_sha256=prepared.source_sha256,
        parsed=parsed, identification=identification, preparation=prepared.treatment.get("type"),
        max_points=max_points, stored=False, wavelength_angstrom=wavelength_angstrom,
    )
    advanced_processing = analysis_payload["advanced_processing"]
    preclassification = build_preclassification(
        prepared=prepared, temporary_path=temporary_path, advanced_processing=advanced_processing,
        identification=identification,
    )
    technical_report = build_drx_technical_report(
        analysis_run=analysis_payload["analysis_run"], advanced_processing=advanced_processing,
        identification=identification, diagnostic_evidence=analysis_payload["diagnostic_evidence"],
    )
    return ExternalCurveAnalysisResult(
        identification=identification, analysis_run=analysis_payload["analysis_run"],
        technical_report=technical_report, diagnostic_evidence=analysis_payload["diagnostic_evidence"],
        advanced_processing=advanced_processing, advanced_summary=analysis_payload["advanced_summary"],
        advanced_curve=analysis_payload["advanced_curve"], preclassification=preclassification,
    )
