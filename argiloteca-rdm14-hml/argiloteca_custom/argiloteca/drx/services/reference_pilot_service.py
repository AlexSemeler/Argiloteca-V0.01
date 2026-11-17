"""Read-only, opt-in reference evidence. Never updates mineral classifications.

Rule pilot-position-coverage-v1: one-to-one line matching within 0.25 deg 2theta,
restricted to the measured interval. Intensities are not abundance or probability.
This pilot has no validated accuracy claim and cannot confirm mineral identity.
"""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

SCHEMA = "argiloteca.drx.reference_pilot.v1"
RULE = "pilot-position-coverage-v1"
DEFAULT_INDEX = Path(__file__).resolve().parents[2] / "data" / "reference_pilot_v1.json"
MAX_POINTS = 2_000_000
POLICY = "auxiliary_candidates_only_no_reclassification"


def _number(value):
    if isinstance(value, bool):
        raise ValueError("Expected a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Expected a finite number.")
    return result


def validate_curve(x, y, wavelength):
    if not isinstance(x, (list, tuple)) or not isinstance(y, (list, tuple)):
        raise ValueError("Expected two numeric arrays.")
    if len(x) != len(y) or not 10 <= len(x) <= MAX_POINTS:
        raise ValueError("Curve requires 10 to 2000000 paired points.")
    wave = _number(wavelength)
    if not 0.1 <= wave <= 5.0:
        raise ValueError("Wavelength must be between 0.1 and 5 angstroms.")
    xs, ys = [_number(v) for v in x], [_number(v) for v in y]
    if xs[0] <= 0 or xs[-1] >= 180 or any(b <= a for a, b in zip(xs, xs[1:])):
        raise ValueError("2theta must increase strictly between 0 and 180 degrees.")
    return xs, ys, wave


@lru_cache(maxsize=4)
def _load_index(path, mtime, size):
    raw = Path(path).read_bytes()
    data = json.loads(raw)
    if data.get("schema_version") != "argiloteca.drx.reference_pilot_index.v1":
        raise ValueError("Unsupported reference index schema.")
    rows = data.get("references")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Reference index is empty.")
    for row in rows:
        if not row.get("reference_id") or not row.get("source_sha256") or not row.get("citation"):
            raise ValueError("Reference provenance is incomplete.")
        if row.get("pattern_kind") != "calculated" or not row.get("peaks"):
            raise ValueError("Pilot index requires calculated reference lines.")
        if any(_number(p["d_angstrom"]) <= 0 for p in row["peaks"]):
            raise ValueError("Invalid reference d-spacing.")
    return data, hashlib.sha256(raw).hexdigest()


def pilot_status(*, enabled=False, index_path=None):
    result = {"schema_version": SCHEMA, "enabled": bool(enabled), "mode": "shadow",
              "status": "disabled", "available": False, "policy": POLICY, "rule_id": RULE}
    if not enabled:
        return result
    try:
        path = Path(index_path or DEFAULT_INDEX)
        stat = path.stat()
        data, digest = _load_index(str(path), stat.st_mtime_ns, stat.st_size)
        result.update(status="available", available=True, index_version=data["index_version"],
                      index_sha256=digest, reference_count=len(data["references"]),
                      mineral_count=len({r["mineral_id"] for r in data["references"]}),
                      sources=sorted({r["source"] for r in data["references"]}),
                      coverage=data.get("coverage", {}), validation_status="technical_pilot_not_accuracy_validated")
    except (OSError, ValueError, KeyError, TypeError):
        result.update(status="unavailable", reason="index_missing_or_invalid")
    return result


