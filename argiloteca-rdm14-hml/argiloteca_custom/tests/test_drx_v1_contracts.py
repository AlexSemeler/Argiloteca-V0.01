from __future__ import annotations

import pytest

from argiloteca.drx.contracts import (
    ContractValidationError,
    validate_curve,
    validate_diagnostic,
    validate_evidence,
    validate_mineral_candidate,
    validate_peak,
    validate_rag_response,
    validate_sample,
    validate_treatment_series,
)
from argiloteca.drx.domain import Diagnostic, Preparation, Sample, ScientificStatus


def versioned(**values):
    return {"schema_version": "1.0", **values}


def test_sample_contract_preserves_identity_preparation_and_provenance():
    payload = validate_sample(versioned(
        identifier="drx:abc", sample_code="AM-1-N", sample_base="AM-1",
        preparation="natural", record_id="abcde-fghij", sha256="abc",
        provenance={"source": "raw_snapshot"},
    ))
    assert payload["preparation"] == "natural"
    assert payload["provenance"]["source"] == "raw_snapshot"


def test_treatment_series_contract_keeps_missing_and_duplicates_explicit():
    payload = validate_treatment_series(versioned(
        natural=["n"], glicolada=["g1", "g2"], calcinada=[], indeterminada=[],
        duplicates={"glicolada": 2}, missing=["calcinada"],
    ))
    assert payload["duplicates"] == {"glicolada": 2}
    assert payload["missing"] == ["calcinada"]


def test_curve_contract_rejects_misaligned_axes():
    with pytest.raises(ContractValidationError):
        validate_curve(versioned(two_theta_deg=[2.0], intensity=[1.0, 2.0]))


def test_peak_and_evidence_contracts_preserve_scientific_fields():
    peak = validate_peak(versioned(two_theta_deg=12, d_spacing_angstrom=7.2, intensity=99,
                                   relative_intensity=100, fwhm=0.2, detection_method="scipy"))
    evidence = validate_evidence(versioned(rule_id="DRX-7A", kind="peak", observation="Pico observado",
                                           weight=0.5, source="rules_catalog.yaml", provenance={"page": 1}))
    assert peak["d_spacing_angstrom"] == 7.2
    assert evidence["rule_id"] == "DRX-7A"


def test_candidate_defaults_to_inferred_never_confirmed():
    candidate = validate_mineral_candidate(versioned(mineral="caulinita", score=0.8))
    assert candidate["status"] == "inferred"


def test_diagnostic_keeps_scientific_states_separate():
    diagnostic = validate_diagnostic(versioned(
        calculated=[{"d": 7.2}], inferred=[{"mineral": "caulinita"}], reviewed=[], confirmed=[],
        status="inconclusive", warnings=["sobreposição"], recommended_tests=["comparar N/G/C"],
        provenance={"rule_catalog": "v1"},
    ))
    assert diagnostic["inferred"] and diagnostic["confirmed"] == []


def test_rag_contract_requires_explicit_availability_and_limitations():
    payload = validate_rag_response(versioned(
        answer="Evidência auxiliar.", available=True, sources=[{"tipo_fonte": "skill_drx_painel"}],
        model="qwen", elapsed_ms=12, context_filters={"sample_code": "AM-1"},
        limitations=["Não confirma mineral."],
    ))
    assert payload["available"] is True
    assert payload["limitations"]


def test_domain_models_serialize_schema_and_enum_values():
    sample = Sample(identifier="drx:1", preparation=Preparation.NATURAL)
    diagnostic = Diagnostic(status=ScientificStatus.INCONCLUSIVE)
    assert sample.to_dict()["schema_version"] == "1.0"
    assert sample.to_dict()["preparation"] == "natural"
    assert diagnostic.to_dict()["status"] == "inconclusive"


def test_contract_rejects_unknown_schema_version():
    with pytest.raises(ContractValidationError):
        validate_sample({"schema_version": "2.0", "identifier": "drx:1"})


def test_contract_rejects_unknown_scientific_state_as_contract_error():
    with pytest.raises(ContractValidationError):
        validate_mineral_candidate(versioned(mineral="caulinita", status="automaticamente_confirmado"))
