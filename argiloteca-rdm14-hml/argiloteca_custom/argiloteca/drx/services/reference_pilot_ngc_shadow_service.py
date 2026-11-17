"""Opt-in N/G/C companion to frozen V2; no ranking replacement or persistence.

Family compatibility follows USGS OFR 01-041. Numeric detection thresholds are
experimental engineering choices, not literature-validated decision limits.
Only declared RAW1.01 header axes are used; no quartz/glycol offsets are fitted.
"""
from __future__ import annotations

import hashlib
import json
import math

from argiloteca_drx_core.raw101_shadow import parse_raw101_shadow, RULE as AXIS_RULE
from .reference_pilot_v2_service import evaluate_reference_pilot_v2, RULE as V2_RULE

RULE = "pilot-ngc-family-context-shadow-v1"
SOURCES = {
    "chlorite": "https://pubs.usgs.gov/of/2001/of01-041/htmldocs/clays/chlor.htm",
    "smectite": "https://pubs.usgs.gov/of/2001/of01-041/htmldocs/clays/smc.htm",
}
PARAMETERS = {
    "smoothing": "Savitzky-Golay 9 points polynomial 2",
    "minimum_prominence_fraction": .02, "minimum_width_points": 3,
    "minimum_distance_two_theta": .18, "chlorite_basal_window": [13.7, 14.7],
    "chlorite_basal_max_spread_angstrom": .5,
    "chlorite_companions": [[6.9, 7.3], [3.50, 3.56]],
    "chlorite_minimum_prominence_fraction": .05,
    "smectite_n_window": [12, 16.5], "smectite_g_window": [16, 18.5],
    "smectite_c_window": [9.4, 10.5], "minimum_expansion_angstrom": .6,
    "minimum_collapse_angstrom": 1.5, "smectite_minimum_prominence_fraction": .1,
    "g_harmonic_d_tolerance_angstrom": .35,
    "maximum_points_per_curve": 100_000,
}


def _profile_peaks(curve):
    """Find peaks on the whole profile; never manufacture a window-edge peak."""
    import numpy as np
    from scipy.signal import find_peaks, savgol_filter
    x = np.asarray(curve.two_theta)
    if max(curve.intensity) == min(curve.intensity):
        return []
    y = savgol_filter(curve.intensity, 9, 2)
    span = float(max(y) - min(y))
    if span <= 0:
        return []
    step = float(np.median(np.diff(x)))
    indices, props = find_peaks(y, prominence=span * .02, width=3,
                               distance=max(1, math.ceil(.18 / step)))
    wave = curve.metadata["wavelength_angstrom"]
    return [{"two_theta": float(x[i]),
             "d_angstrom": wave / (2 * math.sin(math.radians(x[i] / 2))),
             "relative_prominence": float(props["prominences"][j] / span),
             "width_two_theta": float(props["widths"][j] * step),
             "status": "observed_profile_maximum"} for j, i in enumerate(indices)]


def _pick(peaks, lo, hi, prominence=.02):
    return max((p for p in peaks if lo <= p["d_angstrom"] <= hi
                and p["relative_prominence"] >= prominence),
               key=lambda p: p["relative_prominence"], default=None)


def _family_context(profiles):
    """No species, percentages or calibrated scores are inferred here."""
    basal = {t: _pick(profiles.get(t, []), 13.7, 14.7, .05) for t in "NGC"}
    companions = {t: [_pick(profiles.get(t, []), lo, hi, .05)
                      for lo, hi in PARAMETERS["chlorite_companions"]] for t in "NG"}
    stable = (all(basal.values()) and
              max(p["d_angstrom"] for p in basal.values()) -
              min(p["d_angstrom"] for p in basal.values()) <= .5)
    chlorite = bool(stable and all(all(p) for p in companions.values()))
    n = _pick(profiles.get("N", []), 12, 16.5, .1)
    g = _pick(profiles.get("G", []), 16, 18.5, .1)
    c = _pick(profiles.get("C", []), 9.4, 10.5, .1)
    harmonic = _pick(profiles.get("G", []), g["d_angstrom"] / 2 - .35,
                     g["d_angstrom"] / 2 + .35) if g else None
    smectite = bool(n and g and c and harmonic and
                    g["d_angstrom"] - n["d_angstrom"] >= .6 and
                    n["d_angstrom"] - c["d_angstrom"] >= 1.5)
    return [
        {"family": "chlorite_group", "status": "compatible" if chlorite else "inconclusive",
         "rule_id": RULE + ":stable_14_companions", "source": SOURCES["chlorite"],
         "observations": {"basal_by_treatment": basal, "companions_ng": companions},
         "missing_evidence": [t + "_basal_14" for t, p in basal.items() if not p] +
             [t + "_companions" for t, ps in companions.items() if not all(ps)],
         "interpretation": "Compatibility only; intensity changes do not exclude chlorite."
         if chlorite else "Insufficient coherent N/G/C evidence; not evidence of absence."},
        {"family": "smectite_group", "status": "compatible" if smectite else "inconclusive",
         "rule_id": RULE + ":expansion_collapse_companion", "source": SOURCES["smectite"],
         "observations": {"N": n, "G": g, "C": c, "G_second_order": harmonic},
         "interpretation": "Expansion/collapse compatible with smectites; species unresolved."
         if smectite else "Incomplete or conflicting trajectory; mixed layers remain possible."},
    ]


