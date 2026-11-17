from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .enums import Preparation, ScientificStatus


class SerializableModel:
    schema_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        def encode(value):
            if hasattr(value, "value"):
                return value.value
            if hasattr(value, "to_dict"):
                return value.to_dict()
            if isinstance(value, list):
                return [encode(item) for item in value]
            if isinstance(value, dict):
                return {key: encode(item) for key, item in value.items()}
            return value

        values = {key: encode(value) for key, value in asdict(self).items()}
        return {"schema_version": self.schema_version, **values}


@dataclass(frozen=True)
class Sample(SerializableModel):
    identifier: str
    sample_code: str | None = None
    sample_base: str | None = None
    preparation: Preparation = Preparation.UNDETERMINED
    record_id: str | None = None
    sha256: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TreatmentSeries(SerializableModel):
    natural: list[str] = field(default_factory=list)
    glicolada: list[str] = field(default_factory=list)
    calcinada: list[str] = field(default_factory=list)
    indeterminada: list[str] = field(default_factory=list)
    duplicates: dict[str, int] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Curve(SerializableModel):
    two_theta_deg: list[float]
    intensity: list[float]
    wavelength: float | None = None
    wavelength_unit: str = "angstrom"
    processing: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Peak(SerializableModel):
    two_theta_deg: float
    d_spacing_angstrom: float
    intensity: float
    relative_intensity: float | None = None
    fwhm: float | None = None
    detection_method: str | None = None


@dataclass(frozen=True)
class Evidence(SerializableModel):
    rule_id: str
    kind: str
    observation: str
    weight: float = 0.0
    source: str | None = None
    reference: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MineralCandidate(SerializableModel):
    mineral: str
    family: str | None = None
    score: float = 0.0
    confidence: str | None = None
    status: ScientificStatus = ScientificStatus.INFERRED
    evidence: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Diagnostic(SerializableModel):
    calculated: list[dict[str, Any]] = field(default_factory=list)
    inferred: list[dict[str, Any]] = field(default_factory=list)
    reviewed: list[dict[str, Any]] = field(default_factory=list)
    confirmed: list[dict[str, Any]] = field(default_factory=list)
    status: ScientificStatus = ScientificStatus.INCONCLUSIVE
    warnings: list[str] = field(default_factory=list)
    recommended_tests: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RagResponse(SerializableModel):
    answer: str
    available: bool
    sources: list[dict[str, Any]] = field(default_factory=list)
    model: str | None = None
    elapsed_ms: float | None = None
    context_filters: dict[str, str] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
