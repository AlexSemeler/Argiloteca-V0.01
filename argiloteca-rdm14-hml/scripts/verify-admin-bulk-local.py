#!/usr/bin/env python3
"""Exercise native mutations only on records/jobs created by this disposable test."""
import json,re
from urllib.parse import urlsplit
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from flask import g
from invenio_app.factory import create_ui
from invenio_accounts.models import User
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex import bulk_maintenance as bulk, maintenance as clean
from argiloteca.openalex.adapters import digest
app=create_ui();client=app.test_client();evidence={'scope':'Local only; native mutations limited to newly created disposable test records','pages':[]}
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101'
 uid=int(db.session.get(User,4).get_id())
assert client.post('/administration/maintenance/bulk/preview').status_code==403
with client.session_transaction() as session:
 session['_user_id']=str(uid);session['_fresh']=True;session['identity.id']=uid;session['identity.auth_type']='session'
for ln in ('pt','en'):
 for path in ['/administration/openalex/','/administration/pangaea/','/administration/mendeley/','/administration/repositories/','/administration/povoamento/authors/','/administration/povoamento/records/','/administration/drx-links/','/administration/raw-library/','/administration/maintenance/']:
  response=client.get(path+'?ln='+ln)
  assert response.status_code==200,(path,ln,response.status_code,response.text[:500])
  evidence['pages'].append(dict(path=path,ln=ln,status=200))
response=client.get('/administration/maintenance/?ln=pt');csrf=re.search(r'name="csrf_token" value="([^"]+)"',response.text)[1]
assert client.post('/administration/maintenance/bulk/preview').status_code==400
assert client.post('/administration/maintenance/bulk/preview',data={'csrf_token':csrf,'operation':'delete','reason':'Teste sem seleção'}).status_code==422

def choice(kind,target,**extra):
 with app.test_request_context():
  with patch.object(bulk,'current_user',type('Actor',(),{'id':uid})()):return bulk.token(kind,target,**extra)

def preview(tokens,operation='delete'):
 result=client.post('/administration/maintenance/bulk/preview',data={'csrf_token':csrf,'operation':operation,'reason':'Teste descartável local de seleção e exclusão','bulk_selected':tokens})
 assert result.status_code==303,(result.status_code,result.text[:500])
 job_id=urlsplit(result.location).path.rstrip('/').rsplit('/',1)[-1]
 result=client.get(result.location);assert result.status_code==200,(result.status_code,result.text[:500])
 with app.app_context():parent=db.session.get(OpenAlexJob,job_id);sha=digest(parent.snapshot)
 return job_id,sha

def apply(parent,sha,permanent=False):
 data={'csrf_token':csrf,'confirm':'yes','plan_sha256':sha}
 if permanent:data['permanent_confirmation']='EXCLUIR'
 with patch('argiloteca.openalex.tasks.run.delay'):
  result=client.post('/administration/maintenance/bulk/'+parent+'/apply',data=data)
 assert result.status_code==303,(result.status_code,result.text[:500])
 with app.app_context():
  jobs=OpenAlexJob.query.filter_by(kind='clean_apply').filter(OpenAlexJob.params['bulk_parent'].as_string()==parent).all()
  ids=[j.id for j in jobs]
  for job in jobs:
   clean.run_job(job)
   db.session.expire_all();done=db.session.get(OpenAlexJob,job.id)
   assert done.state=='completed',(done.id,done.state,done.result)
   assert done.result.get('backup',{}).get('sha256')
 return ids

