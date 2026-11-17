"""
Projeto: Painel DRX Argiloteca

Descrição:
Dependency-light curve parsing and XRD numeric helpers.

Autores:
- Alexandre Ribas Semeler
  E-mail: alexandre.semeler@ufrgs.br



Projeto:
Argiloteca / CPAA

Licença:
Preservar licença existente no repositório.

Última revisão:
2026-06-21

Observação:
Este arquivo integra o sistema de análise, comparação e interpretação de difratogramas de raios X para argilominerais.


Fundamentacao cientifica revisada:
    Este arquivo integra o Painel DRX da Argiloteca, projeto fundamentado nas
    referencias cientificas revisadas para interpretacao auxiliar de DRX de
    argilominerais: Brindley & Brown (1980), Bailey (1980/1988),
    Moore & Reynolds (1989/1997), Drits & Tchoubar (1990),
    Lanson & Bouchet (1995), Meunier, Clays (2005), fluxograma USGS para
    identificacao de argilominerais por DRX e referencias empiricas Pre-Sal
    UFRGS/Petrobras.

Autoria cientifica e curadoria:
    Alexandre Ribas Semeler
    E-mail: alexandre.semler@ufrgs.br

Politica de interpretacao:
    Resultados mineralogicos sao auxiliares e nao confirmatorios. O codigo
    combina comportamento N/G/C, picos companheiros, d060, ambiguidades,
    contexto e proveniencia; nao confirma mineral por pico isolado.
"""

from __future__ import annotations

import math
import hashlib
import re
import struct
from dataclasses import dataclass
from pathlib import Path


from .parser_errors import (
    CurveLimitExceededError,
    CurveParseError,
    InvalidCurveHeaderError,
    InvalidCurveSeriesError,
    TruncatedCurveError,
    UnsupportedCurveFormatError,
)
from .parser_limits import (
    MAX_CURVE_BYTES,
    MAX_CURVE_POINTS,
    MAX_TEXT_LINE_BYTES,
    MAX_TEXT_LINES,
    MIN_POINTS,
)

SUPPORTED_TEXT_CURVE_EXTENSIONS = {".csv", ".txt", ".xy", ".dat"}
SUPPORTED_UPLOAD_CURVE_EXTENSIONS = {".raw", *SUPPORTED_TEXT_CURVE_EXTENSIONS}
CU_K_ALPHA_WAVELENGTH = 1.5406


@dataclass
class CurveData:
    """In-memory 1D diffractogram curve."""

    two_theta: list[float]
    intensity: list[float]
    metadata: dict


def _read_float32_series(content, offset, count):
    """
    Carrega e valida dados de entrada usados pelo fluxo, preservando rastreabilidade e tratando formatos heterogêneos sem assumir validade científica automática.
    
    Args:
        content: Valor de entrada consumido por esta etapa do fluxo.
        offset: Valor de entrada consumido por esta etapa do fluxo.
        count: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    if count < MIN_POINTS:
        raise InvalidCurveSeriesError("Arquivo .raw incompleto ou sem pontos suficientes.")
    if count > MAX_CURVE_POINTS:
        raise CurveLimitExceededError("Arquivo .raw excede o limite seguro de pontos.")
    required = offset + (count * 4)
    if offset < 0 or required > len(content):
        raise TruncatedCurveError("Arquivo .raw incompleto ou sem pontos suficientes.")
    values = (row[0] for row in struct.iter_unpack("<f", memoryview(content)[offset:required]))
    values = tuple(values)
    if not all(math.isfinite(value) for value in values):
        raise InvalidCurveSeriesError("Intensidades contem valores nao finitos.")
    return [round(float(value), 6) for value in values]


def _build_axis(start, step, count):
    """
    Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
    
    Args:
        start: Valor de entrada consumido por esta etapa do fluxo.
        step: Valor de entrada consumido por esta etapa do fluxo.
        count: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    if not math.isfinite(start) or not math.isfinite(step) or step <= 0:
        raise InvalidCurveHeaderError("Metadados de 2theta invalidos no cabecalho .raw.")
    return [round(float(start + (index * step)), 6) for index in range(count)]


