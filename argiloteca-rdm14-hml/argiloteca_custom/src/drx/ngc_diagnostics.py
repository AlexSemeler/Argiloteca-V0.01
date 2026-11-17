"""Canonical non-confirmatory N/G/C diagnostic engine v4."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from argiloteca_drx.diagnostics import interpret_ngc as interpret_ngc_v3

from .legacy import migrate_legacy_diagnostic
from .rules_loader import load_rule_catalog


ENGINE_VERSION = "argiloteca.drx.ngc.v4"
POLICY = "non_confirmatory_rule_based_evidence"


def _fraction(numerator: int, denominator: int) -> float:
    return min(max(float(numerator) / max(int(denominator), 1), 0.0), 1.0)


def _candidate_score(candidate: dict[str, Any], interpretation: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    evidences = candidate.get("evidences") or candidate.get("evidence") or candidate.get("matched") or []
    missing = candidate.get("missing_evidence") or candidate.get("missing") or []
    behaviors = interpretation.get("behavior_candidates") or []
    summary = interpretation.get("input_summary") or {}
    treatment_count = int(summary.get("treatment_count") or sum(bool(summary.get(f"has_{key}")) for key in ("N", "G", "C")))

    behavior_component = min(len(behaviors), 2) / 2.0
    peak_component = _fraction(len(evidences), len(evidences) + len(missing)) if evidences or missing else 0.0
    treatment_component = min(treatment_count, 3) / 3.0
    metadata_component = 1.0 if candidate.get("source_rule") or candidate.get("rule_id") else 0.0
    weights = catalog["score_weights"]
    score = 100.0 * (
        float(weights["behaviors"]) * behavior_component
        + float(weights["required_peaks"]) * peak_component
        + float(weights["treatments"]) * treatment_component
        + float(weights["metadata"]) * metadata_component
    )
    score = round(min(max(score, 0.0), 100.0), 2)
    if score <= 20:
        state = "compatible_by_rules"
    elif score <= 45:
        state = "possible_candidate"
    elif score <= 75:
        state = "probable_candidate"
    else:
        state = "strongly_supported_candidate"
    if treatment_count < 2 or (len(evidences) <= 1 and not behaviors):
        state = "possible_candidate" if score > 20 else "compatible_by_rules"
    row = deepcopy(candidate)
    if "score" in row:
        row["legacy_score"] = row["score"]
    row["evidence_score"] = score
    row["confidence"] = state
    row["status"] = state
    row["score_components"] = {
        "behaviors": round(behavior_component, 4),
        "required_peaks": round(peak_component, 4),
        "treatments": round(treatment_component, 4),
        "metadata": round(metadata_component, 4),
    }
    limitations = row.get("limitations")
    if not isinstance(limitations, list):
        limitations = [] if limitations in (None, "") else [str(limitations)]
        row["limitations"] = limitations
    limitations.append(
        "Escore operacional para ordenar candidatos; não é probabilidade, teor ou confirmação mineralógica."
    )
    return row


def interpret_ngc(peaks: dict[str, Any], metadata: dict[str, Any] | None = None, empirical_ranges=None) -> dict[str, Any]:
    """Run v3 rules, migrate epistemic states and apply the v4 contract."""
    catalog = load_rule_catalog()
    legacy = interpret_ngc_v3(peaks, metadata=metadata, empirical_ranges=empirical_ranges)
    source = legacy.get("diagnostic_interpretation") or legacy
    interpretation = migrate_legacy_diagnostic(source)
    for field in ("combined_candidates", "chapter7_rule_candidates", "mixed_layer_candidates"):
        rows = interpretation.get(field)
        if isinstance(rows, list):
            interpretation[field] = [
                _candidate_score(row, interpretation, catalog) if isinstance(row, dict) else row
                for row in rows
            ]
    interpretation["engine_version"] = ENGINE_VERSION
    interpretation["policy"] = POLICY
    interpretation["catalog"] = {
        "version": catalog["version"],
        "loader_version": catalog["loader_version"],
        "status": catalog["catalog_status"],
        "sources": catalog["catalog_sources"],
    }
    interpretation["curatorial_states"] = list(catalog["curatorial_states"])
    interpretation.setdefault("warnings", []).append(
        "Estados automáticos da engine v4 são candidatos; 'confirmado' exige CuratorialReview separado."
    )
    return {"diagnostic_interpretation": interpretation}
