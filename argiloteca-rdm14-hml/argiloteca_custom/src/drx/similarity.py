"""Pure similarity helpers for DRX curves.

The functions here avoid heavy scientific dependencies so they can run in the
existing Argiloteca environment and in small offline scripts. They return
candidate similarity evidence, never confirmed mineralogical interpretation.
"""

from __future__ import annotations

import math


def _finite_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def normalize_intensity(intensity: list[float]) -> list[float]:
    """Scale intensities to 0..1 using the maximum finite positive value."""
    values = [_finite_float(value) for value in intensity]
    finite = [value for value in values if value is not None]
    maximum = max(finite) if finite else 0.0
    if maximum <= 0:
        return [0.0 for _ in intensity]
    return [round((value or 0.0) / maximum, 8) for value in values]


def common_two_theta_grid(
    left_two_theta: list[float],
    right_two_theta: list[float],
    step: float | None = None,
    max_points: int = 2000,
) -> list[float]:
    """Return an overlapping 2theta grid for two curves."""
    left = [_finite_float(value) for value in left_two_theta]
    right = [_finite_float(value) for value in right_two_theta]
    left = [value for value in left if value is not None]
    right = [value for value in right if value is not None]
    if not left or not right:
        return []
    start = max(min(left), min(right))
    end = min(max(left), max(right))
    if end <= start:
        return []
    if step is None:
        left_step = _median_step(left)
        right_step = _median_step(right)
        candidates = [value for value in (left_step, right_step) if value and value > 0]
        step = max(candidates) if candidates else (end - start) / max_points
    step = max(float(step), (end - start) / max(max_points - 1, 1))
    points = int(math.floor((end - start) / step)) + 1
    return [round(start + index * step, 6) for index in range(max(0, points))]


def _median_step(axis: list[float]) -> float | None:
    diffs = sorted(
        round(axis[index + 1] - axis[index], 8)
        for index in range(len(axis) - 1)
        if axis[index + 1] > axis[index]
    )
    if not diffs:
        return None
    return diffs[len(diffs) // 2]


def resample_curve(
    two_theta: list[float],
    intensity: list[float],
    grid: list[float],
) -> list[float]:
    """Linearly interpolate intensity values onto a target 2theta grid."""
    pairs = []
    for theta_raw, value_raw in zip(two_theta, intensity):
        theta = _finite_float(theta_raw)
        value = _finite_float(value_raw)
        if theta is not None and value is not None:
            pairs.append((theta, value))
    pairs.sort()
    if not pairs or not grid:
        return []
    result = []
    cursor = 0
    for target in grid:
        if target <= pairs[0][0]:
            result.append(pairs[0][1])
            continue
        if target >= pairs[-1][0]:
            result.append(pairs[-1][1])
            continue
        while cursor < len(pairs) - 2 and pairs[cursor + 1][0] < target:
            cursor += 1
        left_theta, left_value = pairs[cursor]
        right_theta, right_value = pairs[cursor + 1]
        span = right_theta - left_theta
        if span <= 0:
            result.append(left_value)
            continue
        ratio = (target - left_theta) / span
        result.append(left_value + ratio * (right_value - left_value))
    return result


def correlation_similarity(left: list[float], right: list[float]) -> float:
    """Return Pearson correlation mapped to 0..1."""
    pairs = []
    for a_raw, b_raw in zip(left, right):
        a = _finite_float(a_raw)
        b = _finite_float(b_raw)
        if a is not None and b is not None:
            pairs.append((a, b))
    if len(pairs) < 2:
        return 0.0
    left_mean = sum(a for a, _b in pairs) / len(pairs)
    right_mean = sum(b for _a, b in pairs) / len(pairs)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in pairs)
    left_den = math.sqrt(sum((a - left_mean) ** 2 for a, _b in pairs))
    right_den = math.sqrt(sum((b - right_mean) ** 2 for _a, b in pairs))
    if left_den <= 0 or right_den <= 0:
        return 0.0
    corr = numerator / (left_den * right_den)
    return round(max(0.0, min(1.0, (corr + 1.0) / 2.0)), 4)


