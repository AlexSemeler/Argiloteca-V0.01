"""Mineral identification orchestration for one processed DRX curve."""

from __future__ import annotations

from .peak_detection import detect_peaks
from .webmineral_classifier import classify_peaks, load_mineral_reference


def identify_mineral_candidates(
    two_theta: list[float],
    intensity: list[float],
    reference_payload: dict | None = None,
    max_peaks: int = 14,
    top_candidates: int = 8,
) -> dict:
    """Detect peaks and classify mineral candidates.

    The function intentionally returns candidates, not confirmed minerals.
    """
    reference_payload = reference_payload or load_mineral_reference()
    peaks = detect_peaks(two_theta, intensity, max_peaks=max_peaks)
    candidates = classify_peaks(peaks, reference_payload=reference_payload, top=top_candidates)
    return {
        "peaks": peaks,
        "candidates": candidates,
        "reference_source": reference_payload.get("source"),
    }
