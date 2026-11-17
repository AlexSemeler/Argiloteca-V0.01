"""External-curve similarity boundary independent of Flask."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


GLOBAL_SCOPES = frozenset({"all", "global", "packages", "pacotes"})


@dataclass(frozen=True)
class SimilarityRequest:
    record_id: str | None
    scope: str
    filename: str
    source_sha256: str
    metadata: dict
    two_theta: list
    intensity: list
    detected_peaks: list
    mineral_candidates: list


def compare_external_curve(request: SimilarityRequest, compare: Callable) -> dict:
    scope = str(request.scope or "all").strip().lower()
    global_scan = scope in GLOBAL_SCOPES
    return compare(
        None if global_scan else request.record_id,
        original_filename=request.filename,
        raw_sha256=request.source_sha256,
        metadata=request.metadata,
        two_theta=request.two_theta,
        intensity=request.intensity,
        detected_peaks=request.detected_peaks,
        mineral_candidates=request.mineral_candidates,
        global_package_scan=global_scan,
    )
