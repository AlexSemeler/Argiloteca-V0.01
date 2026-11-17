"""Deterministic content-first registry over the canonical core parsers."""

from __future__ import annotations

from pathlib import Path

from argiloteca_drx_core.curves import (
    SUPPORTED_TEXT_CURVE_EXTENSIONS,
    parse_raw_bytes,
    parse_text_curve_bytes,
)
from argiloteca_drx_core.parser_errors import UnsupportedCurveFormatError

from .base import ParsedPattern


RAW_SIGNATURES = (b"RAW ", b"RAW2", b"RAW1.01")


def parse_pattern(content: bytes, *, filename: str | None = None, expected: str | None = None) -> ParsedPattern:
    suffix = Path(filename or "").suffix.lower()
    is_raw = any(content.startswith(signature) for signature in RAW_SIGNATURES)
    if is_raw:
        curve = parse_raw_bytes(content)
        curve.metadata["parser_format"] = "raw"
        return ParsedPattern.from_curve_data(curve)
    if expected == "raw" or suffix == ".raw":
        raise UnsupportedCurveFormatError("Formato .raw nao reconhecido pela assinatura do arquivo.")
    if expected == "text" or suffix in SUPPORTED_TEXT_CURVE_EXTENSIONS or not suffix:
        return ParsedPattern.from_curve_data(parse_text_curve_bytes(content, filename=filename))
    raise UnsupportedCurveFormatError("Formato de curva nao suportado.")
