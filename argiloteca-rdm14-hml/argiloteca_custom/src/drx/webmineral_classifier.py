"""WebMineral-compatible mineral candidate classification."""

from __future__ import annotations

import json
import os
from pathlib import Path


from argiloteca.drx.services.mineral_matcher import EMBEDDED_REFERENCE, match_reference, normalize_reference_payload


def load_mineral_reference(cache_path: str | Path | None = None, update: bool = False) -> dict:
    """Load WebMineral cache or the embedded fallback reference."""
    path = cache_path or os.environ.get('ARGILOTECA_DRX_MINERAL_REFERENCE_PATH')
    if path:
        return normalize_reference_payload(json.loads(Path(path).read_text()), path)
    return {'records': EMBEDDED_REFERENCE, 'source':'embedded_reference_fallback',
            'notes':['Configure ARGILOTECA_DRX_MINERAL_REFERENCE_PATH to retain the full local vocabulary.']}


def classify_peaks(
    peaks: list[dict],
    reference_payload: dict | None = None,
    top: int = 8,
    tolerance_d: float = 0.08,
    tolerance_two_theta: float = 0.35,
) -> list[dict]:
    """Return mineral candidates with matched peak evidence."""
    reference = (reference_payload or {}).get("records") or EMBEDDED_REFERENCE
    return match_reference(
        peaks,
        reference,
        tolerance_d=tolerance_d,
        tolerance_two_theta=tolerance_two_theta,
        top=top,
    )
