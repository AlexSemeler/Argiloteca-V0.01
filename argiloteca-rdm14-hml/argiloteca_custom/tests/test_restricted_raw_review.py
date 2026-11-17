"""Read-only review isolation, authorization ordering and filter contracts."""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Blueprint, Flask

from argiloteca.scientific import restricted_review as review


def catalogue():
    return {'schema_version': 1, 'mode': 'read_only', 'summary': {'groups': 2, 'files': 2},
        'candidates': [{'candidate_id': 'candidate-1'}],
        'groups': [
            {'code': 'ARC-AAA', 'files': [{'filename': 'ARC-AAA_N.raw'}],
             'issues': ['missing_c'], 'candidate_ids': ['candidate-1']},
            {'code': 'ARC-BBB', 'files': [{'filename': 'ARC-BBB_X.raw'}],
             'issues': ['unknown_preparation'], 'candidate_ids': []}]}


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.testing = True
    bp = Blueprint('argiloteca_scientific', __name__)
    review.register_review(bp, app)
    app.register_blueprint(bp)
    path = tmp_path / 'catalogue.json'
    path.write_text(json.dumps(catalogue()))
    app.config['ARGILOTECA_DRX_REVIEW_CATALOGUE'] = str(path)
    return app


def test_denied_access_does_not_open_catalogue(app):
    with patch.object(review, 'can_review', return_value=False), patch.object(review, 'load_catalogue') as load:
        response = app.test_client().get('/administration/drx-review/')
    assert response.status_code == 403
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert 'noindex' in response.headers['X-Robots-Tag']
    load.assert_not_called()
    assert b'ARC-' not in response.data


def test_requires_native_admin_permission_even_when_authenticated():
    from invenio_administration.permissions import administration_permission
    from flask import g
    from flask_principal import Identity
    from invenio_app.factory import create_ui
    app = create_ui()
    with app.test_request_context('/'), patch.object(review, 'current_user', SimpleNamespace(is_authenticated=True)):
        g.identity = Identity('ordinary-user')
        assert not review.can_review()
        g.identity = Identity('test-administrator')
        g.identity.provides.update(administration_permission.needs)
        assert review.can_review()
    with patch.object(review, 'current_user', SimpleNamespace(is_authenticated=False)):
        assert not review.can_review()


@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete'])
def test_no_write_methods(app, method):
    assert getattr(app.test_client(), method)('/administration/drx-review/').status_code == 405


def test_filters_and_pagination(app):
    with app.test_request_context('/'):
        data = catalogue()
        assert review.review_context(data, {'q': 'aaa'})['total'] == 1
        assert review.review_context(data, {'q': 'BBB_X.raw'})['groups'][0]['code'] == 'ARC-BBB'
        assert review.review_context(data, {'candidate': 'candidate-1'})['total'] == 1
        assert review.review_context(data, {'issue': 'missing_c'})['total'] == 1
        assert review.review_context(data, {'q': 'missing'})['total'] == 0
        assert review.review_context(data, {'page': '9999'})['page'] == 1
        for args in [{'page': 'bad'}, {'issue': '../secret'}, {'candidate': '../secret'}]:
            with pytest.raises(Exception) as error:
                review.review_context(data, args)
            assert error.value.code == 400


def test_catalogue_failure_is_explicit_503(app):
    app.config['ARGILOTECA_DRX_REVIEW_CATALOGUE'] = '/missing/catalogue.json'
    with patch.object(review, 'can_review', return_value=True), patch.object(review, 'render_template', return_value='unavailable'):
        response = app.test_client().get('/administration/drx-review/')
    assert response.status_code == 503
    assert response.data == b'unavailable'
    assert response.headers['Cache-Control'] == 'private, no-store'


def test_invalid_counts_are_not_presented(app):
    with app.app_context():
        path = app.config['ARGILOTECA_DRX_REVIEW_CATALOGUE']
        data = catalogue()
        data['summary']['files'] = 999
        with open(path, 'w') as stream:
            json.dump(data, stream)
        with pytest.raises(ValueError):
            review.load_catalogue()


def test_authorized_render_and_read_only_headers(app):
    with patch.object(review, 'can_review', return_value=True), patch.object(review, 'render_template', return_value='review') as render:
        response = app.test_client().get('/administration/drx-review/?q=AAA')
    assert response.status_code == 200
    assert render.call_args.kwargs['total'] == 1
    assert response.headers['Cache-Control'] == 'private, no-store'
