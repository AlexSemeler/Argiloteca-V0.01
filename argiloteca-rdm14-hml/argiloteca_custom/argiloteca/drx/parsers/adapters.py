"""Mutable adapters for legacy DRX consumers."""

from argiloteca_drx_core.curves import CurveData

from .registry import parse_pattern


def parse_curve_data(content: bytes, *, filename: str | None = None, expected: str | None = None) -> CurveData:
    parsed = parse_pattern(content, filename=filename, expected=expected)
    return CurveData(list(parsed.two_theta), list(parsed.intensity), dict(parsed.metadata))
