from copy import deepcopy

import pytest

from src.drx.contracts import CuratorialReview, MineralCandidate, NgcComparison
from src.drx.legacy import migrate_legacy_diagnostic
from src.drx.method_manifest import build_method_manifest
from src.drx.ngc_diagnostics import interpret_ngc
from src.drx.rules_loader import DuplicateKeyError, RuleCatalogError, load_rule_catalog, validate_catalog


AUTOMATIC_STATES = {
    "compatible_by_rules",
    "possible_candidate",
    "probable_candidate",
    "strongly_supported_candidate",
}


def test_canonical_catalog_is_executable_and_resolves_legacy_source():
    catalog = load_rule_catalog()
    assert catalog["version"] == "argiloteca.drx.rules.v1"
    assert catalog["engine_version"] == "argiloteca.drx.ngc.v4"
    assert catalog["catalog_status"] == "canonical_runtime_catalog"
    assert catalog["named_ranges"]
    assert catalog["rules"]
    assert len(catalog["catalog_sources"]) == 2


def test_catalog_loader_rejects_duplicate_yaml_keys(tmp_path):
    path = tmp_path / "duplicated.yaml"
    path.write_text("version: one\nversion: two\n", encoding="utf-8")
    with pytest.raises(DuplicateKeyError):
        load_rule_catalog(path)


def test_catalog_validator_rejects_inverted_range():
    catalog = load_rule_catalog()
    invalid = deepcopy(catalog)
    invalid["named_ranges"] = {"invalid": {"d_min": 10, "d_max": 5}}
    with pytest.raises(RuleCatalogError, match="Faixa invertida"):
        validate_catalog(invalid)


def test_legacy_migration_changes_states_not_observations():
    migrated = migrate_legacy_diagnostic({
        "engine_version": "argiloteca.drx.ngc.v3",
        "combined_candidates": [{
            "confidence": "confirmed_by_rules",
            "status": "probable_by_rules",
            "observation": "confirmed_by_rules aparece aqui como texto observado",
        }],
    })
    row = migrated["combined_candidates"][0]
    assert row["confidence"] == "strongly_supported_candidate"
    assert row["status"] == "probable_candidate"
    assert row["observation"] == "confirmed_by_rules aparece aqui como texto observado"
    assert migrated["provenance"]["legacy_migration"]["scientific_rules_changed"] is False


def test_v4_engine_emits_candidates_but_never_automatic_confirmation():
    result = interpret_ngc(
        {"N": [(14.8, 100)], "G": [(17.0, 100)], "C": [(10.0, 80)]},
        {"d060": 1.54},
    )["diagnostic_interpretation"]
    assert result["engine_version"] == "argiloteca.drx.ngc.v4"
    assert result["policy"] == "non_confirmatory_rule_based_evidence"
    assert "curator_confirmed" not in result["diagnostic_labels"]
    for field in ("combined_candidates", "chapter7_rule_candidates", "mixed_layer_candidates"):
        for candidate in result.get(field, []):
            assert candidate["confidence"] in AUTOMATIC_STATES
            assert 0 <= candidate["evidence_score"] <= 100
            assert "confirmado" not in candidate["confidence"]


def test_versioned_contracts_keep_curatorial_review_separate():
    automatic = NgcComparison(candidates=[MineralCandidate(
        mineral="smectite",
        status="probable_candidate",
        score=62.0,
    ).to_dict()]).to_dict()
    review = CuratorialReview(
        decision="curator_confirmed",
        reviewer="curator-id",
        reviewed_at="2026-09-01T00:00:00Z",
        justification="Tratamentos diagnósticos e contexto laboratorial revisados.",
        result_sha256="0" * 64,
    ).to_dict()
    assert automatic["contract_version"] == "argiloteca.drx.ngc.v4"
    assert review["contract_version"] == "argiloteca.drx.curatorial_review.v1"
    assert review["decision"] == "curator_confirmed"


def test_method_manifest_records_versions_limits_and_non_confirmation_policy():
    manifest = build_method_manifest()
    assert manifest["manifest_version"] == "argiloteca.drx.method_manifest.v1"
    assert manifest["engine_version"] == "argiloteca.drx.ngc.v4"
    assert manifest["limits"]["max_curve_bytes"] == 64 * 1024 * 1024
    assert manifest["scientific_policy"]["automatic_confirmation"] is False
