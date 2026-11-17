"""Internal contract for temporary external DRX curve processing."""

from __future__ import annotations

from dataclasses import dataclass

from .upload import DRX_UPLOAD_CONTRACT_VERSION


@dataclass(frozen=True)
class ExternalCurveRequest:
    content: bytes
    filename: str
    sample_code: str | None = None
    record_id: str | None = None
    similarity_scope: str = "all"
    max_points: int = 3000
    wavelength_angstrom: float = 1.5406
    contract_version: str = DRX_UPLOAD_CONTRACT_VERSION
    wavelength_assumed: bool = True


@dataclass(frozen=True)
class PreparedExternalCurve:
    parsed: object
    filename: str
    sample_code: str
    treatment: dict
    source_sha256: str
    is_raw: bool

