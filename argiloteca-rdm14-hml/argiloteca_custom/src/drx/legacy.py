"""Compatibility migration from historical DRX diagnostic states to v4."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


LEGACY_STATE_MAP = {
    "confirmed_by_rules": "strongly_supported_candidate",
    "probable_by_rules": "probable_candidate",
    "possible_by_rules": "possible_candidate",
}

STATE_FIELDS = {
    "confidence",
    "forced_confidence",
    "status",
    "diagnostic_labels",
}


def migrate_legacy_state(value: Any) -> Any:
    if isinstance(value, str):
        return LEGACY_STATE_MAP.get(value, value)
    if isinstance(value, list):
        return [migrate_legacy_state(item) for item in value]
    return value


def migrate_legacy_diagnostic(payload: dict[str, Any]) -> dict[str, Any]:
    """Migrate state-bearing fields without changing observations or rules."""
    result = deepcopy(payload)

    def visit(value: Any) -> Any:
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        migrated = {}
        for key, item in value.items():
            if key in STATE_FIELDS:
                migrated[key] = migrate_legacy_state(item)
            else:
                migrated[key] = visit(item)
        return migrated

    result = visit(result)
    result["engine_version"] = "argiloteca.drx.ngc.v4"
    result["policy"] = "non_confirmatory_rule_based_evidence"
    result["policy_scope"] = "automatic_candidate_ranking_requires_curatorial_confirmation"
    result["diagnostic_labels"] = [
        "compatible_by_rules",
        "possible_candidate",
        "probable_candidate",
        "strongly_supported_candidate",
    ]
    result.setdefault("provenance", {})["legacy_migration"] = {
        "adapter": "argiloteca.drx.ngc.v3_to_v4",
        "source_engine": payload.get("engine_version", "argiloteca.drx.ngc.v3"),
        "state_map": dict(LEGACY_STATE_MAP),
        "scientific_rules_changed": False,
    }
    return result
