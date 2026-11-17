"""Immutable public contract for parsed DRX patterns."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class PatternProvenance:
    source_sha256: str
    source_size_bytes: int
    detected_format: str
    parser_version: str


@dataclass(frozen=True)
class ParsedPattern:
    two_theta: tuple[float, ...]
    intensity: tuple[float, ...]
    metadata: Mapping[str, object]
    provenance: PatternProvenance
    contract_version: str = "argiloteca.drx.pattern.v1"

    @classmethod
    def from_curve_data(cls, curve):
        metadata = dict(curve.metadata or {})
        provenance = PatternProvenance(
            source_sha256=str(metadata.get("source_sha256") or ""),
            source_size_bytes=int(metadata.get("source_size_bytes") or 0),
            detected_format=str(metadata.get("detected_format") or ""),
            parser_version=str(metadata.get("parser_version") or ""),
        )
        return cls(tuple(curve.two_theta), tuple(curve.intensity), MappingProxyType(metadata), provenance)
