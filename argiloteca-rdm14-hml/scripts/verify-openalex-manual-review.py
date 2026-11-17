"""Native/manual HTTP checks on two restricted synthetic records only."""
from copy import deepcopy
import json
from pathlib import Path
import re
from unittest.mock import patch
import uuid

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_records_resources.services.uow import UnitOfWork
from invenio_rdm_records.services.communities.service import ParentRecordCommitOp
from argiloteca.openalex.manual_review import active_items,snapshot_record,build_plan,scan_job
from argiloteca.openalex.classification import load_vocabulary,community_catalog,classify
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.tasks import run
from argiloteca.openalex.adapters import digest

app=create_ui();fixtures=[];evidence={}
with app.app_context():
 identity=actor_identity(4);baseline=len(active_items())
 vocab,version=load_vocabulary(app.config['ARGILOTECA_OPENALEX_ROOT']);catalog=community_catalog(identity)
 first=catalog['caulim-serpentina']['id'];second=catalog['esmectitas']['id']
 def row_for(rid,kind):
  item=next((m,k) for m,k in active_items() if m.json['id']==rid)
  row=snapshot_record(identity,item)
  row['classification']=classify({'payload':{'metadata':row['metadata']},'provenance':[]},vocab,catalog,version)
  assert not row['classification']['communities']
  return row
 def review_job(row):
  job=OpenAlexJob(kind='manual_scan',state='review',actor=4,params={'test_only':True},snapshot={'rows':[row],'catalog':catalog,'rule':version},result={'total':1,'pending':1,'manually_reviewed':0})
  db.session.add(job);db.session.commit();return job
 def application(scan,plan):
  preview=OpenAlexJob(kind='manual_preview',state='review',actor=4,params={'scan_job':scan.id,'test_only':True},snapshot={'plan':plan})
  db.session.add(preview);db.session.commit()
  job=OpenAlexJob(kind='manual_apply',actor=4,params={'source_job':preview.id,'scan_job':scan.id,'plan_sha256':digest(plan),'test_only':True},snapshot={'plan':deepcopy(plan)})
  db.session.add(job);db.session.commit();return preview.id,job.id
 try:
  for kind in ('published','draft'):
   data={'metadata':{'title':'TESTE SINTÉTICO — Curadoria manual '+uuid.uuid4().hex[:8],
       'resource_type':{'id':'publication-article'},'publication_date':'2026-10-23',
       'creators':[{'person_or_org':{'type':'personal','name':'Curador, Teste','given_name':'Teste','family_name':'Curador'}}]},
       'access':{'record':'restricted','files':'restricted'},'files':{'enabled':False}}
   created=service.create(identity,data);record=created._record;rid=created.id
   fixtures.append({'id':rid,'kind':'draft'})
   with UnitOfWork(db.session) as uow:
    record.parent.communities.add(__import__('invenio_communities.proxies',fromlist=['current_communities']).current_communities.service.record_cls.pid.resolve(first),default=True)
    uow.register(ParentRecordCommitOp(record.parent,indexer_context={'service':service},bulk_index=False));uow.commit()
   if kind=='published':service.publish(identity,rid);fixtures[-1]['kind']='published'
   row=row_for(rid,kind);scan=review_job(row);plan=build_plan(identity,row,[second],'Validação sintética de vínculo adicional.')
   preview_id,job_id=application(scan,plan)
   if kind=='draft':
    native=service.read_draft(identity,rid).to_dict()
    service.update_draft(identity,rid,{'metadata':{**native['metadata'],'title':native['metadata']['title']+' atualizado'},'files':{'enabled':False}})
    run(job_id);stale=db.session.get(OpenAlexJob,job_id)
    assert stale.state=='failed' and 'mudaram' in stale.result['error'],stale.result
    assert service.read_draft(identity,rid).to_dict()['parent']['communities']['ids']==[first]
    evidence['stale_preview_refused']=True
    row=row_for(rid,kind);scan=review_job(row);plan=build_plan(identity,row,[second])
    preview_id,job_id=application(scan,plan)
   else:
    with patch('argiloteca.openalex.manual_review.verify_parent',side_effect=ValueError('Teste de rollback antes do commit')):run(job_id)
    assert db.session.get(OpenAlexJob,job_id).state=='failed'
    assert service.read(identity,rid).to_dict()['parent']['communities']['ids']==[first]
    evidence['native_rollback_preserves_existing_links']=True
    preview_id,job_id=application(scan,plan)
   run(job_id);job=db.session.get(OpenAlexJob,job_id)
   assert job.state=='completed',job.result
   assert job.result['search_refreshed'] and [c['id'] for c in job.result['added']]==[second]
   native=(service.read if kind=='published' else service.read_draft)(identity,rid).to_dict()
   assert set(native['parent']['communities']['ids'])=={first,second}
   assert native['parent']['communities']['default']==first
   assert native['access']['record']=='restricted' and native['id']==rid
   result=deepcopy(job.result);run(job_id);assert db.session.get(OpenAlexJob,job_id).result==result
   evidence[kind]={'id':rid,'job':job_id,'preview':preview_id,'scan':scan.id,'same_pid':True,'existing_links_and_default_preserved':True,'redelivery_idempotent':True}
  row=row_for(fixtures[0]['id'],'published');scan=review_job(row)
  preview_id,job_id=application(scan,build_plan(identity,row,[],'Vínculos atuais conferidos.',keep=True))
  run(job_id);assert db.session.get(OpenAlexJob,job_id).state=='completed'
  assert not db.session.get(OpenAlexJob,job_id).result['added']
  evidence['confirm_current_without_new_links']=True
  # Decisions leave future scans, while metadata and link changes reopen them.
  only=[item for item in active_items() if item[0].json['id'] in {f['id'] for f in fixtures}]
  verification=OpenAlexJob(kind='manual_scan',actor=4,params={'test_only':True})
  with patch('argiloteca.openalex.manual_review.active_items',return_value=only):scan_job(verification)
  assert verification.result['pending']==0 and verification.result['manually_reviewed']==2,verification.result
  evidence['reviewed_decisions_leave_queue']=True
  # Every request gets a fresh app context; no authenticated Flask g leaks into anonymous checks.
  client=app.test_client()
  def call(method,path,**kwargs):
   with app.app_context():return getattr(client,method)(path,**kwargs)
  assert call('get','/administration/openalex/classification/').status_code==403
  with client.session_transaction() as session:
   session['_user_id']=db.session.get(User,4).get_id();session['_fresh']=True
   session['identity.id']=4;session['identity.auth_type']='session'
  path='/administration/openalex/classification/jobs/'+evidence['draft']['scan']
  response=call('get',path+'?record='+fixtures[1]['id']+'&ln=pt')
  assert response.status_code==200,response.status_code
  assert 'private, no-store' in response.headers['Cache-Control']
  assert 'Vínculos atuais' in response.text
  csrf=re.search(r'name="csrf_token" value="([^"]+)"',response.text).group(1)
  assert call('post',path+'/preview',data={'record':fixtures[1]['id']}).status_code==400
  # Current snapshot for a valid, incomplete preview generated by the actual form route.
  current=review_job(row_for(fixtures[1]['id'],'draft'));path='/administration/openalex/classification/jobs/'+current.id
  response=call('post',path+'/preview',data={'csrf_token':csrf,'record':fixtures[1]['id'],'intent':'keep'})
  assert response.status_code==303,response.status_code
  preview_path=response.location
  page=call('get',preview_path);assert page.status_code==200
  generated=db.session.get(OpenAlexJob,preview_path.split('/jobs/')[1].split('?')[0])
  assert generated.snapshot['plan']['keep'] and not generated.snapshot['plan']['additions']
  apply_path='/administration/openalex/classification/jobs/'+generated.id+'/apply'
  assert call('post',apply_path,data={'csrf_token':csrf,'plan_sha256':digest(generated.snapshot['plan'])}).status_code==409
  response=call('post',apply_path,data={'csrf_token':csrf,'confirm':'yes','plan_sha256':'changed'})
  assert response.status_code==409
  # Reject out-of-catalog destination on a live snapshot, leaving native state untouched.
  response=call('post',path+'/preview',data={'csrf_token':csrf,'record':fixtures[1]['id'],'intent':'add','community':'not-a-community'})
  assert response.status_code==303
  assert call('get',path+'?ln=en').status_code==200
  evidence['http']={'anonymous_denied':True,'admin_page200':True,'csrf_missing400':True,'missing_confirmation409':True,'tampered_preview409':True,'private_no_store':True,'keep_form_generates_valid_preview':True,'unknown_destination_refused':True,'english_page200':True}
 finally:
  db.session.rollback()
  for fixture in fixtures:
   if fixture['kind']=='published':
    service.delete_record(identity,fixture['id'],{'removal_reason':{'id':'duplicate'},'is_visible':False,'note':'TESTE SINTÉTICO de revisão manual encerrado.','citation_text':'TESTE SINTÉTICO.'})
   else:service.delete_draft(identity,fixture['id'])
  assert len(active_items())==baseline
  evidence['synthetic_records_not_active']=True
  Path('/tmp/openalex-manual-native-results.json').write_text(json.dumps(evidence,indent=2))
 print(json.dumps(evidence))
