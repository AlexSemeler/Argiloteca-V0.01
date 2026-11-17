#!/usr/bin/env python3
"""Run inside the LOCAL Invenio runtime; --exercise-import writes one dataset."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

from flask import jsonify
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.preview import iter_records
from argiloteca.openalex.tasks import run
from argiloteca.mendeley import workflow

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ready-extraction', required=True)
parser.add_argument('--blocked-extraction', required=True)
parser.add_argument('--exercise-import', action='store_true')
args = parser.parse_args()
app = create_ui()
client = app.test_client()
evidence = {}
with app.app_context():
    assert '127.0.0.1:5101' in app.config['SITE_UI_URL'], 'Only the local homologation is allowed.'
    user = db.session.get(User, 4)
    user_id = user.get_id()
    evidence['native_before'] = {'published': RDMRecordMetadata.query.count(), 'drafts': RDMDraftMetadata.query.count()}


def call(method, path, **kwargs):
    with app.app_context():
        return getattr(client, method)(path, **kwargs)


assert call('get', '/administration/mendeley/').status_code == 403
with client.session_transaction() as s:
    s['_user_id'] = user_id
    s['_fresh'] = True
    s['identity.id'] = int(user_id)
    s['identity.auth_type'] = 'session'

for lang in ('pt', 'en'):
    response = call('get', '/administration/mendeley/?ln=' + lang)
    assert response.status_code == 200, response.text[:200]
    assert response.text.count('<option value=') == 83
    assert call('get', '/administration/mendeley/publication/?ln=' + lang).status_code == 200
csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
base = '/administration/mendeley'


def post(path, data=None):
    return call('post', base + path, data={'csrf_token': csrf, **(data or {})})


for path in ('/extract', '/prepare', '/jobs/' + 'a'*32 + '/import', '/publication/preview',
             '/jobs/' + 'a'*32 + '/correct', '/jobs/' + 'a'*32 + '/resume',
             '/publication/jobs/' + 'a'*32 + '/apply'):
    assert call('post', base + path, data={}).status_code == 400, path

with patch('argiloteca.mendeley.views.enqueue', side_effect=lambda job: jsonify(job.params)):
    for values, mode in (({'free_text': 'XRD'}, 'free'), ({'term': 'kaolinite'}, 'vocabulary'),
                         ({'term': 'kaolinite', 'free_text': 'XRD OR DRX'}, 'combined')):
        response = post('/extract', values)
        assert response.status_code == 200 and response.json['search_mode'] == mode
    for values in ({}, {'term': 'unknown'}, {'term': 'kaolinite', 'offset': 1}, {'free_text': 'a'*501}):
        assert post('/extract', values).status_code == 303
evidence.update(terms=81, languages=['pt', 'en'], anonymous_denied=True, csrf=True,
                search_modes=['free', 'vocabulary', 'combined'])


def dispatch(job_id):
    with app.app_context():
        run(job_id)
        db.session.expire_all()
        job = db.session.get(OpenAlexJob, job_id)
        assert job.state in {'review', 'completed'}, (job.kind, job.state, job.result)
        return job


def new_job(path, data):
    with patch('argiloteca.openalex.tasks.run.delay'):
        response = post(path, data)
    assert response.status_code == 303, (response.status_code, response.text[:300])
    return urlsplit(response.location).path.rsplit('/', 1)[1]


# Journal the already completed real public collections, then exercise the shared dispatcher.
for jid in (args.ready_extraction, args.blocked_extraction):
    with app.app_context():
        params = json.loads((workflow.root() / (jid + '.request.json')).read_text())['params']
        if not db.session.get(OpenAlexJob, jid):
            db.session.add(OpenAlexJob(id=jid, kind='men_extract', actor=4, params=params))
            db.session.commit()
    dispatch(jid)
ready = new_job('/prepare', {'lot': 'men_' + args.ready_extraction, 'limit': 0})
blocked = new_job('/prepare', {'lot': 'men_' + args.blocked_extraction, 'limit': 0})
dispatch(ready); dispatch(blocked)
with app.app_context():
    good = db.session.get(OpenAlexJob, ready)
    row = next(iter_records(good.snapshot))
    bad = next(iter_records(db.session.get(OpenAlexJob, blocked).snapshot))
    assert row['status'] != 'bloqueado', row['issues']
    assert bad['status'] == 'bloqueado' and any(i['path'] == 'metadata.publication_date' for i in bad['issues'])
    assert bad['payload']['metadata']['publication_date'] == ''
    assert 'custom_fields' not in row['payload']
    altered = {**good.snapshot, 'records': [deepcopy(row)]}
    altered['records'][0]['payload']['metadata']['title'] = 'tamper'
    try:
        workflow.verify_snapshot(workflow.root(), altered)
        raise AssertionError('Tampered payload accepted')
    except ValueError:
        pass
    evidence.update(ready_review=ready, blocked_review=blocked, ready_doi=row['identity']['doi'],
                    blocked_missing_date=True, payload_tamper_refused=True,
                    suggested_communities=row['classification']['communities'])

for jid in (ready, blocked):
    for lang in ('pt', 'en'):
        assert call('get', base + '/jobs/' + jid + '?ln=' + lang).status_code == 200
    assert call('get', base + '/jobs/' + jid + '/report.json').status_code == 200
    assert call('get', base + '/jobs/' + jid + '/report.csv').status_code == 200
assert post('/jobs/' + blocked + '/import', {'selected': bad['key'], 'confirm': 'yes'}).status_code == 409
assert post('/jobs/' + ready + '/import', {'selected': row['key']}).status_code == 400
assert post('/jobs/' + ready + '/import', {'selected': row['key'], 'confirm': 'yes', 'community:' + row['key']: 'invalid'}).status_code == 409
assert post('/jobs/' + ready + '/correct', {'record': row['key'], 'corrections': '{"identifiers":[]}'}).status_code == 303

Path('/tmp/verified-mendeley.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))

if args.exercise_import:
    assert not row['duplicates'], 'This lifecycle test only creates a dataset absent from the local collection.'
    data = {'selected': row['key'], 'confirm': 'yes', 'community:' + row['key']: [c['id'] for c in row['classification']['communities']]}
    imported = new_job('/jobs/' + ready + '/import', data)
    assert new_job('/jobs/' + ready + '/import', data) == imported
    dispatch(imported)
    with app.app_context():
        job = db.session.get(OpenAlexJob, imported)
        outcome = job.result['items'][row['key']]
        assert outcome['state'] == 'created', outcome
        rid = outcome['draft_id']
    # Create another immutable review with a verified descriptive correction.
    corrected = new_job('/jobs/' + ready + '/correct', {'record': row['key'], 'corrections': '{"publisher":"Mendeley Data"}'})
    dispatch(corrected)
    updated = new_job('/jobs/' + corrected + '/import', data)
    dispatch(updated)
    with app.app_context():
        outcome = db.session.get(OpenAlexJob, updated).result['items'][row['key']]
        assert outcome['state'] == 'updated' and outcome['draft_id'] == rid, outcome
        from argiloteca.openalex.service import actor_identity
        from invenio_rdm_records.proxies import current_rdm_records_service as service
        draft = service.read_draft(actor_identity(4), rid).to_dict()
        assert not draft.get('is_published') and not draft['files']['enabled']
        assert len(draft['parent']['communities']['ids']) >= len(row['classification']['communities'])
        before = deepcopy(draft['metadata'])
    publishing = new_job('/jobs/' + imported + '/publication/preview', {'batch_size': 100})
    dispatch(publishing)
    with app.app_context():
        preview = db.session.get(OpenAlexJob, publishing)
        assert preview.snapshot['summary']['ready'] == 1, preview.snapshot
        plan = digest(preview.snapshot)
    assert call('get', base + '/publication/jobs/' + publishing).status_code == 200
    assert post('/publication/jobs/' + publishing + '/apply', {'confirm': 'yes', 'plan_sha256': 'bad'}).status_code == 409
    published = new_job('/publication/jobs/' + publishing + '/apply', {'confirm': 'yes', 'plan_sha256': plan})
    dispatch(published)
    assert new_job('/publication/jobs/' + publishing + '/apply', {'confirm': 'yes', 'plan_sha256': plan}) == published
    with app.app_context():
        job = db.session.get(OpenAlexJob, published)
        assert job.result['items'][row['key']]['state'] == 'published', job.result
        result = service.read(actor_identity(4), rid).to_dict()
        assert result['metadata'] == before and result['id'] == rid
        evidence.update(import_job=imported, correction_review=corrected, update_job=updated,
                        publication_preview=publishing, publication_job=published, record_id=rid,
                        same_pid_upsert=True, publication_preserved_metadata=True,
                        backups=job.result['backups'])
    Path('/tmp/verified-mendeley.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    assert call('get', '/records/' + rid).status_code == 200
    assert call('get', base + '/publication/jobs/' + published + '/backups/0').status_code == 200
    assert call('get', base + '/publication/jobs/' + published + '/report.csv').status_code == 200

# Browser test session, generated by the unchanged LOCAL session interface.
with app.app_context():
    cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
    signed = next(cookie.value for cookie in client._cookies.values() if cookie.key == cookie_name)
    Path('/tmp/mendeley-browser-state.json').write_text(json.dumps({'cookies': [{
        'name': cookie_name, 'value': signed,
        'domain': '127.0.0.1', 'path': '/', 'expires': -1, 'httpOnly': True, 'secure': True, 'sameSite': 'Lax'}], 'origins': []}))
    Path('/tmp/mendeley-browser-state.json').chmod(0o600)
    evidence['native_after'] = {'published': RDMRecordMetadata.query.count(), 'drafts': RDMDraftMetadata.query.count()}
Path('/tmp/verified-mendeley.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
print(json.dumps(evidence, ensure_ascii=False, default=str))
