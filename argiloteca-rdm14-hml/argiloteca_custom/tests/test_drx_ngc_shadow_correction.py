"""Synthetic layout and scientific guardrails, independent of CPAA labels/IDs."""
import copy
import hashlib
import math
import struct

import pytest

from argiloteca_drx_core.raw101_shadow import parse_raw101_shadow
from argiloteca_drx_core.parser_errors import (
    InvalidCurveHeaderError, InvalidCurveSeriesError, TruncatedCurveError,
    UnsupportedCurveFormatError, CurveLimitExceededError,
)
from argiloteca.drx.services.reference_pilot_ngc_shadow_service import evaluate_reference_pilot_ngc_shadow as evaluate


def raw(peaks=(), *, start=2.3, dwell=2, shift=0, wave=1.5406, monotonic=False):
    n, step = 1486, .02
    b = bytearray(1016 + n * 4)
    b[:8] = b"RAW1.01\x00"
    struct.pack_into("<II", b, 8, 1, 1)
    struct.pack_into("<II", b, 712, 304, n)
    struct.pack_into("<dd", b, 720, start / 2, start)
    struct.pack_into("<d", b, 888, step)
    struct.pack_into("<f", b, 904, dwell)
    struct.pack_into("<d", b, 952, wave)
    angles = [(math.degrees(2 * math.asin(wave / (2 * d))) + shift, h) for d, h in peaks]
    values = [10 + (n - i if monotonic else 0) +
              sum(h * math.exp(-((start + i * step - a) / .12) ** 2) for a, h in angles)
              for i in range(n)]
    struct.pack_into("<%df" % n, b, 1016, *values)
    return bytes(b)


def group(kind="smectite"):
    if kind == "chlorite":
        patterns = {"N": [(14.2, 30), (7.1, 100), (3.54, 60)],
                    "G": [(14.2, 40), (7.1, 80), (3.54, 60)],
                    "C": [(14.2, 100), (7.1, 3), (3.54, 2)]}
    else:
        patterns = {"N": [(15.2, 100)], "G": [(17, 100), (8.5, 8)], "C": [(10, 100)]}
    return [{"treatment": t, "content": raw(p, dwell=i + 2)} for i, (t, p) in enumerate(patterns.items())]


def status(result, family):
    return next(r["status"] for r in result["family_context"] if r["family"] == family + "_group")


def test_disabled_requires_no_input_or_index():
    assert evaluate(None)["status"] == "disabled"
    with pytest.raises(ValueError, match="opt-in"):
        parse_raw101_shadow(b"")


def test_axis_uses_start2theta_not_dwell_and_preserves_bytes():
    a, b = raw(dwell=2), raw(dwell=3)
    original = hashlib.sha256(a).hexdigest()
    one, two = [parse_raw101_shadow(x, enabled=True) for x in [a, b]]
    assert one.two_theta == two.two_theta
    assert one.two_theta[0] == 2.3 and one.two_theta[-1] == 32
    assert one.intensity == two.intensity
    assert one.metadata["time_per_step_seconds"] == 2
    assert two.metadata["time_per_step_seconds"] == 3
    assert one.metadata["source_sha256"] == original == hashlib.sha256(a).hexdigest()


@pytest.mark.parametrize("offset,fmt,value", [(8,"I",2),(12,"I",2),(712,"I",300),(968,"I",40),
                                             (728,"d",float("nan")),(888,"d",0),(952,"d",0)])
def test_unproven_headers_fail_closed(offset, fmt, value):
    b = bytearray(raw()); struct.pack_into("<" + fmt, b, offset, value)
    with pytest.raises(InvalidCurveHeaderError):
        parse_raw101_shadow(bytes(b), enabled=True)


@pytest.mark.parametrize("data,error", [(b"RAW2",UnsupportedCurveFormatError),
    (b"RAW1.01",TruncatedCurveError),(raw()[:-4],TruncatedCurveError),
    (raw()+b"\x00"*4,InvalidCurveHeaderError)])
def test_invalid_vectors_are_not_silently_reinterpreted(data,error):
    with pytest.raises(error):
        parse_raw101_shadow(data,enabled=True)


