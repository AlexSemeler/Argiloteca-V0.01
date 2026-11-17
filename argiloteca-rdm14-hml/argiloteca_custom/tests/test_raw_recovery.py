"""Documented binary layouts, textual uncertainty and privacy boundaries."""
import math
import struct
import pytest
from argiloteca_drx_core.raw_recovery import anonymize_recoverable,read_recoverable_pattern
from argiloteca_drx_core.raw_lifecycle import validate_public_raw_files
from argiloteca_drx_core.parser_errors import CurveParseError
from .test_drx_ngc_shadow_correction import raw as raw101

CODE='ARC-0123456789ABCDEF'
SECRET=b'PRIVATE-ORIGIN'

def legacy():
    n=21;b=bytearray(156+n*4);b[:4]=b'RAW '
    struct.pack_into('<IffI',b,4,n,7,.02,256);struct.pack_into('<f',b,24,2.5)
    struct.pack_into('<ff',b,72,1.78901,1.79289);b[40:40+len(SECRET)]=SECRET
    struct.pack_into('<%df'%n,b,156,*range(n));return bytes(b)

def raw2():
    n=21;b=bytearray(316+n*4);b[:4]=b'RAW2';struct.pack_into('<H',b,4,1)
    b[20:20+len(SECRET)]=SECRET;struct.pack_into('<fff',b,190,1.54056,1.54439,.5)
    struct.pack_into('<HH',b,256,60,n);struct.pack_into('<fff',b,264,9,.02,2.5)
    struct.pack_into('<%df'%n,b,316,*range(n));return bytes(b)

def fi():
    n=21;b=bytearray(3158+n*4);b[:4]=b'FI\0\0';b[24:26]=b'BU'
    b[104:104+len(SECRET)]=SECRET;struct.pack_into('<ddd',b,1212,1.540562,1.54439,1.392)
    struct.pack_into('<fff',b,2962,10,11,.05);struct.pack_into('<I',b,3154,n)
    struct.pack_into('<%df'%n,b,3158,*range(n));return bytes(b)

def raw4():
    n=21;p=61+80+136;offset=p+160+64;b=bytearray(offset+n*4);b[:8]=b'RAW4.00\0'
    struct.pack_into('<II',b,61,10,80);b[73:73+len(SECRET)]=SECRET
    struct.pack_into('<II',b,141,30,136);struct.pack_into('<d',b,213,1.5406)
    b[p+32:p+46]=b'Locked Coupled';struct.pack_into('<ddIf',b,p+72,10,.05,n,2)
    struct.pack_into('<d',b,p+112,1.5406);struct.pack_into('<II',b,p+136,4,64)
    struct.pack_into('<II',b,p+160,50,64);b[p+172:p+178]=b'2Theta';struct.pack_into('<d',b,p+216,10)
    struct.pack_into('<%df'%n,b,offset,*range(n));return bytes(b)

def ras():
    lines=['*RAS_DATA_START','*RAS_HEADER_START','*FILE_SAMPLE "PRIVATE-ORIGIN"',
           '*HW_COUNTER_NAME-0 "privàte"','*HW_XG_WAVE_LENGTH_ALPHA1 "1.540593"',
           '*MEAS_DATA_COUNT "11"','*MEAS_SCAN_AXIS_X_INTERNAL "TwoThetaTheta"','*MEAS_SCAN_UNIT_X "deg"',
           '*MEAS_SCAN_START "5"','*MEAS_SCAN_STOP "6"','*MEAS_SCAN_STEP "0.1"',
           '*RAS_HEADER_END','*RAS_INT_START',*[f'{5+i*.1:.1f} {10+i} {1+i%2}' for i in range(11)],
           '*RAS_INT_END','*RAS_DATA_END']
    return ('\r\n'.join(lines)+'\r\n').encode('latin1')

def gsas():
    rows=[]
    pairs=[f'{10+i:8.1f}{.5+i*.1:8.1f}' for i in range(11)]
    for i in range(0,11,5):rows.append(''.join(pairs[i:i+5]))
    # One provably repairable record-count error and missing final padding.
    return ('PRIVATE-ORIGIN\nBANK 1 11 2 CONST 300 .3 0 0 ESD\n'+'\n'.join(rows)+'\n').encode()

