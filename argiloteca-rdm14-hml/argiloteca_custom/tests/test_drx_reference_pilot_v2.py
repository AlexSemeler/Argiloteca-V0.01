"""Mechanism/regression controls for the opt-in shadow correction, not accuracy claims."""
import copy
import json
import math

import pytest

from argiloteca.drx.services.reference_pilot_service import evaluate_reference_pilot
from argiloteca.drx.services.reference_pilot_v2_service import evaluate_reference_pilot_v2, RULE


def curve(peaks=((12, 100), (26, 100), (41, 100)), wave=1.5406):
    x = [5 + i * .01 for i in range(5001)]
    y = [10 + sum(height * math.exp(-((v - angle) / .04) ** 2) for angle, height in peaks) for v in x]
    return x, y


def row(name, peaks=((12, 100), (26, 100), (41, 100)), source="AMCSD"):
    return {"reference_id": source.lower() + ":" + name, "mineral_id": name, "mineral_name": name,
            "source": source, "source_id": name, "citation": "Explicit synthetic control, no material identity",
            "source_sha256": "a" * 64, "pattern_kind": "calculated",
            "peaks": [{"d_angstrom": 1.5406 / (2 * math.sin(math.radians(angle / 2))),
                       "relative_intensity": height} for angle, height in peaks]}


def index(tmp_path, rows):
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"schema_version": "argiloteca.drx.reference_pilot_index.v1",
                                "index_version": "synthetic-control", "references": rows}))
    return path


def evaluate(path, peaks=((12, 100), (26, 100), (41, 100)), **kwargs):
    x, y = curve(peaks)
    return evaluate_reference_pilot_v2(x, y, enabled=True, index_path=path, wavelength_angstrom=1.5406, **kwargs)


def test_disabled_never_reads_index_or_curve():
    r = evaluate_reference_pilot_v2(None, None, wavelength_angstrom=None)
    assert r["status"] == "disabled" and r["candidates"] == []
    assert r["mode"] == "shadow" and r["rule_id"] == RULE


def test_unavailable_index_is_not_a_successful_zero(tmp_path):
    r = evaluate_reference_pilot_v2(None, None, enabled=True, index_path=tmp_path / "missing", wavelength_angstrom=None)
    assert r["status"] == "unavailable" and r["available"] is False


def test_perfect_equal_intensities_have_unit_similarity(tmp_path):
    r = evaluate(index(tmp_path, [row("equal")]))
    assert r["candidates"][0]["score"] == pytest.approx(1)
    assert r["candidates"][0]["status"] == "candidate"
    assert r["policy"] == "auxiliary_candidates_only_no_reclassification"
    assert "not_probability_or_mass_fraction" in r["limitations"]


def test_score_matches_independent_hand_calculation(tmp_path):
    r = evaluate(index(tmp_path, [row("unequal", ((12, 100), (26, 50)))]), ((12, 20), (26, 80)))
    # Dot((1,.5),(.25,1)) / (norm((1,.5))*norm((.25,1))).
    expected = .75 / (math.sqrt(1.25) * math.sqrt(1.0625))
    assert r["candidates"][0]["score"] == pytest.approx(expected, abs=1e-8)


def test_weak_coincidences_are_not_unit_evidence(tmp_path):
    p = index(tmp_path, [row("weak", ((12, 100), (26, 100))), row("dominant", ((20, 100), (30, 100), (35, 100)))])
    peaks = ((12, 3), (26, 3), (20, 100), (30, 100), (35, 100))
    r = evaluate(p, peaks)
    assert r["candidates"][0]["mineral_id"] == "dominant"
    weak = next(c for c in r["candidates"] if c["mineral_id"] == "weak")
    assert weak["positional_coverage"] == 1 and weak["score"] < .05