def euclidean_similarity(left: list[float], right: list[float]) -> float:
    """Return 1 / (1 + normalized RMSE) for two normalized curves."""
    pairs = []
    for a_raw, b_raw in zip(left, right):
        a = _finite_float(a_raw)
        b = _finite_float(b_raw)
        if a is not None and b is not None:
            pairs.append((a, b))
    if not pairs:
        return 0.0
    mse = sum((a - b) ** 2 for a, b in pairs) / len(pairs)
    rmse = math.sqrt(mse)
    return round(1.0 / (1.0 + rmse), 4)


def peak_similarity(
    left_peaks: list[dict],
    right_peaks: list[dict],
    tolerance_two_theta: float = 0.12,
    tolerance_d: float = 0.10,
) -> tuple[float, list[str]]:
    """Compare peak lists using position, relative intensity and FWHM/width."""
    left = _usable_peaks(left_peaks)
    right = _usable_peaks(right_peaks)
    if not left or not right:
        return 0.0, ["picos insuficientes para comparar"]
    used = set()
    matches = []
    for peak in left:
        best_index = None
        best_score = None
        best_details = None
        for index, candidate in enumerate(right):
            if index in used:
                continue
            delta_t = None
            if peak.get("two_theta") is not None and candidate.get("two_theta") is not None:
                delta_t = abs(peak["two_theta"] - candidate["two_theta"])
            left_d = peak.get("d")
            right_d = candidate.get("d")
            delta_d = abs(left_d - right_d) if left_d is not None and right_d is not None else None

            position_scores = []
            if delta_t is not None and delta_t <= tolerance_two_theta:
                position_scores.append(1.0 - (delta_t / tolerance_two_theta))
            if delta_d is not None and delta_d <= tolerance_d:
                position_scores.append(1.0 - (delta_d / tolerance_d))
            if not position_scores:
                continue
            position_score = max(position_scores)

            intensity_delta = _relative_delta(peak.get("relative_intensity"), candidate.get("relative_intensity"))
            intensity_score = None if intensity_delta is None else max(0.0, 1.0 - min(intensity_delta / 0.50, 1.0))
            width_delta = _relative_delta(peak.get("width"), candidate.get("width"))
            width_score = None if width_delta is None else max(0.0, 1.0 - min(width_delta / 0.75, 1.0))
            width_weight = _width_weight(peak, candidate)

            weighted_score = position_score * 0.60
            weight = 0.60
            if intensity_score is not None:
                weighted_score += intensity_score * 0.25
                weight += 0.25
            if width_score is not None:
                weighted_score += width_score * width_weight
                weight += width_weight
            score = weighted_score / weight
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
                best_details = {
                    "delta_t": delta_t,
                    "delta_d": delta_d,
                    "intensity_delta": intensity_delta,
                    "width_delta": width_delta,
                    "width_weight": width_weight,
                    "score": score,
                }
        if best_index is not None:
            used.add(best_index)
            matches.append((peak, right[best_index], best_details or {}))
    evidence = []
    for left_peak, right_peak, details in matches[:5]:
        fragments = []
        if left_peak.get("two_theta") is not None and right_peak.get("two_theta") is not None:
            fragments.append(
                "2θ %.2f° ~ %.2f°" % (left_peak.get("two_theta"), right_peak.get("two_theta"))
            )
        if left_peak.get("d") is not None and right_peak.get("d") is not None:
            fragments.append("d %.2f Å ~ %.2f Å" % (left_peak.get("d"), right_peak.get("d")))
        if details.get("intensity_delta") is not None:
            fragments.append("I rel. dif. %.0f%%" % (details["intensity_delta"] * 100))
        if details.get("width_delta") is not None:
            fragments.append(
                "FWHM/largura dif. %.0f%%; peso %.2f" % (
                    details["width_delta"] * 100,
                    details.get("width_weight", 0.0),
                )
            )
        evidence.append("pico compatível: " + "; ".join(fragments))
    if not matches:
        return 0.0, ["sem picos compatíveis dentro da tolerância"]
    average_quality = sum(item[2].get("score", 0.0) for item in matches) / len(matches)
    coverage = len(matches) / max(len(left), len(right), 1)
    score = coverage * average_quality
    return round(score, 4), evidence or ["sem picos compatíveis dentro da tolerância"]


