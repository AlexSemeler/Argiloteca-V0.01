"""Curatorial persistence and measured-curve boundaries; no production records."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import json

import numpy as np
import pytest
from flask import Flask, g
from invenio_db import db
from argiloteca.scientific import drx_links as links
from argiloteca.scientific import drx_similarity as similarity


@pytest.fixture
def database(monkeypatch):
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    with app.app_context():
        links.install_tables()
        monkeypatch.setattr(links, 'record_for', Mock(return_value=SimpleNamespace()))
        yield app
        db.session.remove()
        for model in (links.DRXLinkEvent, links.DRXRecordLink, links.DRXAnalysisRevision):
            model.__table__.drop(db.engine)


def raw(**changes):
    row = dict(id='a'*24, sha256='b'*64, access='restricted', filename='ARC-0123456789ABCDEF_N.raw',
               sample_code='ARC-0123456789ABCDEF', preparation='N', curve_available=True,
               candidates=[], points=100, wavelength_angstrom=1.54056)
    return dict(row, **changes)


def set_link(row, **changes):
    options=dict(state='pending',evidence='Source verified by curator',expected_revision=0,actor='test')
    options.update(changes)
    return links.set_link(SimpleNamespace(id='test'),row,'4rxma-end93',**options)


def test_link_revision_audit_and_idempotent_conflict(database):
    row=raw(); first=set_link(row);db.session.commit()
    assert first.state=='pending' and first.revision==1
    with pytest.raises(ValueError,match='revision_conflict'):set_link(row)
    assert links.DRXLinkEvent.query.count()==1
    set_link(row,state='confirmed',expected_revision=1);db.session.commit()
    event=links.DRXLinkEvent.query.order_by(links.DRXLinkEvent.id.desc()).first()
    assert event.before['state']=='pending' and event.after['state']=='confirmed'
    assert links.DRXRecordLink.query.count()==1
    set_link(row,state='removed',expected_revision=2);db.session.commit()
    assert links.DRXLinkEvent.query.count()==3
    assert links.metadata_bundle('4rxma-end93',{row['id']:row})['summary']['files']==0


def test_changed_derivative_is_never_silently_relinked(database):
    row=raw();set_link(row);db.session.commit()
    with pytest.raises(ValueError,match='integrity_conflict'):
        set_link(raw(sha256='c'*64),expected_revision=1)
    assert links.metadata_bundle('4rxma-end93',{row['id']:raw(sha256='c'*64)})['summary']['files']==0


@pytest.mark.parametrize('state,access,expected',[
 ('pending','restricted',0),('confirmed','restricted',0),('pending','public_snapshot',0),('confirmed','public_snapshot',1)])
def test_public_bundle_does_not_export_restricted_or_pending_details(database,state,access,expected):
    row=raw(access=access);set_link(row,state=state);db.session.commit()
    data=links.metadata_bundle('4rxma-end93',{row['id']:row})
    assert len(data['items'])==expected
    assert data['summary']['files']==1
    if not expected:
        serialized=json.dumps(data)
        assert row['filename'] not in serialized and row['sha256'] not in serialized
        assert row['sample_code'] not in serialized and row['id'] not in serialized
    else:
        assert data['items'][0]['raw_sha256']==row['sha256']
    from argiloteca.scientific.models import validator
    validator('arg_pacote_analitico.schema.json').validate(data)


def test_analysis_revisions_are_hash_bound_and_append_only(database):
    row=raw()
    db.session.add(links.DRXAnalysisRevision(raw_id=row['id'],sha256=row['sha256'],engine=links.ENGINE,result={'status':'new'}))
    db.session.commit()
    assert links.analysis_for(row)=={'status':'new'}
    assert links.analysis_for(raw(sha256='c'*64)) is None


@pytest.mark.parametrize('wave',[None,0,float('nan'),float('inf')])
def test_similarity_requires_declared_radiation(wave):
    with pytest.raises((ValueError,TypeError)):
        similarity.vector(list(range(10,30)),list(range(20)),wave)


def test_similarity_uses_same_physical_spacing_for_different_radiation():
    q=np.linspace(.03,.7,10000)
    y=10+100*np.exp(-((q-.25)/.004)**2)+60*np.exp(-((q-.5)/.005)**2)
    def pattern(wave):return similarity.vector(np.rad2deg(2*np.arcsin(q*wave/2)),y,wave)[0]
    a,b=pattern(1.54056),pattern(1.78901)
    assert np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b))>0.99999


def test_similarity_refuses_unsorted_axis():
    with pytest.raises(ValueError):similarity.vector(list(range(30,10,-1)),list(range(20)),1.54)


def test_name_coincidence_cannot_produce_exact_match(monkeypatch):
    from argiloteca.scientific import admin_raw_views,restricted_review
    app=Flask(__name__)
    from flask_babel import Babel
    Babel(app)
    row=raw(access='public_snapshot')
    repository=SimpleNamespace(rows=lambda:[row],library='lib',uploads='uploads')
    monkeypatch.setattr(admin_raw_views,'store',lambda:repository)
    monkeypatch.setattr(restricted_review,'can_review',lambda:False)
    monkeypatch.setattr(links,'item_payload',lambda row,**kw:dict(preparation='natural',id='linked:'+row['id'],record_links=[],record_id=None,mineral_candidates=[]))
    monkeypatch.setattr(similarity,'_cached_curve',lambda *a: similarity.vector(list(range(10,30)),list(range(20)),1.54))
    with app.test_request_context():
        g.identity=SimpleNamespace()
        result=similarity.compare_library(None,original_filename=row['filename'],raw_sha256='c'*64,
            metadata={'wavelength_angstrom':1.54},two_theta=list(range(10,30)),intensity=list(range(20)))
        assert result['best_match']['score']>0.99 and result['best_match']['exact'] is False
        assert result['status']!='igual'
        # No declared radiation: even identical names produce no curve result.
        result=similarity.compare_library(None,original_filename=row['filename'],metadata={})
        assert not result['available'] and result['best_match'] is None


def test_xml_exports_structured_drx_on_legacy_record(database):
    from argiloteca.scientific.xml import record_to_xml,DEFAULT_NAMESPACE
    row=raw();set_link(row);db.session.commit()
    bundle=links.metadata_bundle('4rxma-end93',{row['id']:row})
    record={'id':'4rxma-end93','metadata':{'title':'Test','publication_date':'2026-10-20','resource_type':{'id':'dataset'},'creators':[]},
            'custom_fields':{links.FIELD:[bundle]}}
    xml=record_to_xml(record)
    assert xml.get('profiled')=='false'
    assert xml.find('.//{'+DEFAULT_NAMESPACE+'}pacotes_analiticos') is not None
    assert 'ARC-' not in __import__('lxml.etree',fromlist=['tostring']).tostring(xml).decode()


def test_public_typed_drx_xml_contains_units_peaks_and_shadow_sources(database):
    from argiloteca.scientific.xml import record_to_xml,DEFAULT_NAMESPACE
    row=raw(access='public_snapshot');set_link(row,state='confirmed');db.session.commit()
    db.session.add(links.DRXAnalysisRevision(raw_id=row['id'],sha256=row['sha256'],engine=links.ENGINE,
        result={'engine':links.ENGINE,'wavelength_angstrom':1.54056,'axis_provenance':'declared',
          'primary':{'status':'evaluated','peaks':[{'two_theta':12.4,'d':7.132,'intensity':0}],
                     'candidates':[{'mineral':'Kaolinite','score':0}]},
          'pilot':{'status':'ok','candidates':[{'mineral_name':'Kaolinite','source':'AMCSD','source_id':'123','score':0.8}]}}))
    db.session.commit()
    record={'id':'4rxma-end93','metadata':{'title':'Test','publication_date':'2026-10-20','resource_type':{'id':'dataset'},'creators':[]},
            'custom_fields':{links.FIELD:[links.metadata_bundle('4rxma-end93',{row['id']:row})]}}
    xml=record_to_xml(record);ns={'a':DEFAULT_NAMESPACE}
    branch=xml.find('a:pacotes_analiticos/a:item/a:items/a:item/a:drx',ns)
    assert branch.find('a:wavelength_angstrom',ns).text=='1.54056'
    assert branch.find('a:picos/a:item/a:intensidade',ns).text=='0'
    assert branch.find('a:minerais_candidatos/a:item/a:score',ns).text=='0'
    assert branch.find('a:evidencias_estruturais/a:property[@name="mode"]',ns).text=='shadow'
    assert 'original_filename' not in __import__('lxml.etree',fromlist=['tostring']).tostring(xml).decode()


def test_reprocessing_displays_co_d_without_running_cu_matcher(monkeypatch):
    from argiloteca.scientific import drx_reprocess as processing
    curve=SimpleNamespace(x=[10,11,12,13,14,15,16,17,18,19,20],intensity=list(range(11)),
                          metadata={'wavelength_angstrom':1.78901,'axis_kind':'two_theta_degrees','axis_provenance':'declared'})
    monkeypatch.setattr(processing,'read_recoverable_pattern',lambda content:curve)
    monkeypatch.setattr(processing,'extract_peaks',lambda *a,**k:[{'two_theta':12.0,'d':7.36,'intensity':5}])
    matcher=Mock();monkeypatch.setattr(processing,'match_reference',matcher)
    monkeypatch.setattr(processing,'evaluate_reference_pilot_v2',lambda *a,**k:{'status':'ok','candidates':[]})
    result=processing.calculate(SimpleNamespace(content=lambda row:b'bytes'),raw(),[])
    assert result['primary']['status']=='not_applicable_wavelength'
    assert result['primary']['peaks'][0]['d']==round(1.78901/(2*np.sin(np.deg2rad(6))),5)
    matcher.assert_not_called()


def test_confirmed_link_does_not_override_record_read_permission(database,monkeypatch):
    row=raw(access='public_snapshot');set_link(row,state='confirmed');db.session.commit()
    forbidden=Mock(side_effect=PermissionError('private record'))
    monkeypatch.setattr(links,'record_for',forbidden)
    with database.test_request_context():
        g.identity=SimpleNamespace(id='anonymous')
        assert links.visible_links(row)==[]


def test_metadata_schema_rejects_invalid_radiation(database):
    from argiloteca.scientific.models import validator
    row=raw(access='public_snapshot');link=set_link(row,state='confirmed');db.session.commit()
    item=links.public_drx_metadata(link,row);item['wavelength_angstrom']=-1
    assert not validator('arg_drx.schema.json').is_valid(item)


def test_legacy_package_curve_contract_remains_available(monkeypatch):
    from argiloteca import views
    app=Flask(__name__)
    app.register_blueprint(views.create_blueprint(app))
    loader=Mock(return_value={'success':True,'two_theta':[10,11],'intensity':[1,2]})
    monkeypatch.setattr(views,'load_package_curve',loader)
    response=app.test_client().get('/api/argiloteca/analises/legacy-package/drx/curva?sample_code=sample&filename=file.raw')
    assert response.status_code==200 and response.json['intensity']==[1,2]
    assert loader.call_args.kwargs['sample_code']=='sample'
    assert loader.call_args.kwargs['filename']=='file.raw'