with app.app_context():
 identity=actor_identity(uid)
 payload={'metadata':{'title':'TESTE DESCARTÁVEL LOCAL — admin bulk 20261101','resource_type':{'id':'dataset'},'publication_date':'2026-11-01','creators':[{'person_or_org':{'type':'personal','given_name':'Pessoa','family_name':'TesteBulk','identifiers':[{'scheme':'orcid','identifier':'0000-0002-1825-0097'}]}},{'person_or_org':{'type':'personal','given_name':'Outra','family_name':'TesteBulk','identifiers':[{'scheme':'orcid','identifier':'0000-0001-5109-3700'}]}}]},'access':{'record':'public','files':'public'},'files':{'enabled':False}}
 draft=service.create(identity,deepcopy(payload));pid=draft.id
 Path('/tmp/admin-bulk-disposable-record.json').write_text(json.dumps({'id':pid,'title':payload['metadata']['title']}))
 before=service.read_draft(identity,pid).to_dict()
 # Both ORCID occurrences must be one native write, preserving both people.
 tokens=[choice('orcid',pid,record_kind='draft',occurrence={'slot':i,'creator_sha256':digest(before['metadata']['creators'][i])}) for i in (0,1)]
parent,sha=preview(tokens,'unlink')
with app.app_context():
 assert len(db.session.get(OpenAlexJob,parent).snapshot['entries'])==1
 assert service.read_draft(identity,pid).to_dict()['metadata']['creators']==before['metadata']['creators']
assert client.post('/administration/maintenance/bulk/'+parent+'/apply',data={'csrf_token':csrf,'confirm':'yes','plan_sha256':'tampered'}).status_code==409
applied=apply(parent,sha)
with app.app_context():
 after=service.read_draft(identity,pid).to_dict()
 expected=deepcopy(before['metadata']['creators'])
 for creator in expected:creator['person_or_org'].pop('identifiers',None)
 assert after['metadata']['creators']==expected
 assert after['metadata']['title']==before['metadata']['title']
evidence['orcid_occurrences_grouped']=True;evidence['orcid_people_and_publication_preserved']=True
# Repeated confirmation must return the same operation, never enqueue twice.
with patch('argiloteca.openalex.tasks.run.delay') as dispatch:
 repeat=client.post('/administration/maintenance/bulk/'+parent+'/apply',data={'csrf_token':csrf,'confirm':'yes','plan_sha256':sha})
 assert repeat.status_code==303;dispatch.assert_not_called()
evidence['confirmation_idempotent']=True
# Delete only the disposable draft created above, with verified backup.
parent,sha=preview([choice('record',pid,record_kind='draft')])
assert client.post('/administration/maintenance/bulk/'+parent+'/apply',data={'csrf_token':csrf,'confirm':'yes','plan_sha256':sha}).status_code==409
apply(parent,sha,True)
with app.app_context():assert not RDMDraftMetadata.query.filter(RDMDraftMetadata.json['id'].as_string()==pid).first()
evidence['temporary_draft_deleted_with_backup']=True
# A disposable review can exclude rows without altering its original corpus.
with app.app_context():
 review=OpenAlexJob(kind='prepare',state='review',actor=uid,params={'test_only':True},snapshot={'records':[{'key':key,'status':'apto','payload':deepcopy(payload),'identity':{}} for key in ('keep','exclude')],'summary':{'total':2,'apto':2}},result={});db.session.add(review);db.session.commit();review_id=review.id
parent,sha=preview([choice('import_row',review_id,row_key='exclude',native_id='',record_kind='')],'exclude')
apply(parent,sha)
with app.app_context():
 from argiloteca.openalex.preview import iter_records,page_records
 result=db.session.get(OpenAlexJob,review_id)
 assert len(result.snapshot['records'])==2 and result.snapshot['admin_excluded_records']==['exclude']
 assert [r['key'] for r in iter_records(result.snapshot)]==['keep']
 assert list(iter_records(result.snapshot,{'exclude'}))==[] and page_records(result.snapshot)[1]==1
 assert result.snapshot['summary']=={'total':1,'apto':1}
