"""Append-only administrative uploads, anonymous previews and frozen history."""
import hashlib
import io
import json
import math
import struct
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Blueprint, Flask

from argiloteca.scientific.admin_raw_store import AdminRawStore
from argiloteca.scientific import admin_raw_service as service
from argiloteca.scientific import admin_raw_views as views


def raw(role=0, wave=1.5406):
    count = 1486
    data = bytearray(1016+count*4); data[:8] = b'RAW1.01\0'
    struct.pack_into('<II',data,8,1,1); struct.pack_into('<II',data,712,304,count)
    struct.pack_into('<d',data,728,2.3); struct.pack_into('<d',data,888,.02)
    struct.pack_into('<d',data,952,wave)
    data[100:110] = b'PRIVATE-ID'
    values = [10+100*math.exp(-((2.3+i*.02-(6+role*3))/.12)**2) for i in range(count)]
    struct.pack_into('<%df'%count,data,1016,*values)
    return bytes(data)


def inputs():
    return {p: ('PRIVATE_'+p+'.raw', raw(i)) for i,p in enumerate('NGC')}


@pytest.fixture
def store(tmp_path):
    library=tmp_path/'library'; library.mkdir()
    (library/'reference.json').write_text('{"records":[]}')
    (library/'index.json').write_text('{"schema_version":1,"summary":{"files":0},"rows":[]}')
    return AdminRawStore(library,tmp_path/'uploads')


def test_submit_persists_originals_and_anonymous_profiles_without_changing_history(store):
    originals=inputs(); before=(store.library/'index.json').read_bytes()
    code=service.submit_trio(store,originals,preparation_confirmed=True,actor='test-admin')
    rows=store.rows()
    assert len(rows)==3 and all(r['access']=='restricted' and r['classification_kind']=='new_provisional' for r in rows)
    assert (store.library/'index.json').read_bytes()==before
    directory=store.uploads/code
    assert not list(store.uploads.glob('.pending-*'))
    assert 'PRIVATE' not in (directory/'manifest.json').read_text()
    assert 'PRIVATE' in (directory/'provenance.private.json').read_text()
    for row in rows:
        content=store.content(row)
        assert b'PRIVATE-ID' not in content
        assert content[1016:]==originals[row['preparation']][1][1016:]
        assert (directory/'originals'/(row['preparation']+'.raw')).read_bytes()==originals[row['preparation']][1]
        preview=service.preview(store,row['id'])
        assert preview['x'][0]==2.3 and preview['original_points']==1486
        assert len(preview['x'])<=3002
    assert directory.stat().st_mode&0o777==0o700
    assert (directory/'provenance.private.json').stat().st_mode&0o777==0o600
    # New instance/reopen proves persistence across request/process boundaries.
    assert len(AdminRawStore(store.library,store.uploads).uploaded())==3


@pytest.mark.parametrize('case',['missing','unconfirmed','duplicate','malformed','wrong_extension','missing_wave'])
def test_validation_failure_is_atomic(store,case):
    files=inputs(); confirmed=True
    if case=='missing': files.pop('C')
    if case=='unconfirmed': confirmed=False
    if case=='duplicate': files['G']=files['N']
    if case=='malformed': files['N']=('x.raw',b'RAW1.01')
    if case=='wrong_extension': files['N']=('x.exe',raw())
    if case=='missing_wave': files['N']=('x.raw',raw(wave=0))
    with pytest.raises(ValueError): service.submit_trio(store,files,preparation_confirmed=confirmed,actor='test')
    assert not store.uploads.exists()


def test_non_cu_does_not_run_cu_primary_and_remains_restricted(store):
    files={p:(p+'.raw',raw(i,wave=1.78901)) for i,p in enumerate('NGC')}
    code=service.submit_trio(store,files,preparation_confirmed=True,actor='test')
    analysis=store.analysis(code)
    assert all(r['primary']['status']=='not_applicable_wavelength' for r in analysis['by_preparation'].values())
    assert all(row['access']=='restricted' for row in store.rows())


def test_primary_and_pilot_service_failure_cannot_partially_commit(store):
    with patch.object(service,'match_reference',side_effect=RuntimeError('test')):
        with pytest.raises(RuntimeError): service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    assert not store.uploads.exists()
    with patch.object(service,'evaluate_reference_pilot_v2',side_effect=RuntimeError('test')):
        code=service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    assert store.analysis(code)['by_preparation']['N']['pilot']['status']=='unavailable'


def test_unknown_ids_and_changed_derivative_are_refused(store):
    with pytest.raises(KeyError): store.get('../../etc/passwd')
    service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    row=store.rows()[0]
    (store.uploads/row['sample_code']/'files'/row['filename']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='integrity'): store.content(row)


