"""Opt-in, single-range RAW1.01 header adapter for shadow investigations.

Not called by the canonical parser, upload service or HTTP routes. Offsets are
documented by xylib's Bruker reader (DIFFRAC plus XCH appendix A) and GSAS-II.
Only the completed, 304-byte range header with no supplemental header observed
in the CPAA corpus is accepted. Unknown layouts fail closed; no axis fitting.
"""
from __future__ import annotations

import hashlib
import math
import struct

from .curves import CurveData, _build_axis, _read_float32_series
from .parser_errors import (
    CurveLimitExceededError, InvalidCurveHeaderError, InvalidCurveSeriesError, TruncatedCurveError,
    UnsupportedCurveFormatError,
)
from .parser_limits import MAX_CURVE_BYTES, MAX_CURVE_POINTS, MIN_POINTS

RULE = "raw101-single-range-header-axis-shadow-v1"
LAYOUT_SOURCE = "https://github.com/wojdyr/xylib/blob/master/xylib/bruker_raw.cpp"


def parse_raw101_shadow(content: bytes, *, enabled=False) -> CurveData:
    """Read proven header fields without modifying bytes or any stored result."""
    if not enabled:
        raise ValueError("Experimental RAW1.01 adapter requires explicit opt-in.")
    if len(content) > MAX_CURVE_BYTES:
        raise CurveLimitExceededError("RAW exceeds byte limit.")
    if content[:7] != b"RAW1.01":
        raise UnsupportedCurveFormatError("Not a supported RAW1.01 signature.")
    if len(content) < 1016:
        raise TruncatedCurveError("Truncated RAW1.01 headers.")
    status, ranges = struct.unpack_from("<II", content, 8)
    header, count = struct.unpack_from("<II", content, 712)
    supplement = struct.unpack_from("<I", content, 968)[0]
    if (status, ranges, header, supplement) != (1, 1, 304, 0):
        raise InvalidCurveHeaderError("Unproven or incomplete RAW1.01 layout.")
    if count < MIN_POINTS:
        raise InvalidCurveSeriesError("RAW1.01 has too few declared points.")
    if count > MAX_CURVE_POINTS:
        raise CurveLimitExceededError("RAW1.01 point count outside supported bounds.")
    required = 1016 + count * 4
    if len(content) < required:
        raise TruncatedCurveError("Declared intensity vector is truncated.")
    if len(content) != required:
        raise InvalidCurveHeaderError("Unexplained bytes after declared intensity vector.")
    start = struct.unpack_from("<d", content, 728)[0]  # range +16, NOT +192
    step = struct.unpack_from("<d", content, 888)[0]   # range +176
    wave = struct.unpack_from("<d", content, 952)[0]   # range +240
    dwell = struct.unpack_from("<f", content, 904)[0]  # range +192, seconds
    if not (math.isfinite(start) and math.isfinite(step) and step > 0
            and 0 < start < start + (count - 1) * step < 180):
        raise InvalidCurveHeaderError("Invalid physical 2theta axis.")
    if not math.isfinite(wave) or not 0 < wave < 10:
        raise InvalidCurveHeaderError("Invalid declared wavelength.")
    xs = _build_axis(start, step, count)
    ys = _read_float32_series(content, 1016, count)
    return CurveData(xs, ys, {
        "contract_version": "argiloteca.drx.pattern.v1", "parser_version": RULE,
        "mode": "shadow", "axis_provenance": "declared_range_start_2theta_float64",
        "axis_calibration": "not_independently_verified", "layout_source": LAYOUT_SOURCE,
        "two_theta_start": xs[0], "two_theta_end": xs[-1], "step": step,
        "points": count, "data_offset": 1016, "detected_format": "RAW1.01 float32",
        "wavelength_angstrom": wave,
        "time_per_step_seconds": dwell if math.isfinite(dwell) else None,
        "source_sha256": hashlib.sha256(content).hexdigest(), "source_size_bytes": len(content),
        "warnings": ["experimental_adapter_not_selected_by_uploads",
                     "declared_header_axis_is_not_instrument_calibration"],
    })
