"""Verify native import+collection links on a restricted synthetic record only."""
from copy import deepcopy
import json
from pathlib import Path
import uuid
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from argiloteca.openalex.adapters import prepare,digest
from argiloteca.openalex.classification import classify_snapshot
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.tasks import run

app=create_ui()
with app.app_context():
    identity=actor_identity(4);root=app.config['ARGILOTECA_OPENALEX_ROOT']
    snapshot=prepare(root,'v59_20261017_125312_yn31iu5f')
    row=snapshot['records'][0];work='W'+str(int(uuid.uuid4().hex[:12],16))
    row['payload']['metadata']['title']='TESTE SINTÉTICO — kaolinite community routing'
    row['payload']['metadata']['identifiers']=[{'scheme':'url','identifier':'https://openalex.org/'+work}]
    row['payload']['metadata']['description']='TESTE SINTÉTICO de classificação temática de kaolinite.'
    row['payload'].pop('pids',None)
    row['payload']['access']={'record':'restricted','files':'restricted'}
    row['identity']={'doi':'','openalex_id':work};row['payload_sha256']=digest(row['payload'])
    classify_snapshot(root,snapshot,identity)
    targets=[c['id'] for c in row['classification']['communities']]
    assert targets==['071f0ad9-c1c0-4670-981c-5965021ce59b']
    def job_for(snapshot):
        job=OpenAlexJob(kind='import',actor=4,snapshot=deepcopy(snapshot),params={
            'selected':[row['key']],'communities':{row['key']:targets},'existing_policy':'overwrite','test_only':True})
        db.session.add(job);db.session.commit();return job.id
    first=job_for(snapshot);run(first);job=db.session.get(OpenAlexJob,first)
    assert job.state=='completed',job.result
    result=job.result['items'][row['key']];rid=result['draft_id']
    Path('/tmp/openalex-classification-fixture.json').write_text(json.dumps({'id':rid,'job':first}))
    data=service.read_draft(identity,rid).to_dict()
    assert data['is_draft'] and not data['is_published']
    assert data['parent']['communities']['ids']==targets,data['parent']
    assert data['access']['record']=='restricted'
    before_access=deepcopy(data['parent']['access'])
    assert result['communities'][0]['slug']=='caulim-serpentina'
    snapshot['records'][0]['payload']['metadata']['title']='TESTE SINTÉTICO — kaolinite community routing updated'
    snapshot['records'][0]['payload_sha256']=digest(snapshot['records'][0]['payload'])
    classify_snapshot(root,snapshot,identity)
    second=job_for(snapshot);run(second);updated=db.session.get(OpenAlexJob,second)
    assert updated.state=='completed',updated.result
    assert updated.result['summary']['created']==0 and updated.result['summary']['updated']==1
    after=service.read_draft(identity,rid).to_dict()
    assert after['parent']['communities']['ids']==targets
    assert after['parent']['access']==before_access
    assert updated.result['items'][row['key']]['draft_id']==rid
    # The native publisher must keep the collection link without auto-publishing
    # any imported record during the import operation itself.
    published=service.publish(identity,rid).to_dict()
    assert published['parent']['communities']['ids']==targets
    assert published['access']['record']=='restricted'
    service.delete_record(identity,rid,{'removal_reason':{'id':'duplicate'},'is_visible':False,
        'note':'TESTE SINTÉTICO de classificação encerrado.','citation_text':'TESTE SINTÉTICO.'})
    result={'import_job':first,'overwrite_job':second,'id':rid,
        'draft_linked_to_expected_community':True,'remained_unpublished_on_import':True,
        'overwrite_same_pid_membership_idempotent':True,'owner_and_access_preserved':True,
        'native_publication_preserves_membership':True,'synthetic_record_retired':True}
    Path('/tmp/openalex-classification-native-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
