"""Technical pilot controls, not an independent mineralogical accuracy study."""
import copy
import json
import math
from pathlib import Path

import pytest

from argiloteca.drx.services.reference_pilot_service import (
    DEFAULT_INDEX, evaluate_reference_pilot, pilot_status, validate_curve,
)


def curve(angles=(12, 26, 41), wave=1.5406, lower=5, upper=55):
    x = [lower + i * .02 for i in range(round((upper - lower) / .02) + 1)]
    y = [10 + sum(100 * math.exp(-((v - a) / .08) ** 2) for a in angles) for v in x]
    return x, y


@pytest.fixture
def index(tmp_path):
    peaks = [{"d_angstrom": 1.5406 / (2 * math.sin(math.radians(a / 2))), "relative_intensity": 100}
             for a in (12, 26, 41)]
    row = {"reference_id": "cod:synthetic", "source_sha256": "a" * 64, "citation": "Explicit synthetic control",
           "source": "COD", "source_id": "synthetic", "mineral_id": "synthetic", "mineral_name": "Synthetic",
           "pattern_kind": "calculated", "peaks": peaks}
    p = tmp_path / "index.json"
    p.write_text(json.dumps({"schema_version": "argiloteca.drx.reference_pilot_index.v1", "index_version": "test-v1", "references": [row]}))
    return p


def evaluate(index, angles=(12, 26, 41), **kwargs):
    x, y = curve(angles)
    return evaluate_reference_pilot(x, y, enabled=True, index_path=index, wavelength_angstrom=1.5406, **kwargs)


def test_disabled_does_not_read_index_or_validate_curve():
    assert evaluate_reference_pilot(None, None, wavelength_angstrom=None)["status"] == "disabled"


def test_missing_and_invalid_index_fail_closed(tmp_path):
    assert pilot_status(enabled=True, index_path=tmp_path / "absent")["status"] == "unavailable"
    p = tmp_path / "invalid"; p.write_text('{"schema_version":"wrong"}')
    assert not pilot_status(enabled=True, index_path=p)["available"]


@pytest.mark.parametrize("x,y,wave", [([], [], 1.54), ([1]*10, [1]*10, 1.54),
    (list(range(10)), [1]*10, 1.54), (list(range(1,11)), [1]*9, 1.54),
    (list(range(1,11)), [float('nan')]*10, 1.54), (list(range(1,11)), [1]*10, None),
    (list(range(1,11)), [1]*10, 0), (list(range(1,11)), [1]*10, float('inf')),
    (list(range(1,11)), [1]*10, True)])
def test_invalid_curve(x, y, wave):
    with pytest.raises((ValueError, TypeError)):
        validate_curve(x, y, wave)


def test_two_or_more_lines_only_are_candidates(index):
    result = evaluate(index)
    assert result["candidates"][0]["matched_peak_count"] == 3
    assert result["candidates"][0]["status"] == "candidate"
    assert result["mode"] == "shadow"
    assert evaluate(index, angles=(12,))["status"] == "inconclusive"


def test_no_absence_claim_for_flat_or_unknown_curve(index):
    assert evaluate(index, angles=())["status"] == "inconclusive"
    assert evaluate(index, angles=(15, 30, 50))["status"] == "inconclusive"


def test_reference_outside_measured_range_not_penalized(index):
    x, y = curve(angles=(12, 26), upper=30)
    result = evaluate_reference_pilot(x, y, enabled=True, index_path=index, wavelength_angstrom=1.5406)
    assert result["candidates"][0]["observable_reference_peak_count"] == 2
    assert result["candidates"][0]["score"] == 1


def test_radiation_converted_from_reference_d(index):
    wave = .7093
    original = json.loads(index.read_text())["references"][0]["peaks"]
    angles = [math.degrees(2 * math.asin(wave / (2 * p["d_angstrom"]))) for p in original]
    x, y = curve(angles, lower=2, upper=40)
    result = evaluate_reference_pilot(x, y, enabled=True, index_path=index, wavelength_angstrom=wave)
    assert result["candidates"][0]["matched_peak_count"] == 3
    assert result["parameters"]["wavelength_angstrom"] == wave


def test_sources_and_structural_variants_do_not_vote_twice(index):
    doc = json.loads(index.read_text())
    other = {**doc["references"][0], "reference_id": "amcsd:synthetic", "source": "AMCSD"}
    doc["references"].append(other);index.write_text(json.dumps(doc))
    result = evaluate(index)
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["score"] == 1


def test_versions_and_parameters_change_fingerprint_without_mutation(index):
    x,y = curve();original = copy.deepcopy((x,y))
    first = evaluate_reference_pilot(x,y,enabled=True,index_path=index,wavelength_angstrom=1.5406,preparation="natural")
    second = evaluate_reference_pilot(x,y,enabled=True,index_path=index,wavelength_angstrom=1.5406,preparation="glicolado")
    assert first["analysis_fingerprint"] != second["analysis_fingerprint"]
    assert (x,y) == original
    doc=json.loads(index.read_text());doc["index_version"]="next-v2";index.write_text(json.dumps(doc))
    assert evaluate(index)["index_version"] == "next-v2"


def test_released_index_has_both_sources_and_pinned_provenance():
    data = json.loads(DEFAULT_INDEX.read_text())
    assert {r["source"] for r in data["references"]} == {"AMCSD", "COD"}
    assert len({r["mineral_id"] for r in data["references"]}) >= 10
    for row in data["references"]:
        assert len(row["source_sha256"]) == 64
        assert row["citation"] and row["license"] and row["conditions"]
        assert all(p["d_angstrom"] > 0 for p in row["peaks"])
    assert pilot_status(enabled=True)["available"]
