"""Fail-closed loader for the canonical executable DRX rule catalog."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


CATALOG_PATH = Path(__file__).with_name("rules_catalog.yaml")
LOADER_VERSION = "argiloteca.drx.rules_loader.1"


class RuleCatalogError(ValueError):
    pass


class DuplicateKeyError(RuleCatalogError):
    pass


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKeyError(f"Chave YAML duplicada: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise RuleCatalogError(f"Falha ao carregar catálogo: {path}") from exc
    if not isinstance(payload, dict):
        raise RuleCatalogError(f"Catálogo deve ser um objeto YAML: {path}")
    return payload


def _validate_range(name: str, row: Any) -> None:
    if not isinstance(row, dict):
        raise RuleCatalogError(f"Faixa inválida: {name}")
    low = row.get("d_min")
    high = row.get("d_max")
    if low is not None and high is not None and float(low) > float(high):
        raise RuleCatalogError(f"Faixa invertida: {name}")
    target = row.get("target")
    if target is not None and low is not None and high is not None:
        if not float(low) <= float(target) <= float(high):
            raise RuleCatalogError(f"Alvo fora da faixa: {name}")


def validate_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    if catalog.get("version") != "argiloteca.drx.rules.v1":
        raise RuleCatalogError("Versão canônica do catálogo ausente ou incompatível.")
    if catalog.get("engine_version") != "argiloteca.drx.ngc.v4":
        raise RuleCatalogError("Catálogo não está associado à engine N/G/C v4.")
    if catalog.get("catalog_status") != "canonical_runtime_catalog":
        raise RuleCatalogError("Catálogo não está habilitado como fonte executável.")
    weights = catalog.get("score_weights") or {}
    if abs(sum(float(value) for value in weights.values()) - 1.0) > 1e-9:
        raise RuleCatalogError("Pesos do evidence_score devem somar 1.")
    for name, row in (catalog.get("named_ranges") or {}).items():
        _validate_range(name, row)
    automatic = set(catalog.get("automatic_states") or [])
    curatorial = set(catalog.get("curatorial_states") or [])
    if automatic & curatorial:
        raise RuleCatalogError("Estados automáticos e curatoriais devem ser disjuntos.")
    if "curator_confirmed" in automatic:
        raise RuleCatalogError("Confirmação curatorial não pode ser automática.")
    return catalog


def load_rule_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Load, resolve imports, validate and return the runtime catalog."""
    root_path = Path(path) if path is not None else CATALOG_PATH
    root = _read_yaml(root_path)
    resolved = deepcopy(root)
    resolved["catalog_sources"] = [str(root_path.resolve())]
    for relative in root.get("imports") or []:
        imported_path = (root_path.parent / str(relative)).resolve()
        imported = _read_yaml(imported_path)
        resolved["catalog_sources"].append(str(imported_path))
        for key in (
            "source_scope",
            "units",
            "global_policy",
            "preparations",
            "named_ranges",
            "peak_sets",
            "rules",
            "diagnostic_rules",
        ):
            if key in imported:
                if key in resolved and isinstance(resolved[key], dict) and isinstance(imported[key], dict):
                    merged = deepcopy(imported[key])
                    merged.update(resolved[key])
                    resolved[key] = merged
                elif key not in resolved:
                    resolved[key] = deepcopy(imported[key])
        resolved.setdefault("imported_catalogs", []).append({
            "path": str(imported_path),
            "version": imported.get("version"),
            "catalog_status": imported.get("catalog_status"),
        })
    resolved["loader_version"] = LOADER_VERSION
    return validate_catalog(resolved)
