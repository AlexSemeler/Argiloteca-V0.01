"""Small preprocessing helpers for DRX curves."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_intensity(intensity: list[float]) -> list[float]:
    """Return intensity divided by the maximum finite value."""
    finite = [float(value) for value in intensity if isinstance(value, (int, float))]
    maximum = max(finite) if finite else 0.0
    if maximum <= 0:
        return [0.0 for _ in intensity]
    return [round(float(value) / maximum, 8) for value in intensity]


def decimate(two_theta: list[float], intensity: list[float], max_points: int = 5000) -> tuple[list[float], list[float]]:
    """Downsample a curve for lightweight plotting/export."""
    if len(two_theta) <= max_points:
        return two_theta, intensity
    step = max(1, round(len(two_theta) / max_points))
    return two_theta[::step], intensity[::step]
