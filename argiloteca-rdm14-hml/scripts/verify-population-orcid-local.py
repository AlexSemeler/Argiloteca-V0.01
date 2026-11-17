#!/usr/bin/env python3
"""Verify source ORCID review locally using a real source-declared ID; no native record writes."""
import json,os,re
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.analytics import connect
from argiloteca.openalex.preview import iter_records,file_hash
from argiloteca.openalex.analytics import path_for
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.tasks import run
app=create_ui();client=app.test_client()
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101'
 a=db.session.get(OpenAlexJob,os.environ['POPULATION_VERIFY_ANALYSIS']);uid=db.session.get(User,4).get_id()
 with connect(a) as c:
  row=dict(c.execute("SELECT a.key,a.orcid FROM p_authors a JOIN p_records r ON r.id=a.record WHERE r.kind='recovered' AND a.status='linked' AND r.review!='' AND r.conflict=0 LIMIT 1").fetchone())
 aid=a.id
with client.session_transaction() as session:
 session['_user_id']=uid;session['_fresh']=True;session['identity.id']=int(uid);session['identity.auth_type']='session'
page=client.get('/administration/povoamento/authors/'+row['key']+'?analysis='+aid+'&ln=pt')
assert page.status_code==200
csrf=re.search(r'name="csrf_token" value="([^"]+)"',page.text).group(1)
def post(path,data):
 with patch('argiloteca.openalex.tasks.run.delay'):
  return client.post(path,data={'csrf_token':csrf,**data})
r=post('/administration/povoamento/authors/'+row['key']+'/preview',{'analysis':aid,'orcid':row['orcid']});assert r.status_code==303
preview_id=urlsplit(r.location).path.rsplit('/',1)[1]
with app.app_context():
 run(preview_id);db.session.expire_all();preview=db.session.get(OpenAlexJob,preview_id);assert preview.state=='review',(preview.state,preview.result)
 plan=preview.snapshot;source=db.session.get(OpenAlexJob,plan['source_job']);original=digest(source.snapshot);params=digest(source.params);analysis_sha=file_hash(path_for(aid))
assert client.get('/administration/povoamento/jobs/'+preview_id+'?ln=pt').status_code==200
assert client.get('/administration/povoamento/jobs/'+preview_id+'?ln=en').status_code==200
assert client.post('/administration/povoamento/jobs/'+preview_id+'/apply').status_code==400
assert post('/administration/povoamento/jobs/'+preview_id+'/apply',{'confirm':'yes','plan_sha256':'wrong'}).status_code==409
r=post('/administration/povoamento/jobs/'+preview_id+'/apply',{'confirm':'yes','plan_sha256':digest(plan),'note':'Validação local: preservar o identificador já declarado na fonte, sem modificar registros nativos.'})
assert r.status_code==303,r.text[:300];revised_id=urlsplit(r.location).path.rsplit('/',1)[1]
assert post('/administration/povoamento/jobs/'+preview_id+'/apply',{'confirm':'yes','plan_sha256':digest(plan)}).location==r.location
with app.app_context():
 run(revised_id);db.session.expire_all();revised=db.session.get(OpenAlexJob,revised_id);assert revised.state=='review',(revised.state,revised.result)
 source=db.session.get(OpenAlexJob,plan['source_job']);assert digest(source.snapshot)==original and digest(source.params)==params
 selected=list(iter_records(revised.snapshot,{plan['row_key']}));assert len(selected)==1
 assert selected[0]['payload']['metadata']['creators']==plan['after_creators'];assert plan['before_creators']==plan['after_creators'],'This verifier only confirms a real source-declared ID, never invents a link'
 assert analysis_sha==file_hash(path_for(aid))
 evidence={'analysis':aid,'key':row['key'],'preview':preview_id,'revised_review':revised_id,'source_review':source.id,'orcid':row['orcid'],'source_unchanged':True,'no_native_writes':True,'idempotent':True,'plan_sha256':digest(plan)}
Path('/tmp/population-orcid-verification.json').write_text(json.dumps(evidence,indent=2))
print(json.dumps(evidence),flush=True)
