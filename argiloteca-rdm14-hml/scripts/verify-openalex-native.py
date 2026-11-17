"""Native integration checks. Only synthetic restricted drafts may be created."""
from copy import deepcopy
import json
import uuid
from pathlib import Path
from unittest.mock import patch
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.records.models import RDMDraftMetadata
from invenio_rdm_records.proxies import current_rdm_records_service as service
from argiloteca.openalex.adapters import digest, prepare
from argiloteca.openalex.models import OpenAlexJob, OpenAlexClaim
from argiloteca.openalex.service import actor_identity, review_snapshot, job_lock
from argiloteca.openalex.tasks import run

import argparse
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--import-job', required=True, help='Completed import of the restricted synthetic fixture')
args=parser.parse_args()
app=create_ui();results={}
with app.app_context():
 root=app.config['ARGILOTECA_OPENALEX_ROOT']
 original=OpenAlexJob.query.filter_by(kind='import', state='completed').filter(OpenAlexJob.id==args.import_job).one()
 draft_id=next(iter(original.result['items'].values()))['draft_id']
 data=service.read_draft(actor_identity(4),draft_id).to_dict()
 assert not data.get('errors'),data.get('errors')
 assert data['metadata']['title'].startswith('TESTE SINTÉTICO')
 assert data['access']['record']=='restricted' and data['files']['enabled'] is False
 assert int(data['parent']['access']['owned_by']['user'])==4
 results['restricted_draft']={'id':draft_id,'native_validation_errors':0,'owner':4,'published':False}
 assert data.get('is_published') is False
 # Same source in a new job must use the existing draft.
 job=OpenAlexJob(kind='import',actor=4,snapshot=deepcopy(original.snapshot),params={**deepcopy(original.params), 'signature': 'test-'+uuid.uuid4().hex, 'test_only': True})
 db.session.add(job);db.session.commit();jid=job.id
 before=RDMDraftMetadata.query.count();claims=OpenAlexClaim.query.count()
 run(jid)
 job=db.session.get(OpenAlexJob,jid)
 assert job.state=='completed',job.result
 assert job.result['summary']=={'created':0,'updated':1,'duplicate':0},job.result
 assert next(iter(job.result['items'].values()))['draft_id']==draft_id
 assert RDMDraftMetadata.query.count()==before and OpenAlexClaim.query.count()==claims
 results['cross_job_deduplication']={'job':jid,'created':0,'updated':1}
 # Re-delivery of a completed job must be a no-op.
 run(jid)
 assert RDMDraftMetadata.query.count()==before
 results['redelivery_no_duplicate']=True
 # Database session lock prevents a second worker from entering the same job.
 with job_lock(jid) as first:
  with job_lock(jid) as second:
   assert first and not second
 results['concurrent_job_lock']=True
 # Crash after native flush but before commit must roll back draft and claims.
 snapshot=deepcopy(original.snapshot);row=snapshot['records'][0]
 row['payload']['metadata']['identifiers']=[{'scheme':'url','identifier':'https://openalex.org/W999999999999999998'}]
 row['payload']['metadata']['title']='TESTE SINTÉTICO — rollback antes de commit'
 row['payload_sha256']=digest(row['payload'])
 crash=OpenAlexJob(kind='import',actor=4,snapshot=snapshot,params={**deepcopy(original.params), 'signature': 'test-'+uuid.uuid4().hex, 'test_only': True})
 db.session.add(crash);db.session.commit();crash_id=crash.id
 with patch('invenio_records_resources.services.uow.UnitOfWork.commit',side_effect=RuntimeError('synthetic precommit crash')):
  run(crash_id)
 assert db.session.get(OpenAlexJob,crash_id).state=='failed'
 assert RDMDraftMetadata.query.count()==before
 assert OpenAlexClaim.query.count()==claims
 assert not OpenAlexClaim.query.filter_by(token='openalex:W999999999999999998').first()
 crash=db.session.get(OpenAlexJob,crash_id)
 crash.result={**crash.result,'error':'TESTE SINTÉTICO: falha antes do commit provocada para validar rollback. Nenhum rascunho criado.'}
 db.session.commit()
 results['rollback_native_draft_and_claims']={'job':crash_id,'draft_count_unchanged':True}
 # Simulate loss after DB commit but before delivery acknowledgement. Durable checkpoint survives.
 completed=db.session.get(OpenAlexJob,original.id)
 completed.state='failed';completed.result={**completed.result,'error':'TESTE: interrupção após commit, antes do reconhecimento.'}
 db.session.commit();completed.state='queued';db.session.commit()
 run(completed.id)
 assert db.session.get(OpenAlexJob,completed.id).state=='completed'
 assert RDMDraftMetadata.query.count()==before and OpenAlexClaim.query.count()==claims
 results['resume_after_committed_checkpoint']=True
 # Real source already exists, so preparation must identify it.
 actual=review_snapshot(root,prepare(root,'v59_20261017_125312_yn31iu5f'),4)
 assert actual['records'][0]['duplicates']
 results['real_source_duplicate']=actual['records'][0]['duplicates']
 Path('/tmp/openalex-integration-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(json.dumps(results,ensure_ascii=False))
