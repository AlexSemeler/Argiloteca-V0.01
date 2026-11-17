"""RAW parser facade used by the local DRX MVP.

This module does not implement a new RAW reader. It delegates to the parser
already used by Argiloteca and returns a small stable data object for the
dashboard/pipeline.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ARGILOTECA_CUSTOM = REPO_ROOT / "argiloteca" / "argiloteca_custom"
if str(ARGILOTECA_CUSTOM) not in sys.path:
    sys.path.insert(0, str(ARGILOTECA_CUSTOM))

from argiloteca.services.drx import RawParseError, parse_raw_file  # noqa: E402


@dataclass(frozen=True)
class RawCurve:
    raw_path: str
    two_theta: list[float]
    intensity: list[float]
    metadata: dict


def parse_raw(path: str | Path) -> RawCurve:
    """Parse a `.raw` file into 2theta/intensity arrays."""
    raw_path = Path(path)
    parsed = parse_raw_file(raw_path)
    return RawCurve(
        raw_path=str(raw_path),
        two_theta=parsed.two_theta,
        intensity=parsed.intensity,
        metadata=parsed.metadata,
    )


__all__ = ["RawCurve", "RawParseError", "parse_raw"]
