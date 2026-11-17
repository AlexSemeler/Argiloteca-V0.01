"""Application service for the complete temporary external-curve workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from argiloteca.drx.contracts.external_curve import ExternalCurveRequest
from argiloteca.drx.repositories import TemporaryUploadRepository
from argiloteca.services.drx import decimate_series

from .curve_analysis_service import analyze_external_curve
from .gsas2_validation_service import validate_with_gsas2
from .similarity_service import SimilarityRequest, compare_external_curve
from .temporary_curve_service import prepare_external_curve


@dataclass(frozen=True)
class ExternalCurveDependencies:
    identify_candidates: Callable
    compare_similarity: Callable
    seed_peaks: Callable
    submit_gsas2: Callable
    reference_pilot: Callable | None = None


class ExternalCurveService:
    def __init__(self, *, temporary_root: Path, dependencies: ExternalCurveDependencies):
        self.temporary_root = Path(temporary_root)
        self.dependencies = dependencies

    def analyze(self, request: ExternalCurveRequest) -> dict:
        prepared = prepare_external_curve(request)
        temporary_path = TemporaryUploadRepository(self.temporary_root).persist(
            request.content, filename=prepared.filename, sha256=prepared.source_sha256,
        )
        analysis = analyze_external_curve(
            prepared=prepared, temporary_path=temporary_path, max_points=request.max_points,
            wavelength_angstrom=request.wavelength_angstrom,
            identify_candidates=self.dependencies.identify_candidates,
        )
        processing = analysis.advanced_processing
        similarity = compare_external_curve(SimilarityRequest(
            record_id=request.record_id, scope=request.similarity_scope, filename=prepared.filename,
            source_sha256=prepared.source_sha256, metadata={**prepared.parsed.metadata,
                "wavelength_angstrom": prepared.parsed.metadata.get("wavelength_angstrom") or
                    prepared.parsed.metadata.get("wavelength_A") or
                    (None if request.wavelength_assumed else request.wavelength_angstrom)},
            two_theta=prepared.parsed.two_theta, intensity=prepared.parsed.intensity,
            detected_peaks=processing.get("peaks") or analysis.identification.get("peaks") or [],
            mineral_candidates=analysis.identification.get("candidates") or [],
        ), self.dependencies.compare_similarity)
        gsas2 = validate_with_gsas2(
            temporary_path=temporary_path, temporary_root=self.temporary_root,
            original_filename=prepared.filename,
            detected_peaks=processing.get("peaks") or analysis.identification.get("peaks") or [],
            seed_builder=self.dependencies.seed_peaks, submit=self.dependencies.submit_gsas2,
        )
        two_theta, intensity = decimate_series(
            prepared.parsed.two_theta, prepared.parsed.intensity, max_points=request.max_points,
        )
        preclassification = analysis.preclassification
        reference_pilot = None
        if self.dependencies.reference_pilot:
            try:
                reference_pilot = self.dependencies.reference_pilot(
                    prepared.parsed.two_theta, prepared.parsed.intensity,
                    wavelength_angstrom=request.wavelength_angstrom,
                    preparation=prepared.treatment.get("type"), source_sha256=prepared.source_sha256,
                    corrections={key: prepared.parsed.metadata.get(key) for key in
                                 ("two_theta_alignment_method", "two_theta_offset_applied")
                                 if prepared.parsed.metadata.get(key) is not None},
                )
                reference_pilot["wavelength_assumed"] = request.wavelength_assumed
            except Exception:
                reference_pilot = {"schema_version": "argiloteca.drx.reference_pilot.v1", "available": False,
                                   "status": "unavailable", "reason": "pilot_analysis_failed", "candidates": []}
        metadata = {
            **prepared.parsed.metadata,
            "original_filename": prepared.filename,
            "sample_code": prepared.sample_code,
            "source": "arquivo_externo_temporario",
            "source_sha256": prepared.source_sha256,
            "stored": False,
            "temporary_upload_path": str(temporary_path),
            "gsas2_validation": gsas2,
            "mineral_classification_source": analysis.identification.get("reference_source"),
            "mineral_classification_error": analysis.identification.get("classification_error"),
            "advanced_summary": analysis.advanced_summary,
            "advanced_curve": analysis.advanced_curve,
            "peak_processing": processing.get("peak_processing") or {},
            "xrd_method": processing.get("xrd_method") or {},
            "qc_flags": processing.get("qc_flags") or [],
            "external_curve_preclassification": preclassification,
            "external_raw_preclassification": preclassification,
            "analysis_run": analysis.analysis_run,
            "diagnostic_evidence": analysis.diagnostic_evidence,
            "technical_report": analysis.technical_report,
        }
        if reference_pilot is not None:
            metadata["reference_pilot"] = reference_pilot
        d060 = preclassification.get("d060") or {}
        if d060.get("status") == "inferred_auxiliary":
            metadata.update({"d060": d060.get("d060"), "d060_source": d060.get("source"),
                             "d060_warning": d060.get("warning"), "d060_two_theta": d060.get("two_theta")})
        return {
            "success": True, "sample_code": prepared.sample_code, "filename": prepared.filename,
            "analysis_run": analysis.analysis_run, "technical_report": analysis.technical_report,
            "diagnostic_evidence": analysis.diagnostic_evidence, "metadata": metadata,
            "detected_peaks": analysis.identification.get("peaks") or [],
            "advanced_peaks": processing.get("peaks") or [], "fit_results": processing.get("fit_results") or [],
            "qc_flags": processing.get("qc_flags") or [], "mineral_evidence": processing.get("mineral_evidence") or [],
            "mineral_characterization": processing.get("mineral_characterization") or [],
            "basal_tracking": processing.get("basal_tracking") or {}, "advanced_summary": analysis.advanced_summary,
            "advanced_curve": analysis.advanced_curve, "mineral_candidates": analysis.identification.get("candidates") or [],
            "external_curve_preclassification": preclassification, "external_raw_preclassification": preclassification,
            "package_similarity": similarity, "gsas2_validation": gsas2, "two_theta": two_theta,
            "intensity": intensity, "render_points": len(two_theta), "total_points": len(prepared.parsed.two_theta),
        }
