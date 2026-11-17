"""Framework-independent validation and bounded reading of DRX uploads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import BinaryIO, Collection

from argiloteca.drx.contracts.upload import DRX_UPLOAD_CONTRACT_VERSION, SUPPORTED_CURVE_SUFFIXES


class UploadValidationError(ValueError):
    """Raised before an invalid upload reaches permanent persistence."""


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    suffix: str
    content: bytes
    sha256: str
    contract_version: str = DRX_UPLOAD_CONTRACT_VERSION


def validate_filename(filename: str, allowed_suffixes: Collection[str] = SUPPORTED_CURVE_SUFFIXES) -> tuple[str, str]:
    raw_name = str(filename or "")
    if not raw_name or "\x00" in raw_name:
        raise UploadValidationError("Nome de arquivo ausente ou invalido.")
    path = PurePath(raw_name)
    if path.is_absolute() or path.name != raw_name or "/" in raw_name or "\\" in raw_name or raw_name in {".", ".."}:
        raise UploadValidationError("Nome de arquivo deve ser simples, sem caminho.")
    suffix = Path(raw_name).suffix.lower()
    if suffix not in {str(item).lower() for item in allowed_suffixes}:
        raise UploadValidationError("Extensao de arquivo nao permitida.")
    return raw_name, suffix


def read_validated_upload(stream: BinaryIO, *, filename: str, max_bytes: int,
                          allowed_suffixes: Collection[str] = SUPPORTED_CURVE_SUFFIXES) -> ValidatedUpload:
    safe_name, suffix = validate_filename(filename, allowed_suffixes)
    if max_bytes <= 0:
        raise ValueError("max_bytes deve ser positivo.")
    content = stream.read(max_bytes + 1)
    if not content:
        raise UploadValidationError("Arquivo vazio.")
    if len(content) > max_bytes:
        raise UploadValidationError("Arquivo excede o limite permitido.")
    return ValidatedUpload(safe_name, suffix, content, hashlib.sha256(content).hexdigest())
