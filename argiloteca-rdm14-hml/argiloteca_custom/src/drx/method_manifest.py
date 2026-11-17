"""Reproducible method manifest derived from executable code and catalog."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .limits import DrxLimits
from .ngc_diagnostics import ENGINE_VERSION, POLICY
from .rules_loader import CATALOG_PATH, load_rule_catalog


MANIFEST_VERSION = "argiloteca.drx.method_manifest.v1"


def build_method_manifest() -> dict[str, Any]:
    catalog = load_rule_catalog()
    catalog_bytes = Path(CATALOG_PATH).read_bytes()
    limits = {
        "max_curve_bytes": DrxLimits.max_curve_bytes,
        "max_curve_points": DrxLimits.max_curve_points,
        "max_text_lines": DrxLimits.max_text_lines,
        "max_text_line_bytes": DrxLimits.max_text_line_bytes,
        "min_points": DrxLimits.min_points,
    }
    return {
        "version": MANIFEST_VERSION,
        "manifest_version": MANIFEST_VERSION,
        "engine_version": ENGINE_VERSION,
        "policy": POLICY,
        "catalog": {
            "version": catalog["version"],
            "sha256": hashlib.sha256(catalog_bytes).hexdigest(),
            "loader_version": catalog["loader_version"],
            "sources": catalog["catalog_sources"],
        },
        "parser": {
            "contract": "argiloteca.drx.pattern.v1",
            "formats": ["RAW legacy", "RAW1.01", "RAW2/EVA", "tabular text"],
            "limits": limits,
        },
        "limits": limits,
        "automatic_states": list(catalog["automatic_states"]),
        "curatorial_states": list(catalog["curatorial_states"]),
        "scientific_scope": "candidate_ranking_and_explainable_evidence",
        "scientific_policy": {
            "automatic_confirmation": False,
            "curatorial_review_required": True,
        },
        "limitations": [
            "Não mede acurácia mineralógica externa.",
            "Não converte evidence_score em probabilidade ou teor.",
            "Confirmação exige revisão curatorial e critérios externos adequados.",
        ],
    }


def manifest_sha256() -> str:
    encoded = json.dumps(build_method_manifest(), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
