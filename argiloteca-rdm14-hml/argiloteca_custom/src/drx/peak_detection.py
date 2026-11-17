"""Peak detection wrapper for the local DRX MVP."""

from __future__ import annotations

from argiloteca.drx.services.mineral_matcher import extract_peaks as _extract_peaks


def detect_peaks(
    two_theta: list[float],
    intensity: list[float],
    max_peaks: int = 14,
    smooth_window: int = 5,
    min_distance_deg: float = 0.18,
    min_prominence_ratio: float = 0.04,
) -> list[dict]:
    """Detect the main peaks in a curve, preserving d-spacing evidence."""
    return _extract_peaks(
        two_theta,
        intensity,
        max_peaks=max_peaks,
        smooth_window=smooth_window,
        min_distance_deg=min_distance_deg,
        min_prominence_ratio=min_prominence_ratio,
    )
