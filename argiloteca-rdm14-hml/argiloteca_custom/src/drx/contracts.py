"""Versioned scientific contracts independent of Flask and InvenioRDM."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


class Contract:
    contract_version = "argiloteca.drx.contract.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            **{key: _serialize(value) for key, value in asdict(self).items()},
        }


@dataclass(frozen=True)
class XrdFile(Contract):
    filename: str
    sha256: str
    size_bytes: int
    detected_format: str
    parser_version: str
    provenance: dict[str, Any] = field(default_factory=dict)

    contract_version = "argiloteca.drx.file.v1"


@dataclass(frozen=True)
class PreparationProtocol(Contract):
    preparation: str
    source: str | None = None
    cation: str | None = None
    solvation_agent: str | None = None
    relative_humidity: float | None = None
    temperature_c: float | None = None
    duration_minutes: float | None = None
    orientation: str | None = None
    radiation: str | None = None
    wavelength_angstrom: float | None = None
    uncertainty_notes: list[str] = field(default_factory=list)

    contract_version = "argiloteca.drx.preparation_protocol.v1"


@dataclass(frozen=True)
class DrxPattern(Contract):
    source: XrdFile
    two_theta_deg: list[float]
    intensity: list[float]
    treatment: str | None = None
    protocol: PreparationProtocol | None = None
    wavelength_angstrom: float | None = None
    wavelength_source: str | None = None
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    contract_version = "argiloteca.drx.pattern.v1"


@dataclass(frozen=True)
class Peak(Contract):
    two_theta_deg: float | None
    d_spacing_angstrom: float | None
    intensity: float
    relative_intensity: float | None = None
    fwhm_deg: float | None = None
    area: float | None = None
    method: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    contract_version = "argiloteca.drx.peak.v1"


@dataclass(frozen=True)
class Evidence(Contract):
    rule_id: str
    status: str
    observation: str
    weight: float | None = None
    source: str | None = None
    reference: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    contract_version = "argiloteca.drx.evidence.v1"


@dataclass(frozen=True)
class MineralCandidate(Contract):
    mineral: str
    status: str
    score: float | None = None
    family: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    contract_version = "argiloteca.drx.mineral_candidate.v2"


@dataclass(frozen=True)
class NgcComparison(Contract):
    candidates: list[dict[str, Any]] = field(default_factory=list)
    behaviors: list[dict[str, Any]] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    contract_version = "argiloteca.drx.ngc.v4"


@dataclass(frozen=True)
class CuratorialReview(Contract):
    decision: str
    reviewer: str
    reviewed_at: str
    justification: str
    result_sha256: str
    complementary_methods: list[str] = field(default_factory=list)
    evidence_considered: list[str] = field(default_factory=list)

    contract_version = "argiloteca.drx.curatorial_review.v1"
