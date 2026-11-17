"""Re-export the canonical dependency-light parser error taxonomy."""

from argiloteca_drx_core.parser_errors import (
    CurveLimitExceededError,
    CurveParseError,
    InvalidCurveHeaderError,
    InvalidCurveSeriesError,
    TruncatedCurveError,
    UnsupportedCurveFormatError,
)

__all__ = [
    "CurveParseError", "UnsupportedCurveFormatError", "TruncatedCurveError",
    "InvalidCurveHeaderError", "CurveLimitExceededError", "InvalidCurveSeriesError",
]
