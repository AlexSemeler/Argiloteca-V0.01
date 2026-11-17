"""Experimental shadow correction; never selected by the deployed V1 routes.

Cosine-like paired peak-intensity agreement replaces positional coverage as a
ranking score. The original detector, positional tolerance and minimum of two
matches are preserved. This is not a calibrated probability, phase abundance,
or identification. Oriented mounts and N/G/C require separate corroboration.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from .reference_pilot_service import DEFAULT_INDEX, _load_index, _number, pilot_status, validate_curve

SCHEMA = "argiloteca.drx.reference_pilot.v2"
RULE = "pilot-cosine-peak-evidence-v2"
SCORE_KIND = "paired_peak_intensity_cosine_not_probability"


def _observed_peaks(xs, ys, wave):
    # Deliberately unchanged from V1, to isolate the scoring intervention.
    minimum, maximum = min(ys), max(ys)
    span = maximum - minimum
    if not math.isfinite(span):
        raise ValueError("Intensity range must be finite.")
    floor = minimum + span * 0.02
    maxima = [i for i in range(1, len(xs) - 1)
              if ys[i] > ys[i - 1] and ys[i] >= ys[i + 1] and ys[i] >= floor] if span > 0 else []
    indices = []
    for i in sorted(maxima, key=lambda i: ys[i], reverse=True):
        if all(abs(xs[i] - xs[j]) >= 0.18 for j in indices):
            indices.append(i)
            if len(indices) >= 80:
                break
    return sorted([{"two_theta": xs[i],
                    "d_angstrom": wave / (2 * math.sin(math.radians(xs[i] / 2))),
                    "relative_amplitude": (ys[i] - minimum) / span}
                   for i in indices], key=lambda p: p["two_theta"])


def _score_reference(row, observed, wave, measured_range):
    peaks = []
    for peak in row["peaks"]:
        intensity = _number(peak.get("relative_intensity", 0))
        if intensity < 0:
            raise ValueError("Reference intensity must be non-negative.")
        ratio = wave / (2 * float(peak["d_angstrom"]))
        if not 0 < ratio < 1 or intensity == 0:
            continue
        angle = math.degrees(2 * math.asin(ratio))
        if measured_range[0] <= angle <= measured_range[1]:
            peaks.append({**peak, "two_theta": angle, "relative_intensity": intensity})
    if not peaks or not observed:
        return None
    # Normalize before summing to avoid overflow on valid but large intensities.
    ref_max = max(p["relative_intensity"] for p in peaks)
    ref_norm = math.sqrt(sum((p["relative_intensity"] / ref_max) ** 2 for p in peaks))
    obs_norm = math.sqrt(sum(p["relative_amplitude"] ** 2 for p in observed))
    used, matches, dot = set(), [], 0.0
    strongest_reference_matched = False
    for peak in sorted(peaks, key=lambda p: p["relative_intensity"], reverse=True):
        choices = [(abs(p["two_theta"] - peak["two_theta"]), j, p)
                   for j, p in enumerate(observed)
                   if j not in used and abs(p["two_theta"] - peak["two_theta"]) <= 0.25]
        if not choices:
            continue
        delta, j, obs = min(choices, key=lambda t: t[0])
        used.add(j)
        proximity = max(0.0, 1 - delta / 0.25)
        contribution = peak["relative_intensity"] / ref_max * obs["relative_amplitude"] * proximity
        dot += contribution
        if peak["relative_intensity"] == ref_max and contribution > 0:
            strongest_reference_matched = True
        matches.append({"observed_two_theta": obs["two_theta"],
                        "reference_two_theta": round(peak["two_theta"], 6),
                        "reference_d_angstrom": peak["d_angstrom"],
                        "delta_two_theta": round(delta, 6), "hkl": peak.get("hkl"),
                        "reference_relative_intensity": peak["relative_intensity"],
                        "observed_relative_amplitude": obs["relative_amplitude"],
                        "positional_closeness": proximity, "dot_contribution": contribution})
    if len(matches) < 2 or dot <= 0 or obs_norm == 0:
        return None
    score = min(1.0, max(0.0, dot / (ref_norm * obs_norm)))
    candidate = {key: row.get(key) for key in
                 ("reference_id", "mineral_id", "mineral_name", "source", "source_id", "source_url",
                  "citation", "doi", "source_sha256", "pattern_kind", "conditions", "license")}
    candidate.update(status="candidate", score=round(score, 8), score_kind=SCORE_KIND,
                     positional_coverage=round(len(matches) / len(peaks), 5),
                     matched_peak_count=len(matches), observable_reference_peak_count=len(peaks),
                     matches=matches, reference_lines=peaks,
                     unmatched_observed_peaks=[p["two_theta"] for j, p in enumerate(observed) if j not in used],
                     score_components={"dot_product": dot, "reference_l2_norm": ref_norm,
                                       "observed_l2_norm": obs_norm, "reference_intensity_scale": ref_max},
                     diagnostic_flags=[] if strongest_reference_matched else ["strongest_reference_line_unmatched"],
                     variants=[], rule_id=RULE)
    return candidate


def evaluate_reference_pilot_v2(x, y, *, wavelength_angstrom, enabled=False, index_path=None,
                                preparation="unknown", source_sha256=None, corrections=None):
    """Explicit opt-in V2 evaluation. Does not touch V1, records or classifications."""
    status = {**pilot_status(enabled=enabled, index_path=index_path), "schema_version": SCHEMA,
              "rule_id": RULE, "validation_status": "experimental_correction_not_accuracy_validated"}
    if not status["available"]:
        return {**status, "candidates": []}
    xs, ys, wave = validate_curve(x, y, wavelength_angstrom)
    observed = _observed_peaks(xs, ys, wave)
    path = Path(index_path or DEFAULT_INDEX)
    stat = path.stat()
    data, digest = _load_index(str(path), stat.st_mtime_ns, stat.st_size)
    groups = {}
    for row in data["references"]:
        candidate = _score_reference(row, observed, wave, (xs[0], xs[-1]))
        if candidate is None:
            continue
        previous = groups.get(row["mineral_id"])
        if previous is None:
            groups[row["mineral_id"]] = candidate
        else:
            # Duplicate providers/structures remain variants, never extra votes.
            best, other = (candidate, previous) if candidate["score"] > previous["score"] else (previous, candidate)
            best["variants"] = previous["variants"] + [other["reference_id"]]
            groups[row["mineral_id"]] = best
    # Evaluate every reference before truncation; V1's truncated list is not reused.
    candidates = sorted(groups.values(), key=lambda c: (-c["score"], -c["matched_peak_count"], c["mineral_id"]))[:8]
    settings = {"rule_id": RULE, "score_kind": SCORE_KIND, "tolerance_two_theta": 0.25,
                "relative_height_above_minimum": 0.02, "peak_detector": "bounded_local_maximum_v1",
                "min_peak_distance_two_theta": 0.18, "max_observed_peaks": 80,
                "minimum_matched_lines": 2, "wavelength_angstrom": wave,
                "preparation": preparation or "unknown", "corrections": corrections or {},
                "measured_range_two_theta": [xs[0], xs[-1]], "index_sha256": digest}
    curve_hash = hashlib.sha256(json.dumps([xs, ys], separators=(",", ":")).encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps([source_sha256, curve_hash, settings], sort_keys=True).encode()).hexdigest()
    return {**status, "status": "candidates" if candidates else "inconclusive", "candidates": candidates,
            "input_sha256": source_sha256, "analysis_fingerprint": fingerprint, "parameters": settings,
            "observed_peak_count": len(observed), "analyzed_points": len(xs),
            "limitations": ["experimental_intensity_score_not_calibrated",
                            "calculated_ideal_structure_not_ngc_treatment",
                            "single_smectite_structure_does_not_cover_variable_basal_spacing",
                            "preferred_orientation_changes_intensities",
                            "not_probability_or_mass_fraction", "curatorial_confirmation_required",
                            "mixtures_and_mixed_layers_require_separate_assessment", "pilot_coverage_is_incomplete"]}
