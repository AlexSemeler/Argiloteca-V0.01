"""Dependency-free validation primitives shared by DRX v1 contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "1.0"


class ContractValidationError(ValueError):
    """Raised when a payload violates a public DRX contract."""


def as_mapping(payload: Any, name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ContractValidationError(f"{name} deve ser um objeto.")
    return dict(payload)


def validate_version(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ContractValidationError(f"schema_version deve ser {SCHEMA_VERSION}.")


def required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field} deve ser um texto não vazio.")
    return value.strip()


def optional_text(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ContractValidationError(f"{field} deve ser texto ou nulo.")
    return value.strip() or None


def number(payload: dict[str, Any], field: str, *, required: bool = True) -> float | None:
    value = payload.get(field)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field} deve ser numérico.")
    return float(value)


def list_value(payload: dict[str, Any], field: str) -> list[Any]:
    value = payload.get(field, [])
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractValidationError(f"{field} deve ser uma lista.")
    return list(value)


def mapping_value(payload: dict[str, Any], field: str) -> dict[str, Any]:
    value = payload.get(field, {})
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{field} deve ser um objeto.")
    return dict(value)


def enum_value(enum_type, value: Any, field: str) -> str:
    try:
        return enum_type(value).value
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in enum_type)
        raise ContractValidationError(f"{field} deve ser um de: {choices}.") from exc
