import hashlib
import math
import struct

import pytest

from argiloteca.drx.parsers import parse_pattern
from argiloteca.drx.parsers.errors import (
    CurveLimitExceededError,
    InvalidCurveHeaderError,
    InvalidCurveSeriesError,
    TruncatedCurveError,
    UnsupportedCurveFormatError,
)
from argiloteca.drx.parsers.limits import MAX_CURVE_BYTES, MAX_CURVE_POINTS, MAX_TEXT_LINE_BYTES
from argiloteca_drx_core.curves import parse_raw_bytes, parse_text_curve_bytes


def raw_legacy(points, *, count=None, start=3.0, step=0.02):
    header = bytearray(156)
    header[0:4] = b"RAW "
    header[4:8] = struct.pack("<I", len(points) if count is None else count)
    header[8:12] = struct.pack("<f", start)
    header[12:16] = struct.pack("<f", step)
    return bytes(header) + struct.pack("<" + "f" * len(points), *points)


def text_curve(rows=20):
    return ("x,y\n" + "\n".join(f"{4 + i * .1},{10 + i}" for i in range(rows))).encode()


def test_pattern_contract_carries_hash_size_and_provenance():
    content = raw_legacy(range(50))
    parsed = parse_pattern(content, filename="curve.raw")

    assert parsed.contract_version == "argiloteca.drx.pattern.v1"
    assert parsed.provenance.source_sha256 == hashlib.sha256(content).hexdigest()
    assert parsed.provenance.source_size_bytes == len(content)
    assert len(parsed.two_theta) == len(parsed.intensity) == 50


def test_registry_prefers_raw_signature_over_misleading_text_extension():
    parsed = parse_pattern(raw_legacy(range(20)), filename="curve.csv")
    assert parsed.metadata["parser_format"] == "raw"


def test_registry_rejects_unknown_raw_signature_and_unknown_extension():
    with pytest.raises(UnsupportedCurveFormatError):
        parse_pattern(b"NOPE" + b"\0" * 400, filename="curve.raw")
    with pytest.raises(UnsupportedCurveFormatError):
        parse_pattern(text_curve(), filename="curve.exe")


def test_raw_legacy_distinguishes_truncation_limits_header_and_series_errors():
    with pytest.raises(TruncatedCurveError):
        parse_raw_bytes(raw_legacy(range(10), count=20))
    with pytest.raises(CurveLimitExceededError):
        parse_raw_bytes(raw_legacy(range(10), count=MAX_CURVE_POINTS + 1))
    with pytest.raises(InvalidCurveHeaderError):
        parse_raw_bytes(raw_legacy(range(20), step=0))
    values = [float(i) for i in range(20)]
    values[5] = math.nan
    with pytest.raises(InvalidCurveSeriesError):
        parse_raw_bytes(raw_legacy(values))


def test_raw_and_text_byte_and_line_limits_are_enforced():
    with pytest.raises(CurveLimitExceededError):
        parse_raw_bytes(b"RAW " + b"\0" * MAX_CURVE_BYTES)
    content = b"x,y\n" + b"1" * (MAX_TEXT_LINE_BYTES + 1)
    with pytest.raises(CurveLimitExceededError):
        parse_text_curve_bytes(content, filename="curve.csv")


def test_text_contract_preserves_negative_intensity_with_warning():
    content = "\n".join(f"{i}, {-i}" for i in range(1, 21)).encode()
    parsed = parse_pattern(content, filename="curve.xy")

    assert min(parsed.intensity) < 0
    assert parsed.metadata["warnings"] == ["Intensidades negativas preservadas do arquivo de origem."]


def test_text_rejects_duplicate_or_decreasing_axis():
    duplicate = "\n".join(f"{1 if i == 10 else i},{i}" for i in range(20)).encode()
    with pytest.raises(InvalidCurveSeriesError):
        parse_pattern(duplicate, filename="curve.dat")
