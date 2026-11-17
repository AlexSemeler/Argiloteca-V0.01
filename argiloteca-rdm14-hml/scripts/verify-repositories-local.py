#!/usr/bin/env python3
"""Run inside LOCAL Invenio. --exercise-import creates, updates and publishes one real record."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch
from urllib.parse import urlsplit
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.preview import iter_records
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.tasks import run
from argiloteca.repositories import workflow

p=argparse.ArgumentParser(description=__doc__);p.add_argument('--extraction',required=True);p.add_argument('--exercise-import',action='store_true');args=p.parse_args()
app=create_ui();client=app.test_client();evidence={}
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101','Local homologation only'
 user=db.session.get(User,4);uid=user.get_id();assert len(workflow.terms())==81
 source=db.session.get(OpenAlexJob,args.extraction);assert source.kind=='oai_extract'
# The already completed host result is consumed using the shared dispatcher.
with app.app_context():
 run(args.extraction);db.session.expire_all();source=db.session.get(OpenAlexJob,args.extraction)
 assert source.state=='completed',(source.state,source.result)
 evidence.update(extraction={'id':source.id,'params':source.params,'result':source.result})
assert client.get('/administration/repositories/').status_code==403
with client.session_transaction() as s:
 s['_user_id']=uid;s['_fresh']=True;s['identity.id']=int(uid);s['identity.auth_type']='session'
base='/administration/repositories'
for lang in ('pt','en'):
 for path in ('/','/publication/','/pdfs/'):
  r=client.get(base+path+'?ln='+lang);assert r.status_code==200,(path,r.text[:300])
r=client.get(base+'/?ln=pt');csrf=re.search(r'name="csrf_token" value="([^"]+)"',r.text).group(1)

def post(path,data=None):return client.post(base+path,data={'csrf_token':csrf,**(data or {})})
def new(path,data=None):
 with patch('argiloteca.openalex.tasks.run.delay'):
  r=post(path,data)
 assert r.status_code==303,(path,r.status_code,r.text[:400])
 return urlsplit(r.location).path.rsplit('/',1)[1]
def dispatch(jid):
 with app.app_context():
  run(jid);db.session.expire_all();job=db.session.get(OpenAlexJob,jid)
  assert job.state in {'completed','review'},(job.kind,job.state,job.result)
  return job
review=new('/prepare',{'lot':source.result['lot'],'limit':1});dispatch(review)
with app.app_context():
 job=db.session.get(OpenAlexJob,review);row=next(iter_records(job.snapshot))
 assert row['status']!='bloqueado',row['issues']
 assert row['identity']['handle'] and not row['identity']['doi'],row['identity']
 assert 'custom_fields' not in row['payload'] and not row['payload']['files']['enabled']
 altered={**job.snapshot,'records':[deepcopy(row)]};altered['records'][0]['payload']['metadata']['title']='tamper'
 try:workflow.verify_snapshot(workflow.root(),altered);raise AssertionError('tamper accepted')
 except ValueError:pass
 evidence.update(review=review,identity=row['identity'],communities=row['classification']['communities'],native_validation=row['instance_validation'])
for lang in ('pt','en'):assert client.get(base+'/jobs/'+review+'?ln='+lang).status_code==200
for fmt in ('json','csv'):assert client.get(base+'/jobs/'+review+'/report.'+fmt).status_code==200
for path in ('/extract','/prepare','/jobs/'+review+'/pdfs','/jobs/'+review+'/import','/jobs/'+args.extraction+'/continue'):
 assert client.post(base+path,data={}).status_code==400
assert post('/jobs/'+review+'/pdfs',{'pdf_selected':row['key']}).status_code==400
assert post('/jobs/'+review+'/import',{'selected':row['key']}).status_code==400
assert post('/jobs/'+review+'/import',{'selected':row['key'],'confirm':'yes','community:'+row['key']:'foreign'}).status_code==409
if args.exercise_import:
 assert not row['duplicates'],'Lifecycle validation only writes a record absent from the local collection.'
 data={'selected':row['key'],'confirm':'yes','community:'+row['key']:[c['id'] for c in row['classification']['communities']]}
 imported=new('/jobs/'+review+'/import',data);assert new('/jobs/'+review+'/import',data)==imported;dispatch(imported)
 with app.app_context():
  outcome=db.session.get(OpenAlexJob,imported).result['items'][row['key']];assert outcome['state']=='created',outcome;rid=outcome['draft_id']
 corrected=new('/jobs/'+review+'/correct',{'record':row['key'],'corrections':json.dumps({'title':row['payload']['metadata']['title']})});dispatch(corrected)
 updated=new('/jobs/'+corrected+'/import',data);dispatch(updated)
 with app.app_context():
  outcome=db.session.get(OpenAlexJob,updated).result['items'][row['key']];assert outcome['state']=='updated' and outcome['draft_id']==rid
 publishing=new('/jobs/'+imported+'/publication/preview',{'batch_size':100});dispatch(publishing)
 with app.app_context():
  plan=db.session.get(OpenAlexJob,publishing).snapshot;assert plan['summary']['ready']==1,plan;plan_hash=digest(plan)
 assert post('/publication/jobs/'+publishing+'/apply',{'confirm':'yes','plan_sha256':'tamper'}).status_code==409
 published=new('/publication/jobs/'+publishing+'/apply',{'confirm':'yes','plan_sha256':plan_hash});dispatch(published)
 with app.app_context():
  job=db.session.get(OpenAlexJob,published);assert job.result['items'][row['key']]['state']=='published',job.result
  from argiloteca.openalex.service import actor_identity
  from invenio_rdm_records.proxies import current_rdm_records_service as service
  record=service.read(actor_identity(4),rid).to_dict();assert not record['files']['enabled']
  assert {'scheme':'handle','identifier':row['identity']['handle']} in record['metadata']['identifiers']
  evidence.update(import_job=imported,update_job=updated,same_pid_upsert=True,record_id=rid,publication_preview=publishing,publication_job=published,backups=job.result['backups'])
 assert client.get(base+'/publication/jobs/'+published+'/backups/0').status_code==200
 assert client.get('/records/'+rid).status_code==200
# No download is started here: a browser test starts the PDF action separately.
evidence.update(terms=81,languages=['pt','en'],anonymous_denied=True,csrf=True,payload_tamper_denied=True)
Path('/tmp/verified-repositories.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str))
print(json.dumps(evidence,ensure_ascii=False,default=str))