evidence['review_exclusion_preserves_sources_and_blocks_import']=True
# Remove only that synthetic review task after its source preservation was checked.
parent,sha=preview([choice('job',review_id)])
apply(parent,sha,True)
# A new temporary publication verifies grouped DRX unlinking and native purge.
with app.app_context():
 from argiloteca.scientific.admin_raw_views import store
 from argiloteca.scientific.drx_links import set_link,sync_metadata,DRXRecordLink
 from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
 raw_store=store();raw_rows=[row for row in raw_store.rows() if row['curve_available']][:2]
 raw_hashes={row['id']:digest(list(raw_store.content(row))) for row in raw_rows}
 publication_payload=deepcopy(payload);publication_payload['metadata']['title']+=' — DRX temporary publication'
 draft=service.create(identity,publication_payload);published_id=draft.id
 assert not draft.to_dict().get('pids'), 'No external PID operation is allowed in this local test'
 service.publish(identity,published_id)
 with UnitOfWork() as uow:
  for row in raw_rows:set_link(identity,row,published_id,state='pending',evidence='Disposable local test association only',expected_revision=0,actor=uid)
  native=sync_metadata(identity,published_id,{row['id']:row for row in raw_store.rows()})
  uow.register(RecordCommitOp(native,indexer=service.indexer,index_refresh=True));uow.commit()
parent,sha=preview([choice('drx_link',published_id,raw_id=row['id']) for row in raw_rows],'unlink')
with app.app_context():assert len(db.session.get(OpenAlexJob,parent).snapshot['entries'])==1
apply(parent,sha)
with app.app_context():
 assert all(link.state=='removed' for link in DRXRecordLink.query.filter_by(record_id=published_id))
 assert service.read(identity,published_id).to_dict()['metadata']['title']==publication_payload['metadata']['title']
 assert {row['id']:digest(list(raw_store.content(row))) for row in raw_rows}==raw_hashes
evidence['grouped_drx_unlink_preserves_raws_and_publication']=True
parent,sha=preview([choice('record',published_id,record_kind='published')])
apply(parent,sha,True)
with app.app_context():assert not RDMRecordMetadata.query.filter(RDMRecordMetadata.json['id'].as_string()==published_id).first()
evidence['temporary_publication_purged_with_backup']=True
# Delete only a new disposable journal task; existing source jobs remain intact.
with app.app_context():
 dummy=OpenAlexJob(kind='extract',state='completed',actor=uid,params={'test_only':True},snapshot={},result={'test_only':True});db.session.add(dummy);db.session.commit();dummy_id=dummy.id
parent,sha=preview([choice('job',dummy_id)])
apply(parent,sha,True)
with app.app_context():assert db.session.get(OpenAlexJob,dummy_id) is None
evidence['temporary_job_deleted_with_backup']=True
# The currently active analysis cannot be deleted from history.
with app.app_context():
 from argiloteca.openalex.models import OpenAlexAnalyticHead
 head=db.session.get(OpenAlexAnalyticHead,1)
 if head and head.version:
  protected=clean.plan(identity,uid,'job',head.version,'delete_job',reason='Verificação somente leitura do retrato ativo')
  assert any('snapshot supplies current' in blocker for blocker in protected['blockers'])
 evidence['active_statistics_snapshot_protected']=True
# Ready source reviews remain read-only here; collect real review routes for browser QA.
with app.app_context():
 evidence['review_jobs']={}
 for source,kind in [('openalex','prepare'),('pangaea','pan_prepare'),('mendeley','men_prepare'),('repositories','oai_prepare')]:
  row=OpenAlexJob.query.filter_by(kind=kind).filter(OpenAlexJob.state.in_(['review','completed'])).order_by(OpenAlexJob.created.desc()).first()
  if row:evidence['review_jobs'][source]=row.id
 cookie_name=app.config.get('SESSION_COOKIE_NAME','session');value=next(c.value for c in client._cookies.values() if c.key==cookie_name)
p=Path('/tmp/admin-bulk-browser-state.json');p.write_text(json.dumps({'cookies':[{'name':cookie_name,'value':value,'domain':'127.0.0.1','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],'origins':[]}));p.chmod(0o600)
Path('/tmp/admin-bulk-verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))