def evaluate_reference_pilot_ngc_shadow(files, *, enabled=False, index_path=None):
    """files = [{treatment: N|G|C, content: bytes}]; memory-only, explicit opt-in."""
    result = {"schema_version": "argiloteca.drx.reference_pilot.ngc_shadow.v1",
              "rule_id": RULE, "mode": "shadow", "policy": "auxiliary_candidates_only_no_reclassification",
              "status": "disabled", "family_context": [], "by_treatment": {}}
    if not enabled:
        return result
    if not isinstance(files, (list, tuple)) or not 1 <= len(files) <= 3:
        raise ValueError("One explicit N/G/C group with at most three preparations is required.")
    profiles, provenance, seen_hashes = {}, {}, set()
    for item in files:
        treatment = item["treatment"]
        if treatment not in {"N", "G", "C"} or treatment in profiles:
            raise ValueError("Unknown or duplicate preparation; grouping must be reviewed.")
        # The stricter context limit also bounds smoothing/peak allocation.
        if len(item["content"]) > 1016 + PARAMETERS["maximum_points_per_curve"] * 4:
            raise ValueError("Curve exceeds experimental N/G/C context limit.")
        curve = parse_raw101_shadow(item["content"], enabled=True)
        digest = curve.metadata["source_sha256"]
        if digest in seen_hashes:
            raise ValueError("The same RAW cannot provide two independent preparations.")
        seen_hashes.add(digest)
        provenance[treatment] = curve.metadata
        profiles[treatment] = _profile_peaks(curve)
        result["by_treatment"][treatment] = evaluate_reference_pilot_v2(
            curve.two_theta, curve.intensity, enabled=True, index_path=index_path,
            wavelength_angstrom=curve.metadata["wavelength_angstrom"],
            preparation=treatment, source_sha256=digest,
            corrections={"axis_adapter": AXIS_RULE, "automatic_axis_offset": False})
    waves = [p["wavelength_angstrom"] for p in provenance.values()]
    if max(waves) - min(waves) > 1e-6:
        raise ValueError("Preparations declare inconsistent wavelengths.")
    context = _family_context(profiles)
    complete = len(profiles) == 3
    result.update(status="evaluated" if complete else "incomplete_ngc",
                  family_context=context, profile_peaks=profiles, provenance=provenance,
                  parameters=PARAMETERS.copy(), structural_rule=V2_RULE,
                  ranking_policy="unchanged_v2_per_curve_family_context_separate",
                  review_status="family_compatible_species_requires_review" if any(
                      c["status"] == "compatible" for c in context) else "inconclusive_review_raw_and_protocol",
                  warnings=["not_species_confirmation", "not_probability_or_mass_fraction",
                            "temperature_and_preparation_protocol_not_verified",
                            "header_axis_is_not_independent_calibration",
                            "experimental_thresholds_not_accuracy_validated",
                            "mixtures_mixed_layers_and_orientation_require_curatorial_review"] +
                      ([] if complete else ["missing_preparation_no_complete_trajectory"]))
    fingerprint = {"sources": {t: p["source_sha256"] for t, p in provenance.items()},
                   "parameters": PARAMETERS, "rule": RULE, "axis_rule": AXIS_RULE,
                   "v2": {t: p.get("analysis_fingerprint") for t, p in result["by_treatment"].items()}}
    result["analysis_fingerprint"] = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    return result
