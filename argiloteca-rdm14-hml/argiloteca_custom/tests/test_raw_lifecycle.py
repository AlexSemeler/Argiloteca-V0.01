"""Privacy, measurement integrity and native publication boundaries."""
import struct
import pytest
from argiloteca_drx_core.raw_lifecycle import (
    anonymize_raw101, parse_lifecycle_raw, preparation_from_name, validate_public_raw_files,
)
from .test_drx_ngc_shadow_correction import raw, group

CODE = 'ARC-0123456789ABCDEF'

def anonymous_group():
    return [(f'{CODE}_{r["treatment"]}.raw', anonymize_raw101(r['content'], CODE, r['treatment']))
            for r in group()]

def test_anonymization_erases_identifiers_and_preserves_arrays_and_original():
    content = bytearray(raw(dwell=3))
    for offset in [16, 100, 200, 326, 386, 480, 680, 980]:
        content[offset:offset+len(b'PERSON-ORIGIN-ID!')] = b'PERSON-ORIGIN-ID!'
    source = bytes(content)
    out = anonymize_raw101(source, CODE, 'N')
    assert source == bytes(content) and out != source
    assert b'PERSON-ORIGIN-ID!' not in out
    assert out[1016:] == source[1016:]
    before, after = map(parse_lifecycle_raw, [source, out])
    assert before.two_theta == after.two_theta
    assert before.intensity == after.intensity
    assert after.two_theta[0] == 2.3
    assert anonymize_raw101(out, CODE, 'N') == out

def test_complete_distinct_anonymous_trio_is_eligible():
    assert validate_public_raw_files(anonymous_group()) == [CODE]

def test_no_raw_does_not_restrict_ordinary_records():
    assert validate_public_raw_files([]) == []

@pytest.mark.parametrize('mode', ['missing','duplicate','original','wrong_name','aborted','zero_wave','same_profile'])
def test_publication_rejects_incomplete_identified_or_ambiguous_files(mode):
    files = anonymous_group()
    if mode == 'missing': files.pop()
    if mode == 'duplicate': files.append(files[0])
    if mode == 'original': files[0] = (files[0][0], raw())
    if mode == 'wrong_name': files[0] = ('IDENTIFIABLE_N.raw', files[0][1])
    if mode in {'aborted','zero_wave'}:
        b = bytearray(files[0][1])
        struct.pack_into('<I' if mode == 'aborted' else '<d', b, 8 if mode == 'aborted' else 952,
                         3 if mode == 'aborted' else 0)
        files[0] = (files[0][0], bytes(b))
    if mode == 'same_profile':
        files[1] = (files[1][0], anonymize_raw101(files[0][1], CODE, 'G'))
    with pytest.raises(ValueError): validate_public_raw_files(files)

def test_group_cannot_borrow_preparation_from_another_sample():
    files = anonymous_group()
    files[-1] = (files[-1][0].replace(CODE, 'ARC-1111111111111111'),
                 anonymize_raw101(files[-1][1], 'ARC-1111111111111111', 'C'))
    with pytest.raises(ValueError, match='trio'): validate_public_raw_files(files)

@pytest.mark.parametrize('name,expected', [('s (N).RAW',('s','N')),('s_G.raw',('s','G')),
    ('s- C.raw',('s','C')),('GREEN.raw',('GREEN',None)),('s 550.raw',('s 550',None))])
def test_preparation_requires_explicit_terminal_label(name,expected):
    assert preparation_from_name(name) == expected

def test_unproven_layout_is_never_sanitized():
    b = bytearray(raw());struct.pack_into('<I',b,12,2)
    with pytest.raises(ValueError): anonymize_raw101(bytes(b), CODE, 'N')

def test_active_policy_preserves_declared_axis_for_temporary_and_snapshot_curves(monkeypatch):
    from argiloteca.services.drx import parse_raw_bytes, align_raw_curve_for_classified_display
    from argiloteca.drx.services.temporary_curve_service import prepare_external_curve
    from argiloteca.drx.contracts.external_curve import ExternalCurveRequest
    monkeypatch.setenv('ARGILOTECA_DRX_ANONYMOUS_POLICY', '1')
    content = raw(start=3, dwell=9)
    parsed = parse_raw_bytes(content)
    assert parsed.two_theta[0] == 3
    assert align_raw_curve_for_classified_display(parsed, filename='sample_G.raw').two_theta == parsed.two_theta
    temporary = prepare_external_curve(ExternalCurveRequest(content=content, filename='sample_G.raw'))
    assert temporary.parsed.two_theta == parsed.two_theta
    assert temporary.parsed.intensity == parsed.intensity
    assert 'two_theta_offset_applied' not in temporary.parsed.metadata

def test_batch_preserves_originals_and_never_groups_across_directories(tmp_path):
    import json
    from argiloteca.drx.services.raw_lifecycle_batch import run
    source=tmp_path/'source';source.mkdir()
    patterns=group()
    for folder in ['a','b','c']:(source/folder).mkdir()
    for row in patterns:(source/'a'/('PRIVATE_'+row['treatment']+'.raw')).write_bytes(row['content'])
    (source/'b'/'PRIVATE_N.raw').write_bytes(patterns[0]['content'])
    (source/'c'/'PRIVATE_G.raw').write_bytes(patterns[1]['content'])
    (source/'c'/'PRIVATE_C.raw').write_bytes(patterns[2]['content'])
    (source/'c'/'unsupported.raw').write_bytes(b'unknown')
    before={p:p.read_bytes() for p in source.rglob('*.raw')}
    reference=tmp_path/'reference.json';reference.write_text('{"records":[]}')
    public,private=tmp_path/'public',tmp_path/'restricted'
    result=run(source,public,private,reference,'/anonymous')
    assert result['total_raw']==7 and result['analyzed']==6
    assert result['eligible_trios']==1 and result['eligible_raw']==3
    assert len(list((public/'raw').iterdir()))==3
    assert len(list((private/'anonymized-held').iterdir()))==3
    assert all(p.read_bytes()==b for p,b in before.items())
    assert all((private/'original-raw'/p.relative_to(source)).read_bytes()==b for p,b in before.items())
    assert 'PRIVATE' not in (public/'classificacao_mineralogica_raw.json').read_text()
    all_rows=json.loads((private/'all-classifications.json').read_text())['results']
    assert len(all_rows)==7
