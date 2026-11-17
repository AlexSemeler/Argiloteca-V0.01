"""Versioned RAW lifecycle: declared axes and anonymous numerical derivatives.

Original bytes are never modified. Only the proven single-range RAW1.01 layout
is eligible for an anonymized RAW derivative. Other supported formats can be
analyzed but require review before any binary file is exposed or published.
"""
from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata

from .curves import CurveData, _build_axis, _read_float32_series, parse_raw_bytes
from .parser_errors import InvalidCurveHeaderError, TruncatedCurveError, CurveLimitExceededError
from .parser_limits import MAX_CURVE_BYTES

RULE = "raw-lifecycle-declared-axis-anonymous-v1"
MARKER = b"ARGILOTECA_ANON_V1"
PUBLIC_CODE = re.compile(r"ARC-[A-F0-9]{16}")
PUBLIC_FILENAME = re.compile(r"(ARC-[A-F0-9]{16})_([NGC])\.raw", re.I)


def preparation_from_name(filename):
    """Require an explicit terminal preparation; do not guess from temperatures."""
    stem = re.sub(r"\.raw$", "", unicodedata.normalize("NFC", str(filename)), flags=re.I)
    match = re.fullmatch(r"(.+?)(?:[\s._-]*\(\s*([NGC])\s*\)|[\s._-]+([NGC]))", stem, re.I)
    if not match:
        return stem.strip(), None
    return match.group(1).strip(), (match.group(2) or match.group(3)).upper()


def parse_lifecycle_raw(content):
    if len(content) > MAX_CURVE_BYTES:
        raise CurveLimitExceededError("RAW exceeds supported byte limit.")
    if content[:7] != b"RAW1.01":
        curve = parse_raw_bytes(content)
        curve.metadata.update(axis_provenance="legacy_adapter_requires_review", measurement_complete=False,
                              binary_anonymization_supported=False, lifecycle_rule=RULE)
        return curve
    if len(content) < 1016:
        raise TruncatedCurveError("RAW1.01 headers are truncated.")
    status, ranges = struct.unpack_from("<II", content, 8)
    header, count = struct.unpack_from("<II", content, 712)
    extra = struct.unpack_from("<I", content, 968)[0]
    if status not in {1, 3} or (ranges, header, extra) != (1, 304, 0):
        raise InvalidCurveHeaderError("Unproven RAW1.01 layout; original retained for review.")
    if len(content) != 1016 + count * 4:
        raise TruncatedCurveError("RAW1.01 declared point count and file length disagree.")
    start = struct.unpack_from("<d", content, 728)[0]
    step = struct.unpack_from("<d", content, 888)[0]
    wave = struct.unpack_from("<d", content, 952)[0]
    if not (math.isfinite(start) and math.isfinite(step) and step > 0 and
            0 <= start < start + (count - 1) * step < 180):
        raise InvalidCurveHeaderError("Invalid declared 2theta axis.")
    xs = _build_axis(start, step, count)
    ys = _read_float32_series(content, 1016, count)
    return CurveData(xs, ys, {
        "parser_version": RULE, "lifecycle_rule": RULE, "contract_version": "argiloteca.drx.pattern.v1",
        "detected_format": "RAW1.01 float32", "axis_provenance": "declared_range_start_2theta_float64",
        "two_theta_start": xs[0], "two_theta_end": xs[-1], "step": step, "points": count,
        "data_offset": 1016, "measurement_complete": status == 1,
        "measurement_status": "completed" if status == 1 else "aborted",
        "binary_anonymization_supported": True,
        "wavelength_angstrom": wave if math.isfinite(wave) and .1 <= wave <= 5 else None,
        "source_sha256": hashlib.sha256(content).hexdigest(), "source_size_bytes": len(content),
        "warnings": ["header_axis_not_independent_instrument_calibration"] +
                    ([] if status == 1 else ["interrupted_measurement_not_eligible_for_publication"]),
    })


def anonymize_raw101(content, public_sample_code, treatment):
    """Make a minimal declared-layout derivative; intensity bytes are identical.

Only documented numerical acquisition fields are carried forward. All free
text, dates, operator/site/sample/comment fields and reserved areas are erased.
The original remains the authoritative source for omitted instrument metadata.
"""
    if not PUBLIC_CODE.fullmatch(public_sample_code) or treatment not in {"N", "G", "C", "X"}:
        raise ValueError("A generated public sample code and explicit preparation are required.")
    parsed = parse_lifecycle_raw(content)
    if not parsed.metadata.get("binary_anonymization_supported"):
        raise InvalidCurveHeaderError("Binary anonymization is not proven for this RAW layout.")
    result = bytearray(len(content))
    result[:16] = content[:16]
    # Documented numeric instrument settings and wavelengths, not hardware IDs.
    for lo, hi in [(564, 608), (616, 656), (660, 668), (712, 776),
                   (812, 824), (888, 896), (904, 908), (920, 928), (936, 944), (952, 960)]:
        result[lo:hi] = content[lo:hi]
    anode = content[608:612].replace(b"\x00", b"").strip().upper()
    if anode in {b"CU", b"CO", b"FE", b"CR", b"MO", b"AG"}:
        result[608:608 + len(anode)] = anode
    label = (public_sample_code + "_" + treatment).encode("ascii")
    result[326:326 + len(label)] = label
    result[386:386 + len(MARKER)] = MARKER
    result[1016:] = content[1016:]
    anonymous = bytes(result)
    check = parse_lifecycle_raw(anonymous)
    if check.two_theta != parsed.two_theta or check.intensity != parsed.intensity:
        raise ValueError("Anonymization changed scientific numerical data.")
    return anonymous


def validate_public_raw_files(files):
    """Validate native publication bytes, not just a filename or UI checkbox."""
    groups = {}
    for filename, content in files:
        match = PUBLIC_FILENAME.fullmatch(filename)
        if not match:
            raise ValueError("RAWs must use anonymous ARC-…_N/G/C.raw filenames / Use nomes RAW anonimizados.")
        code, treatment = match.group(1).upper(), match.group(2).upper()
        bucket = groups.setdefault(code, {})
        if treatment in bucket:
            raise ValueError("Duplicate N/G/C preparation / Preparo N/G/C duplicado.")
        parsed = parse_lifecycle_raw(content)
        if not parsed.metadata.get("measurement_complete") or not parsed.metadata.get("wavelength_angstrom"):
            raise ValueError("Incomplete or unverified measurement / Medição incompleta ou não verificada.")
        if anonymize_raw101(content, code, treatment) != content:
            raise ValueError("RAW header is not anonymized / Cabeçalho RAW não anonimizado.")
        bucket[treatment] = hashlib.sha256(content[1016:]).hexdigest()
    for bucket in groups.values():
        if set(bucket) != {"N", "G", "C"}:
            raise ValueError("A complete N/G/C trio is required for each sample / Exigido trio N/G/C completo por amostra.")
        if len(set(bucket.values())) != 3:
            raise ValueError("Duplicated numerical profiles do not establish distinct preparations / Perfis duplicados exigem revisão.")
    return sorted(groups)