def test_all_references_scored_before_list_truncation(tmp_path):
    rows = [row(f"distractor-{i}", ((12, 100), (26, 100))) for i in range(9)]
    rows.append(row("target", ((41, 100), (50, 100), (35, 1))))
    p = index(tmp_path, rows)
    x, y = curve(((12, 3), (26, 3), (41, 100), (50, 100)))
    old = evaluate_reference_pilot(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    assert "target" not in [c["mineral_id"] for c in old["candidates"]]
    new = evaluate_reference_pilot_v2(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    assert new["candidates"][0]["mineral_id"] == "target"
    assert len(new["candidates"]) == 8


@pytest.mark.parametrize("peaks", [(), ((12, 100),), ((15, 100), (30, 100), (50, 100))])
def test_flat_single_peak_and_unrelated_curves_stay_inconclusive(tmp_path, peaks):
    assert evaluate(index(tmp_path, [row("control")]), peaks)["status"] == "inconclusive"


def test_one_observed_peak_cannot_explain_two_reference_lines(tmp_path):
    p = index(tmp_path, [row("unresolved", ((12, 100), (12.1, 80)))])
    assert evaluate(p, ((12.05, 100),))["status"] == "inconclusive"


def test_missing_strongest_reference_is_exposed(tmp_path):
    p = index(tmp_path, [row("control", ((12, 100), (26, 3), (41, 3)))])
    r = evaluate(p, ((26, 100), (41, 100)))
    assert "strongest_reference_line_unmatched" in r["candidates"][0]["diagnostic_flags"]
    assert r["candidates"][0]["score"] < .05


def test_amplitude_scaling_and_constant_background_do_not_change_score(tmp_path):
    p = index(tmp_path, [row("control")]);x, y = curve(((12, 20), (26, 80), (41, 50)))
    first = evaluate_reference_pilot_v2(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    second = evaluate_reference_pilot_v2(x, [v * 7 + 123 for v in y], enabled=True, index_path=p, wavelength_angstrom=1.5406)
    assert first["candidates"][0]["score"] == second["candidates"][0]["score"]


def test_out_of_range_reference_lines_not_penalized(tmp_path):
    p = index(tmp_path, [row("control")]);x, y = curve(((12, 100), (26, 100)))
    x, y = x[:2501], y[:2501]
    r = evaluate_reference_pilot_v2(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    assert r["candidates"][0]["score"] == pytest.approx(1)
    assert r["candidates"][0]["observable_reference_peak_count"] == 2


def test_duplicate_provider_does_not_add_evidence(tmp_path):
    p = index(tmp_path, [row("same"), row("same", source="COD")])
    r = evaluate(p)
    assert len(r["candidates"]) == 1 and r["candidates"][0]["score"] == pytest.approx(1)
    assert r["candidates"][0]["variants"] == ["cod:same"]


def test_radiation_conversion_and_provenance(tmp_path):
    p = index(tmp_path, [row("control")]);wave = .7093
    angles = [math.degrees(2 * math.asin(wave / 1.5406 * math.sin(math.radians(a / 2)))) for a in [12, 26, 41]]
    x, y = curve(tuple((a, 100) for a in angles))
    r = evaluate_reference_pilot_v2(x, y, enabled=True, index_path=p, wavelength_angstrom=wave)
    assert r["candidates"][0]["matched_peak_count"] == 3
    assert r["parameters"]["wavelength_angstrom"] == wave


def test_v1_results_and_inputs_unchanged_by_v2_call(tmp_path):
    p = index(tmp_path, [row("control")]);x, y = curve();before = copy.deepcopy((x, y))
    v1 = evaluate_reference_pilot(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    v2 = evaluate_reference_pilot_v2(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406)
    assert evaluate_reference_pilot(x, y, enabled=True, index_path=p, wavelength_angstrom=1.5406) == v1
    assert (x, y) == before
    assert v2["analysis_fingerprint"] != v1["analysis_fingerprint"]
    assert v2["schema_version"] == "argiloteca.drx.reference_pilot.v2"


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), True])
def test_invalid_reference_intensity_is_not_silently_accepted(tmp_path, invalid):
    r = row("invalid");r["peaks"][0]["relative_intensity"] = invalid
    p = index(tmp_path, [r])
    with pytest.raises((ValueError, TypeError)):
        evaluate(p)