def evaluate_reference_pilot(x, y, *, wavelength_angstrom, enabled=False, index_path=None,
                             preparation="unknown", source_sha256=None, corrections=None):
    status = pilot_status(enabled=enabled, index_path=index_path)
    if not status["available"]:
        return {**status, "candidates": []}
    xs, ys, wave = validate_curve(x, y, wavelength_angstrom)
    # Bounded local-maximum screening, independent of optional scientific engines.
    # The original diagnostic peak detector and classifications are untouched.
    span = max(ys) - min(ys)
    floor = min(ys) + span * 0.02
    maxima = [i for i in range(1, len(xs) - 1)
              if ys[i] > ys[i - 1] and ys[i] >= ys[i + 1] and ys[i] >= floor] if span > 0 else []
    indices = []
    for i in sorted(maxima, key=lambda i: ys[i], reverse=True):
        if all(abs(xs[i] - xs[j]) >= 0.18 for j in indices):
            indices.append(i)
            if len(indices) >= 80:
                break
    observed = sorted([{"two_theta": xs[i], "d_angstrom": wave / (2 * math.sin(math.radians(xs[i] / 2)))}
                       for i in indices], key=lambda p: p["two_theta"])
    path = Path(index_path or DEFAULT_INDEX)
    stat = path.stat()
    data, digest = _load_index(str(path), stat.st_mtime_ns, stat.st_size)
    groups = {}
    for row in data["references"]:
        peaks = []
        for peak in row["peaks"]:
            ratio = wave / (2 * float(peak["d_angstrom"]))
            if not 0 < ratio < 1:
                continue
            angle = math.degrees(2 * math.asin(ratio))
            if xs[0] <= angle <= xs[-1]:
                peaks.append({**peak, "two_theta": angle})
        used, matches = set(), []
        for peak in sorted(peaks, key=lambda p: p.get("relative_intensity", 0), reverse=True):
            choices = [(abs(p["two_theta"] - peak["two_theta"]), j, p) for j, p in enumerate(observed)
                       if j not in used and abs(p["two_theta"] - peak["two_theta"]) <= 0.25]
            if choices:
                delta, j, obs = min(choices, key=lambda t: t[0])
                used.add(j)
                matches.append({"observed_two_theta": obs["two_theta"], "reference_two_theta": round(peak["two_theta"], 6),
                                "reference_d_angstrom": peak["d_angstrom"], "delta_two_theta": round(delta, 6),
                                "hkl": peak.get("hkl")})
        if len(matches) < 2:
            continue
        candidate = {key: row.get(key) for key in ("reference_id", "mineral_id", "mineral_name", "source", "source_id",
                     "source_url", "citation", "doi", "source_sha256", "pattern_kind", "conditions", "license")}
        candidate.update(status="candidate", score=round(len(matches) / len(peaks), 5),
                         score_kind="observable_reference_line_coverage_not_probability", matches=matches,
                         matched_peak_count=len(matches), observable_reference_peak_count=len(peaks),
                         unmatched_observed_peaks=[p["two_theta"] for j, p in enumerate(observed) if j not in used],
                         reference_lines=peaks, variants=[], rule_id=RULE)
        previous = groups.get(row["mineral_id"])
        if previous is None:
            groups[row["mineral_id"]] = candidate
        else:
            # Multiple structures or providers never count as independent votes.
            best, other = (candidate, previous) if candidate["score"] > previous["score"] else (previous, candidate)
            best["variants"] = previous["variants"] + [other["reference_id"]]
            groups[row["mineral_id"]] = best
    candidates = sorted(groups.values(), key=lambda c: (-c["score"], -c["matched_peak_count"], c["mineral_id"]))[:8]
    settings = {"rule_id": RULE, "tolerance_two_theta": 0.25, "relative_height_above_minimum": 0.02,
                "peak_detector": "bounded_local_maximum_v1", "min_peak_distance_two_theta": 0.18, "max_observed_peaks": 80,
                "wavelength_angstrom": wave, "preparation": preparation or "unknown", "corrections": corrections or {},
                "measured_range_two_theta": [xs[0], xs[-1]], "index_sha256": digest}
    curve_hash = hashlib.sha256(json.dumps([xs, ys], separators=(",", ":")).encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps([source_sha256, curve_hash, settings], sort_keys=True).encode()).hexdigest()
    return {**status, "status": "candidates" if candidates else "inconclusive", "candidates": candidates,
            "input_sha256": source_sha256, "analysis_fingerprint": fingerprint, "parameters": settings,
            "observed_peak_count": len(observed), "analyzed_points": len(xs),
            "limitations": ["calculated_ideal_structure_not_ngc_treatment", "preferred_orientation_changes_intensities",
                            "not_probability_or_mass_fraction", "curatorial_confirmation_required",
                            "mixtures_and_mixed_layers_require_separate_assessment", "pilot_coverage_is_incomplete"]}