def parse_raw_bytes(content):
    """Parse supported Bruker/EVA-like RAW byte layouts."""
    if len(content) > MAX_CURVE_BYTES:
        raise CurveLimitExceededError("Arquivo .raw excede o limite seguro de bytes.")
    if len(content) < 4:
        raise TruncatedCurveError("Arquivo .raw muito pequeno para conter um difratograma.")
    magic = content[:4]
    if magic == b"RAW ":
        if len(content) < 16:
            raise TruncatedCurveError("Arquivo RAW legacy truncado no cabecalho.")
        count = struct.unpack("<I", content[4:8])[0]
        start = struct.unpack("<f", content[8:12])[0]
        step = struct.unpack("<f", content[12:16])[0]
        data_offset = 156
        detected_format = "RAW legacy float32"
    elif content[:7] == b"RAW1.01":
        if len(content) < 0x3F8:
            raise TruncatedCurveError("Arquivo RAW1.01 truncado antes do vetor de intensidades.")
        if (len(content) - 0x3F8) % 4:
            raise TruncatedCurveError("Arquivo RAW1.01 possui vetor de intensidades truncado.")
        start = struct.unpack("<f", content[0x388:0x38C])[0]
        step = struct.unpack("<d", content[0x378:0x380])[0]
        data_offset = 0x3F8
        count = (len(content) - data_offset) // 4
        detected_format = "RAW1.01 float32"
    elif magic == b"RAW2":
        if len(content) < 0x110:
            raise TruncatedCurveError("Arquivo RAW2 truncado no cabecalho.")
        count = struct.unpack("<H", content[0x102:0x104])[0]
        start = struct.unpack("<f", content[0x108:0x10C])[0]
        step = struct.unpack("<f", content[0x10C:0x110])[0]
        data_offset = 0x13C
        detected_format = "RAW2 EVA float32"
    else:
        raise UnsupportedCurveFormatError("Formato .raw nao reconhecido pela assinatura do arquivo.")
    intensity = _read_float32_series(content, data_offset, count)
    two_theta = _build_axis(start, step, count)
    return CurveData(
        two_theta=two_theta,
        intensity=intensity,
        metadata={
            "two_theta_start": round(float(two_theta[0]), 6),
            "two_theta_end": round(float(two_theta[-1]), 6),
            "step": round(float(step), 8),
            "points": count,
            "detected_format": detected_format,
            "data_offset": data_offset,
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "source_size_bytes": len(content),
            "contract_version": "argiloteca.drx.pattern.v1",
            "parser_version": "argiloteca_drx_core.curves.v1",
            "warnings": [],
        },
    )


def _parse_number(value):
    """
    Carrega e valida dados de entrada usados pelo fluxo, preservando rastreabilidade e tratando formatos heterogêneos sem assumir validade científica automática.
    
    Args:
        value: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    text = str(value or "").strip().replace("\ufeff", "").strip('"').strip("'")
    if not text:
        return None
    if "," in text and "." not in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9eE+\-.]", "", text)
    if not text or text in {"+", "-", ".", "+.", "-."}:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _text_curve_columns(line):
    """
    Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
    
    Args:
        line: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    text = str(line or "").strip()
    if not text or text.startswith(("#", "//", ";")):
        return []
    tokens = re.split(r"[;\t, ]+", text)
    return [_parse_number(token) for token in tokens if str(token or "").strip()]


