"""Frozen N/G/C evidence is reported without reclassification or original identities."""
import csv,hashlib,io,json,zipfile
from unittest.mock import patch
import pytest
from test_admin_raw_library import store,inputs
from argiloteca.scientific.admin_raw_service import submit_trio
from argiloteca.scientific import admin_ngc_report as reports


def submit(store):
    submit_trio(store,inputs(),preparation_confirmed=True,actor='PRIVATE_ACTOR')
    return store.rows()[0]


def test_report_uses_saved_evidence_and_preserves_all_storage(store):
    row=submit(store)
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in store.uploads.rglob('*') if p.is_file()}
    with patch('argiloteca.scientific.admin_raw_service.evaluate_reference_pilot_ngc_shadow',side_effect=AssertionError('no rerun')):
        data=reports.build_report(store,row,include_curves=True)
    assert len(data['files'])==3 and len(data['curves'])==3
    assert data['existing_classifications_modified'] is False
    assert data['record_publication_performed_by_report'] is False
    assert {f['preparation'] for f in data['files']}==set('NGC')
    assert 'PRIVATE' not in json.dumps(data)
    assert data['ngc_status']=='evaluated'
    assert all(f['status'] in {'compatible','inconclusive'} for f in data['families'])
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in store.uploads.rglob('*') if p.is_file()}


def test_archive_contains_portable_report_and_all_original_curve_points(store):
    row=submit(store);data=reports.build_report(store,row,include_curves=True)
    archive=zipfile.ZipFile(io.BytesIO(reports.final_archive(store,row,data,'<html>report</html>')))
    assert set(archive.namelist())=={'relatorio-ngc.html','resultados-ngc.json','curvas-ngc.csv','LEIA-ME.txt','SHA256SUMS.txt','LICENCAS.txt'}
    values=list(csv.DictReader(io.StringIO(archive.read('curvas-ngc.csv').decode())))
    assert len(values)==3*1486 and {r['preparation'] for r in values}==set('NGC')
    assert all(r['sample_code']==row['sample_code'] for r in values)
    exported=json.loads(archive.read('resultados-ngc.json'))
    assert 'curves' not in exported and exported['analysis_fingerprint']==data['analysis_fingerprint']
    assert hashlib.sha256(archive.read('resultados-ngc.json')).hexdigest().encode() in archive.read('SHA256SUMS.txt')
    assert b'PRIVATE' not in archive.read('resultados-ngc.json')
    assert all(not name.endswith('.raw') for name in archive.namelist())


def test_non_evaluated_context_is_explicit_and_cannot_become_confirmed(store):
    row=submit(store);path=store.uploads/row['sample_code']/'analysis.json'
    data=json.loads(path.read_text());data['ngc']={'status':'unavailable','family_context':[]}
    path.write_text(json.dumps(data));report=reports.build_report(store,row)
    assert report['ngc_status']=='unavailable' and report['families']==[]
    assert 'not_species_confirmation' in report['warnings']


def test_changed_derivative_or_analysis_provenance_blocks_report(store):
    row=submit(store);path=store.uploads/row['sample_code']/'analysis.json'
    data=json.loads(path.read_text());data['ngc']['provenance']['N']['source_sha256']='bad'
    path.write_text(json.dumps(data))
    with pytest.raises(reports.ReportUnavailable):reports.build_report(store,row)
    (store.uploads/row['sample_code']/'files'/row['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError):reports.build_report(store,row)


def test_historical_result_never_triggers_new_scientific_analysis(store):
    row=submit(store);row['classification_kind']='historical_frozen'
    with pytest.raises(reports.ReportUnavailable):reports.build_report(store,row)


def test_family_view_distinguishes_missing_peak_from_unassessed_preparation():
    view=reports.family_view({'family':'chlorite_group','observations':{'basal_by_treatment':{'N':None},'companions_ng':{}}})
    assert 'C' in view['evidence'][0]['values']
    assert 'C' not in view['evidence'][1]['values']