def test_storage_write_failure_rolls_back_only_new_staging(store):
    with patch('argiloteca.scientific.admin_raw_store.os.rename',side_effect=OSError('test')):
        with pytest.raises(OSError): service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    assert not list(store.uploads.glob('ARC-*')) and not list(store.uploads.glob('.pending-*'))
    assert (store.library/'index.json').is_file()


def test_retry_does_not_duplicate_or_replace_submission(store):
    first=service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    before=(store.uploads/first/'analysis.json').read_bytes()
    repeated=service.submit_trio(store,inputs(),preparation_confirmed=True,actor='test')
    assert repeated==first and len(store.uploaded())==3
    assert (store.uploads/first/'analysis.json').read_bytes()==before


@pytest.fixture
def app(store):
    app=Flask(__name__);app.testing=True
    app.config['ARGILOTECA_ADMIN_RAW_LIBRARY']=str(store.library)
    app.config['ARGILOTECA_ADMIN_RAW_UPLOADS']=str(store.uploads)
    bp=Blueprint('argiloteca_scientific',__name__);views.register_library(bp);app.register_blueprint(bp)
    return app


@pytest.mark.parametrize('path',['/administration/raw-library/','/administration/raw-library/'+'a'*24,'/administration/raw-library/'+'a'*24+'/curve','/administration/raw-library/'+'a'*24+'/ngc','/administration/raw-library/'+'a'*24+'/ngc/report'])
def test_library_endpoints_are_private(app,path):
    with patch.object(views,'can_review',return_value=False),patch.object(views,'store') as access:
        response=app.test_client().get(path)
    assert response.status_code==403 and response.headers['Cache-Control']=='private, no-store'
    access.assert_not_called()


def test_upload_permission_and_missing_roles_are_checked_before_service(app):
    client=app.test_client()
    with patch.object(views,'can_review',return_value=False):
        assert client.post('/administration/raw-library/trios').status_code==403
    with patch.object(views,'can_review',return_value=True),patch.object(views,'submit_trio') as submit:
        assert client.post('/administration/raw-library/trios',data={'N':(io.BytesIO(raw()),'x.raw')}).status_code==422
    submit.assert_not_called()


def test_admin_upload_route_creates_restricted_result_only(app):
    data={p:(io.BytesIO(content),name) for p,(name,content) in inputs().items()}
    data['confirm_preparations']='yes'
    with patch.object(views,'can_review',return_value=True),patch.object(views,'current_user',SimpleNamespace(get_id=lambda:'test')):
        response=app.test_client().post('/administration/raw-library/trios',data=data,headers={'Accept':'application/json'})
    assert response.status_code==201
    assert response.json['access']=='restricted' and response.json['published'] is False


def test_listing_filters_reject_invalid_parameters():
    rows=[{'filename':'ARC-EXAMPLE_N.raw','preparation':'N','access':'restricted','status':'classified','candidates':[{'mineral':'Illite'}]}]
    assert views.listing(rows,{'q':'illite'})['total']==1
    assert views.listing(rows,{'prep':'C'})['total']==0
    for args in ({'prep':'other'},{'page':'bad'},{'access':'../secret'}):
        with pytest.raises(views.InvalidLibraryFilter): views.listing(rows,args)


def test_test_flag_and_embedded_fixture_marker_block_curation(store):
    from argiloteca.scientific.admin_raw_curation import eligibility, CurationBlocked, prepare_draft, CurationLinks
    marked=inputs()
    name,content=marked['N']; content=bytearray(content)
    marker=b'ARGILOTECA_SYNTHETIC_TEST_V1'; content[100:100+len(marker)]=marker
    marked['N']=(name,bytes(content))
    service.submit_trio(store,marked,preparation_confirmed=True,actor='test')
    assert all(r['test_only'] for r in store.rows())
    assert eligibility(store,store.rows()[0])=={'eligible':False,'reason':'test_only'}
    with pytest.raises(CurationBlocked,match='test_only'):
        prepare_draft(store,store.rows()[0],CurationLinks(store.uploads/'links'),{},None)
    assert not (store.uploads/'links').exists()


def test_curation_endpoint_checks_administration_before_storage(app):
    with patch.object(views,'can_review',return_value=False),patch.object(views,'prepare_draft') as prepare:
        result=app.test_client().post('/administration/raw-library/'+'a'*24+'/prepare-draft')
    assert result.status_code==403 and result.headers['Cache-Control']=='private, no-store'
    prepare.assert_not_called()