def parse_text_curve_bytes(content, filename=None):
    """Parse a simple two-column 2theta/intensity text curve."""
    if len(content) > MAX_CURVE_BYTES:
        raise CurveLimitExceededError("Arquivo tabular excede o limite seguro de bytes.")
    try:
        text = content.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = content.decode("latin-1")
        encoding = "latin-1"
    rows = []
    skipped_rows = 0
    lines = text.splitlines()
    if len(lines) > MAX_TEXT_LINES:
        raise CurveLimitExceededError("Arquivo tabular excede o limite seguro de linhas.")
    for line in lines:
        if len(line.encode(encoding, errors="replace")) > MAX_TEXT_LINE_BYTES:
            raise CurveLimitExceededError("Arquivo tabular contem linha excessivamente longa.")
        values = [value for value in _text_curve_columns(line) if value is not None]
        if len(values) < 2:
            skipped_rows += 1
            continue
        rows.append((float(values[0]), float(values[1])))
    rows = [(x, y) for x, y in rows if math.isfinite(x) and math.isfinite(y)]
    if len(rows) < MIN_POINTS:
        raise InvalidCurveSeriesError("Arquivo tabular sem pontos suficientes de 2theta/intensidade.")
    if len(rows) > MAX_CURVE_POINTS:
        raise CurveLimitExceededError("Arquivo tabular excede o limite seguro de pontos.")
    if not all(rows[index][0] < rows[index + 1][0] for index in range(len(rows) - 1)):
        raise InvalidCurveSeriesError("Eixo 2theta do arquivo tabular precisa estar em ordem crescente.")
    two_theta = [round(row[0], 6) for row in rows]
    intensity = [round(row[1], 6) for row in rows]
    steps = [two_theta[index + 1] - two_theta[index] for index in range(len(two_theta) - 1)]
    step = sorted(steps)[len(steps) // 2] if steps else None
    return CurveData(
        two_theta=two_theta,
        intensity=intensity,
        metadata={
            "two_theta_start": round(float(two_theta[0]), 6),
            "two_theta_end": round(float(two_theta[-1]), 6),
            "step": round(float(step), 8) if step else None,
            "points": len(two_theta),
            "detected_format": "text two-column diffractogram",
            "parser_format": "text_curve",
            "text_encoding": encoding,
            "skipped_text_rows": skipped_rows,
            "original_filename": Path(filename).name if filename else None,
            "source_sha256": hashlib.sha256(content).hexdigest(),
            "source_size_bytes": len(content),
            "contract_version": "argiloteca.drx.pattern.v1",
            "parser_version": "argiloteca_drx_core.curves.v1",
            "warnings": ["Intensidades negativas preservadas do arquivo de origem."] if any(value < 0 for value in intensity) else [],
        },
    )


def parse_curve_bytes(content, filename=None):
    """Parse an uploaded diffractogram by extension, with RAW/text fallbacks."""
    suffix = Path(filename or "").suffix.lower()
    if content.startswith((b"RAW ", b"RAW2", b"RAW1.01")):
        parsed = parse_raw_bytes(content)
        parsed.metadata["parser_format"] = "raw"
        return parsed
    if suffix == ".raw":
        raise UnsupportedCurveFormatError("Formato .raw nao reconhecido pela assinatura do arquivo.")
    if suffix in SUPPORTED_TEXT_CURVE_EXTENSIONS:
        return parse_text_curve_bytes(content, filename=filename)
    if not suffix:
        return parse_text_curve_bytes(content, filename=filename)
    raise UnsupportedCurveFormatError("Formato de curva nao suportado.")


def normalize_max(values):
    """
    Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
    
    Args:
        values: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    maximum = max([float(value) for value in values or [] if math.isfinite(float(value))] or [0.0])
    if maximum <= 0:
        return [0.0 for _ in values or []], 0.0
    return [max(float(value), 0.0) / maximum for value in values or []], maximum


def normalize_area(x_values, y_values):
    """
    Executa uma etapa coesa do fluxo do módulo, mantendo contratos de entrada e saída usados pelo painel Argiloteca.
    
    Args:
        x_values: Valor de entrada consumido por esta etapa do fluxo.
        y_values: Valor de entrada consumido por esta etapa do fluxo.
    Returns:
        Resultado produzido pela etapa, quando aplicável ao contrato do chamador.
    Raises:
        Exception: Propaga erros das dependências quando a validação ou o processamento falha.
    """
    values = [max(float(value), 0.0) for value in y_values or []]
    if len(values) < 2:
        return values, 0.0
    area = 0.0
    xs = [float(value) for value in x_values or []]
    for index in range(min(len(xs), len(values)) - 1):
        area += abs(xs[index + 1] - xs[index]) * ((values[index] + values[index + 1]) / 2.0)
    if area <= 0:
        return [0.0 for _ in values], 0.0
    return [value / area for value in values], area


def calculate_d_spacing(two_theta, wavelength=CU_K_ALPHA_WAVELENGTH):
    """Converte 2θ para d-spacing pela Lei de Bragg.

    Regra do Capitulo 3: o difratometro mede 2θ, mas a equacao usa θ. A funcao
    divide o eixo experimental por dois antes de aplicar `d = λ/(2 sen θ)`.
    """
    theta = math.radians(float(two_theta) / 2.0)
    sine = math.sin(theta)
    if sine <= 0:
        return None
    return float(wavelength) / (2.0 * sine)


def calculate_two_theta(d_spacing, wavelength=CU_K_ALPHA_WAVELENGTH):
    """Converte d-spacing para 2θ pela Lei de Bragg.

    Regra do Capitulo 3: a reflexao so e geometricamente possivel quando
    `λ/(2d) <= 1`. A funcao retorna `None` quando essa condicao falha.
    """
    value = float(d_spacing)
    if value <= 0:
        return None
    ratio = float(wavelength) / (2.0 * value)
    if ratio <= 0 or ratio > 1:
        return None
    return math.degrees(2.0 * math.asin(ratio))