@pytest.mark.parametrize('factory',[legacy,raw2,fi,raw4,ras,gsas])
def test_anonymization_is_idempotent_and_preserves_every_array(factory):
    source=factory();before=bytes(source);a,ext,p=anonymize_recoverable(source,CODE,'N');q=read_recoverable_pattern(a)
    assert source==before and SECRET not in a
    assert (p.x,p.intensity,p.uncertainty,p.auxiliary)==(q.x,q.intensity,q.uncertainty,q.auxiliary)
    assert p.metadata['wavelength_angstrom']==q.metadata['wavelength_angstrom']
    assert anonymize_recoverable(a,CODE,'N')[0]==a
    assert not q.metadata['measurement_complete'] and q.metadata['requires_curatorial_release']
    if p.metadata['data_offset'] is not None:
        offset=p.metadata['data_offset'];assert a[offset:]==source[offset:]

def test_legacy_and_raw2_angles_are_not_dwell_times_and_cobalt_is_preserved():
    for content in [legacy(),raw2()]:
        p=read_recoverable_pattern(content);assert p.x[0]==2.5
    assert read_recoverable_pattern(legacy()).metadata['wavelength_angstrom']==pytest.approx(1.78901)

def test_negative_angles_are_not_fabricated_as_positive_powder_data():
    data=raw101(start=-.2)
    out,_,p=anonymize_recoverable(data,CODE,'X')
    assert p.x[0]==-.2 and read_recoverable_pattern(out).x[0]==-.2
    assert 'nonpositive_angle_scan_preserved_not_shifted_not_for_mineral_classification' in p.metadata['warnings']

def test_gsas_repairs_only_record_count_and_padding_not_scientific_units():
    out,ext,p=anonymize_recoverable(gsas(),CODE,'X');q=read_recoverable_pattern(out)
    assert ext=='.gsa' and p.metadata['record_count_repaired']
    assert p.metadata['final_record_padding_completed'] and not q.metadata['record_count_repaired']
    assert p.x[0]==300 and p.metadata['axis_kind']=='native_gsas_coordinate_unit_unverified'
    assert p.metadata['wavelength_angstrom'] is None and len(q.uncertainty)==11

@pytest.mark.parametrize('factory',[legacy,raw2,fi,raw4,ras,gsas])
def test_truncated_input_fails_closed(factory):
    with pytest.raises(CurveParseError):read_recoverable_pattern(factory()[:-20])

@pytest.mark.parametrize('factory',[legacy,raw2,fi,raw4])
def test_appended_bytes_are_not_silently_discarded(factory):
    with pytest.raises(CurveParseError):read_recoverable_pattern(factory()+b'\0'*4)

@pytest.mark.parametrize('factory,offset,fmt,value',[(legacy,152,'I',1),(raw2,4,'H',2),
    (raw2,256,'H',64),(fi,3154,'I',2_000_001),(raw4,65,'I',0)])
def test_unknown_layouts_and_limits_fail_closed(factory,offset,fmt,value):
    b=bytearray(factory());struct.pack_into('<'+fmt,b,offset,value)
    with pytest.raises(CurveParseError):read_recoverable_pattern(bytes(b))

def test_new_recovery_does_not_bypass_existing_publication_gate():
    content=anonymize_recoverable(legacy(),CODE,'N')[0]
    with pytest.raises(ValueError):validate_public_raw_files([(CODE+'_N.raw',content)])

def test_recovery_batch_keeps_originals_and_backups_and_rejects_overwrite(tmp_path):
    import hashlib,json
    from argiloteca.drx.services.raw_recovery_batch import run
    src=tmp_path/'source';backup=tmp_path/'backup';src.mkdir();backup.mkdir()
    entries=[]
    for index,content in enumerate([legacy(),gsas(),b'']):
        name=f'{CODE}_X_D{index+2}.raw'
        original=src/name;copy=backup/name;original.write_bytes(content);copy.write_bytes(content)
        entries.append({'source_path':str(original),'backup_path':str(copy),'source_sha256':hashlib.sha256(content).hexdigest(),
                        'public_code':CODE,'public_filename':name,'treatment':'X'})
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(entries));dest=tmp_path/'recovered'
    result=run(manifest,dest,tmp_path/'restricted')
    assert result['recovered']==2 and result['unrecoverable']==1
    assert result['record_publications']==0 and not result['existing_classifications_modified']
    for entry in entries:assert (src/entry['public_filename']).read_bytes()==(backup/entry['public_filename']).read_bytes()
    assert len(list((dest/'files').iterdir()))==2
    assert len(list((dest/'curves').iterdir()))==2
    assert (dest/'index.json').stat().st_mode&0o777==0o600
    with pytest.raises(ValueError,match='new recovery version'):run(manifest,dest,tmp_path/'restricted')

def test_ras_bad_numeric_header_uses_stable_error_taxonomy():
    from argiloteca_drx_core.parser_errors import InvalidCurveHeaderError
    with pytest.raises(InvalidCurveHeaderError):read_recoverable_pattern(ras().replace(b'"11"',b'"unknown"'))
