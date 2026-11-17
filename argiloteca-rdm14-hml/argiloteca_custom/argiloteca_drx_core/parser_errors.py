"""Stable error taxonomy for DRX curve parsing."""


class CurveParseError(ValueError):
    code = "curve_parse_error"


class UnsupportedCurveFormatError(CurveParseError):
    code = "unsupported_format"


class TruncatedCurveError(CurveParseError):
    code = "truncated_file"


class InvalidCurveHeaderError(CurveParseError):
    code = "invalid_header"


class CurveLimitExceededError(CurveParseError):
    code = "limit_exceeded"


class InvalidCurveSeriesError(CurveParseError):
    code = "invalid_series"
