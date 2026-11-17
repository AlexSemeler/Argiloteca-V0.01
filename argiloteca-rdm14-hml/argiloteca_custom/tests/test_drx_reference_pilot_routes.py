"""HTTP and fail-open controls for additive shadow evidence."""
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Blueprint, Flask

from argiloteca.drx.api.reference_routes import register_reference_routes
from argiloteca.drx.contracts.external_curve import ExternalCurveRequest
from argiloteca.drx.services import external_curve_service as external


@pytest.fixture
def app():
    app = Flask(__name__)
    app.testing = True
    app.config["ARGILOTECA_DRX_REFERENCE_PILOT_ENABLED"] = True
    bp = Blueprint("reference_pilot_test", __name__)
    register_reference_routes(bp, SimpleNamespace())
    app.register_blueprint(bp)
    return app


def test_status_aliases_and_head_are_read_only(app):
    client = app.test_client()
    public = client.get('/argiloteca/drx/references/pilot')
    assert public.status_code == 200
    assert public.json == client.get('/api/argiloteca/drx/references/pilot').json
    assert client.head('/argiloteca/drx/references/pilot').status_code == 200
    assert 'manifest_path' not in public.json


@pytest.mark.parametrize('body', [None, [], {}, {'two_theta':[1]*10,'intensity':[1]*10},
    {'two_theta':list(range(1,11)), 'intensity':[1]*10,'wavelength_angstrom':0}])
def test_invalid_requests_are_400(app, body):
    assert app.test_client().post('/argiloteca/drx/references/pilot', json=body).status_code == 400


def test_disabled_and_unavailable_are_explicit_without_analysis(app):
    app.config['ARGILOTECA_DRX_REFERENCE_PILOT_ENABLED'] = False
    client = app.test_client()
    assert client.get('/argiloteca/drx/references/pilot').json['status'] == 'disabled'
    assert client.post('/argiloteca/drx/references/pilot', json={}).status_code == 503


def test_unknown_curve_is_successful_inconclusive_not_mineral_absence(app):
    response = app.test_client().post('/argiloteca/drx/references/pilot', json={
        'two_theta':list(range(1,11)), 'intensity':[1]*10, 'wavelength_angstrom':1.5406})
    assert response.status_code == 200
    assert response.json['status'] == 'inconclusive'
    assert response.json['candidates'] == []
    assert response.json['mode'] == 'shadow'


def test_reference_failure_does_not_modify_baseline_or_block_upload(tmp_path, monkeypatch):
    parsed = SimpleNamespace(two_theta=list(range(1,11)),intensity=list(range(11,21)),metadata={})
    prepared = SimpleNamespace(parsed=parsed,filename='test.xy',source_sha256='a'*64,
                               sample_code='test',treatment={'type':'unknown'})
    # Repository hash uses the actual bytes; this fixture substitutes preparation only.
    import hashlib
    prepared.source_sha256=hashlib.sha256(b'curve bytes').hexdigest()
    baseline = SimpleNamespace(advanced_processing={},preclassification={'d060':{}},
        identification={'reference_source':'baseline','candidates':[{'mineral':'Original','score':.5}]},
        advanced_summary={},advanced_curve={},analysis_run={'id':'unchanged'},diagnostic_evidence={},technical_report={})
    monkeypatch.setattr(external,'prepare_external_curve',lambda _:prepared)
    monkeypatch.setattr(external,'analyze_external_curve',lambda **_:baseline)
    monkeypatch.setattr(external,'compare_external_curve',lambda *_:{'available':False})
    monkeypatch.setattr(external,'validate_with_gsas2',lambda **_:{'available':False})
    def service(pilot):
        return external.ExternalCurveService(temporary_root=tmp_path,
            dependencies=external.ExternalCurveDependencies(mock.Mock(),mock.Mock(),mock.Mock(),mock.Mock(),pilot))
    request=ExternalCurveRequest(content=b'curve bytes',filename='test.xy')
    original=service(None).analyze(request)
    failed=service(mock.Mock(side_effect=RuntimeError('index offline'))).analyze(request)
    assert failed['metadata'].pop('reference_pilot')['status']=='unavailable'
    assert failed==original
    assert failed['mineral_candidates']==[{'mineral':'Original','score':.5}]