def test_nonfinite_intensity_and_declared_count_limits():
    b = bytearray(raw()); struct.pack_into("<f",b,1016,float("inf"))
    with pytest.raises(InvalidCurveSeriesError):parse_raw101_shadow(b,enabled=True)
    struct.pack_into("<I",b,716,2_000_001)
    with pytest.raises(CurveLimitExceededError):parse_raw101_shadow(b,enabled=True)


def test_smectite_requires_expansion_collapse_and_companion():
    files = group(); before = copy.deepcopy(files)
    r = evaluate(files,enabled=True)
    assert status(r,"smectite") == "compatible"
    assert status(r,"chlorite") == "inconclusive"
    assert r["mode"] == "shadow" and r["policy"] == "auxiliary_candidates_only_no_reclassification"
    assert files == before
    assert r["analysis_fingerprint"] == evaluate(list(reversed(files)),enabled=True)["analysis_fingerprint"]


def test_chlorite_tolerates_intensity_change_without_reranking_species():
    r = evaluate(group("chlorite"),enabled=True)
    assert status(r,"chlorite") == "compatible"
    assert status(r,"smectite") == "inconclusive"
    assert r["ranking_policy"] == "unchanged_v2_per_curve_family_context_separate"
    assert "temperature_and_preparation_protocol_not_verified" in r["warnings"]
    assert all(v["rule_id"] == "pilot-cosine-peak-evidence-v2" for v in r["by_treatment"].values())


@pytest.mark.parametrize("kind", ["smectite","chlorite"])
def test_missing_calcination_cannot_supply_complete_ngc_support(kind):
    r = evaluate(group(kind)[:2],enabled=True)
    assert r["status"] == "incomplete_ngc" and status(r,kind) == "inconclusive"


def test_window_edge_of_monotonic_tail_is_not_a_reflection():
    files = [{"treatment":t,"content":raw(monotonic=True,dwell=i+2)} for i,t in enumerate("NGC")]
    r = evaluate(files,enabled=True)
    assert all(not p for p in r["profile_peaks"].values())
    assert all(c["status"] == "inconclusive" for c in r["family_context"])


def test_flat_noise_free_curve_is_inconclusive():
    r = evaluate([{"treatment":t,"content":raw(dwell=i+2)} for i,t in enumerate("NGC")],enabled=True)
    assert all(c["status"] == "inconclusive" for c in r["family_context"])


def test_glycol_single_basal_peak_cannot_be_a_complete_smectite_trajectory():
    f=group();f[1]["content"]=raw([(17,100)],dwell=3)
    assert status(evaluate(f,enabled=True),"smectite") == "inconclusive"


def test_shifted_or_conflicting_series_is_not_auto_aligned():
    f=group("chlorite");f[1]["content"]=raw([(14.2,40),(7.1,80),(3.54,60)],shift=.8,dwell=3)
    assert status(evaluate(f,enabled=True),"chlorite") == "inconclusive"


def test_two_families_in_mixture_remain_separate_hypotheses():
    a=group("chlorite");sm={"N":[(15.2,100)],"G":[(17,100),(8.5,8)],"C":[(10,100)]}
    ch={"N":[(14.2,30),(7.1,100),(3.54,60)],"G":[(14.2,40),(7.1,80),(3.54,60)],"C":[(14.2,100)]}
    for i,f in enumerate(a):f["content"]=raw(ch[f["treatment"]]+sm[f["treatment"]],dwell=i+2)
    r=evaluate(a,enabled=True)
    assert all(c["status"] == "compatible" for c in r["family_context"])


@pytest.mark.parametrize("case", ["same_bytes","same_treatment","wrong_treatment","too_many","inconsistent_wave"])
def test_invalid_grouping_cannot_create_support(case):
    f=group()
    if case=="same_bytes":f[1]["content"]=f[0]["content"]
    if case=="same_treatment":f[1]["treatment"]="N"
    if case=="wrong_treatment":f[1]["treatment"]="unknown"
    if case=="too_many":f.append(f[0])
    if case=="inconsistent_wave":f[1]["content"]=raw([(17,100),(8.5,8)],wave=1.6,dwell=3)
    with pytest.raises(ValueError):evaluate(f,enabled=True)
