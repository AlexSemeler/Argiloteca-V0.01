"""Verify overwrite on a restricted synthetic draft; published checks always roll back."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import uuid
from unittest.mock import patch

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMDraftMetadata, RDMRecordMetadata
from invenio_records_resources.services.uow import UnitOfWork
from argiloteca.openalex.adapters import converter, digest, prepare
from argiloteca.openalex.models import OpenAlexClaim, OpenAlexJob
from argiloteca.openalex.service import actor_identity, update_existing, update_payload
from argiloteca.openalex.tasks import run

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--import-job', required=True)
parser.add_argument('--published-test-id', help='Optional existing published PID; changes are rolled back')
args = parser.parse_args()
app = create_ui()
results = {}
with app.app_context():
    root = app.config['ARGILOTECA_OPENALEX_ROOT']
    original = db.session.get(OpenAlexJob, args.import_job)
    source = deepcopy(original.snapshot)
    original_outcome = next(iter(original.result['items'].values()))
    rid = original_outcome['draft_id']
    actor = original.actor
    identity = actor_identity(actor)
    current = service.read_draft(identity, rid).to_dict()
    assert current['metadata']['title'].startswith('TESTE SINTÉTICO')
    assert current['access']['record'] == 'restricted'
    # Add local curation that the bibliographic import must preserve.
    incoming = deepcopy(source['records'][0]['payload'])
    incoming['metadata']['publisher'] = 'TESTE — editora conferida localmente'
    base = update_payload(current, incoming, converter(root)[0])
    base['custom_fields']['arg:publicacao_argilominerais_relacionados'] = 'TESTE — curadoria preservada'
    service.update_draft(identity, rid, base)
    before = service.read_draft(identity, rid).to_dict()
    before_counts = (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count())
    before_claims = OpenAlexClaim.query.count()

    source['records'][0]['payload']['metadata']['title'] = 'TESTE SINTÉTICO — metadados sobrescritos no mesmo registro'
    source['records'][0]['payload_sha256'] = digest(source['records'][0]['payload'])
    def job_for(snapshot):
        job = OpenAlexJob(kind='import', actor=actor, snapshot=deepcopy(snapshot), params={
            'selected':[r['key'] for r in snapshot['records']], 'existing_policy':'overwrite',
            'source_job':original.params.get('source_job'), 'test_only':True,
            'signature':'test-upsert-'+uuid.uuid4().hex})
        db.session.add(job);db.session.commit()
        return job.id

    jid = job_for(source)
    run(jid)
    job = db.session.get(OpenAlexJob, jid)
    assert job.state == 'completed', job.result
    assert job.result['summary'] == {'created':0, 'updated':1, 'duplicate':0}, job.result
    outcome = next(iter(job.result['items'].values()))
    assert outcome['draft_id'] == rid and outcome['record_id'] == rid
    assert outcome['before']['metadata']['title'] == before['metadata']['title']
    after = service.read_draft(identity, rid).to_dict()
    assert after['metadata']['title'] == source['records'][0]['payload']['metadata']['title']
    assert after['metadata']['publisher'] == before['metadata']['publisher']
    assert after['custom_fields'] == before['custom_fields']
    assert after['access'] == before['access']
    assert after['files'] == before['files']
    assert after['parent']['access']['owned_by'] == before['parent']['access']['owned_by']
    assert not after.get('errors')
    assert (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count()) == before_counts
    assert OpenAlexClaim.query.count() == before_claims
    results['overwrite_same_pid'] = {'job':jid, 'id':rid, 'created':0, 'updated':1,
        'title_persisted':True, 'curation_files_access_owner_preserved':True, 'before_snapshot_saved':True}

    # A redelivery must not increment the revision or overwrite again.
    revision = service.read_draft(identity, rid)._record.revision_id
    run(jid)
    job = db.session.get(OpenAlexJob,jid)
    job.state = 'queued';db.session.commit()
    run(jid)
    assert service.read_draft(identity, rid)._record.revision_id == revision
    assert (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count()) == before_counts
    results['redelivery_and_resume_no_new_record'] = True

    # Roll back a failed update, rather than creating a replacement.
    failing = deepcopy(source)
    failing['records'][0]['payload']['metadata']['title'] = 'TESTE SINTÉTICO — esta alteração deve ser desfeita'
    failing['records'][0]['payload_sha256'] = digest(failing['records'][0]['payload'])
    failure_id = job_for(failing)
    with patch('invenio_records_resources.services.uow.UnitOfWork.commit', side_effect=RuntimeError('synthetic update precommit failure')):
        run(failure_id)
    assert db.session.get(OpenAlexJob,failure_id).state == 'failed'
    model_id = service.read_draft(identity, rid)._record.model.id
    persisted = db.session.query(RDMDraftMetadata.json).filter_by(id=model_id).one()[0]
    assert persisted['metadata']['title'] == after['metadata']['title']
    assert (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count()) == before_counts
    assert OpenAlexClaim.query.count() == before_claims
    failed = db.session.get(OpenAlexJob,failure_id)
    failed.result = {**failed.result, 'error':'TESTE SINTÉTICO: falha de atualização simulada; rollback confirmado e nenhum registro novo.'}
    db.session.commit()
    results['failed_update_rolled_back_without_create'] = True

    # A runtime collision must fail even if an old review missed it.
    collision_id = job_for(source)
    metadata = converter(root)[0]
    from argiloteca.openalex.service import tokens
    index = {token:{('one','draft'):{'id':'one','kind':'draft'}, ('two','published'):{'id':'two','kind':'published'}}
             for token in tokens(source['records'][0]['payload'],metadata)}
    with patch('argiloteca.openalex.service.inventory',return_value=index):
        run(collision_id)
    assert db.session.get(OpenAlexJob,collision_id).state == 'failed'
    assert (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count()) == before_counts
    results['ambiguous_identity_never_creates'] = True

    if args.published_test_id:
        pid = args.published_test_id
        published = service.read(identity, pid).to_dict()
        assert published['is_published']
        row = deepcopy(prepare(root,'v59_20261017_125312_yn31iu5f')['records'][0])
        row['payload']['metadata']['title'] = 'TESTE TRANSACIONAL — não persistir'
        class RollbackTest(Exception): pass
        published_counts = (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count())
        try:
            with UnitOfWork() as uow:
                data,outcome = update_existing(service,identity,{'id':pid,'kind':'published'},row,metadata,uow)
                assert data['id'] == pid and outcome['draft_id'] == pid
                assert data['metadata']['title'] == row['payload']['metadata']['title']
                raise RollbackTest()
        except RollbackTest:
            pass
        assert (RDMDraftMetadata.query.count(), RDMRecordMetadata.query.count()) == published_counts
        assert service.read(identity,pid).to_dict()['metadata'] == published['metadata']
        results['published_edit_uses_same_pid_rolled_back'] = True

    Path('/tmp/openalex-upsert-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False))