def _usable_peaks(peaks: list[dict]) -> list[dict]:
    rows = []
    for peak in peaks or []:
        two_theta = _finite_float(peak.get("two_theta") or peak.get("center_2theta"))
        d_value = _finite_float(peak.get("d") or peak.get("d_spacing") or peak.get("d_angstrom") or peak.get("center_d_angstrom"))
        if two_theta is None and d_value is None:
            continue
        relative_intensity = _finite_float(
            peak.get("relative_intensity")
            or peak.get("intensity_relative")
            or peak.get("normalized_intensity")
        )
        rows.append(
            {
                "two_theta": two_theta,
                "d": d_value,
                "relative_intensity": relative_intensity,
                "width": _finite_float(
                    peak.get("fwhm")
                    or peak.get("width_estimate")
                    or peak.get("width")
                    or peak.get("peak_width")
                ),
                "fit_quality": peak.get("fit_quality"),
                "model_name": peak.get("model_name"),
            }
        )
    rows.sort(key=lambda item: item["relative_intensity"] or 0.0, reverse=True)
    return rows[:12]


def _relative_delta(left, right) -> float | None:
    left = _finite_float(left)
    right = _finite_float(right)
    if left is None or right is None:
        return None
    scale = max(abs(left), abs(right), 1.0)
    return abs(left - right) / scale


def _width_weight(left_peak: dict, right_peak: dict) -> float:
    text = " ".join(
        str(value or "").lower()
        for peak in (left_peak, right_peak)
        for value in (peak.get("fit_quality"), peak.get("model_name"), peak.get("fit_method"))
    )
    if any(marker in text for marker in ("low", "fallback", "failed", "measured_fallback")):
        return 0.05
    if any(marker in text for marker in ("medium", "measured")):
        return 0.10
    return 0.15


def compare_curves(source: dict, target: dict) -> dict:
    """Compare two DRX curve dictionaries and return a combined score."""
    grid = common_two_theta_grid(source.get("two_theta") or [], target.get("two_theta") or [])
    left = normalize_intensity(resample_curve(source.get("two_theta") or [], source.get("intensity") or [], grid))
    right = normalize_intensity(resample_curve(target.get("two_theta") or [], target.get("intensity") or [], grid))
    correlation = correlation_similarity(left, right)
    euclidean = euclidean_similarity(left, right)
    peak_score, evidence = peak_similarity(source.get("peaks") or [], target.get("peaks") or [])
    score = round((0.45 * correlation) + (0.30 * euclidean) + (0.25 * peak_score), 4)
    return {
        "target_id": target.get("id"),
        "score": score,
        "correlation": correlation,
        "euclidean_similarity": euclidean,
        "peak_similarity": peak_score,
        "evidence": evidence,
    }


def rank_similar_curves(source: dict, curves: list[dict], top: int = 5) -> dict:
    """Rank the most similar curves to one source curve."""
    source_id = source.get("id")
    rows = []
    for target in curves:
        if target.get("id") == source_id:
            continue
        rows.append(compare_curves(source, target))
    rows.sort(key=lambda item: item["score"], reverse=True)
    return {"source_id": source_id, "similar": rows[:top]}


def build_similarity_index(curves: list[dict], top: int = 5) -> dict[str, list[dict]]:
    """Return top similarities keyed by curve id."""
    return {
        str(curve.get("id")): rank_similar_curves(curve, curves, top=top)["similar"]
        for curve in curves
        if curve.get("id")
    }
