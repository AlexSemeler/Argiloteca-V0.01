#!/usr/bin/env python3
"""Local-only integrated census and access validation. Does not change native records."""
import json
import os
from pathlib import Path
import re
from unittest.mock import patch
from urllib.parse import urlsplit
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.analytics import connect
from argiloteca.openalex.tasks import run

app=create_ui();client=app.test_client();evidence={}
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101','Local instance only'
 user=db.session.get(User,4);uid=user.get_id()
for path in ('/','/authors/','/records/','/export.csv'):
 assert client.get('/administration/povoamento'+path).status_code==403
with client.session_transaction() as session:
 session['_user_id']=uid;session['_fresh']=True;session['identity.id']=int(uid);session['identity.auth_type']='session'
r=client.get('/administration/povoamento/?ln=pt');assert r.status_code==200,r.text[:300]
csrf=re.search(r'name="csrf_token" value="([^"]+)"',r.text).group(1)
assert client.post('/administration/povoamento/refresh').status_code==400
jid=os.environ.get('POPULATION_VERIFY_ANALYSIS')
if not jid:
 with patch('argiloteca.openalex.tasks.run.delay'):
  r=client.post('/administration/povoamento/refresh',data={'csrf_token':csrf})
 assert r.status_code==303,r.text[:300]
 jid=urlsplit(r.location).path.rsplit('/',1)[1]
print('SCAN',jid,flush=True)
with app.app_context():
 run(jid);db.session.expire_all();job=db.session.get(OpenAlexJob,jid)
 assert job.state=='completed',(job.state,job.result)
 assert job.snapshot.get('population'),job.snapshot
 evidence={'analysis':jid,'snapshot':job.snapshot,'result':job.result,'orcid_token_configured':bool(app.config.get('ARGILOTECA_ORCID_READ_PUBLIC_TOKEN'))}
 with connect(job) as c:
  from argiloteca.population.queries import summary,source_summary
  evidence['summary']=summary(c,{});evidence['sources']=source_summary(c)
  evidence['warnings']=[dict(r) for r in c.execute('SELECT * FROM p_warnings')]
  evidence['lots']=[dict(r) for r in c.execute('SELECT * FROM p_lots')]
  staged=c.execute("SELECT a.key FROM p_authors a JOIN p_records r ON r.id=a.record WHERE r.kind='recovered' ORDER BY (r.review!='') DESC LIMIT 1").fetchone()
  evidence['staged_author']=staged[0] if staged else None
  native=c.execute("SELECT key FROM p_authors WHERE native_key IS NOT NULL LIMIT 1").fetchone();evidence['native_author']=native[0] if native else None
  evidence['pdfs']=c.execute('SELECT count(*) FROM p_pdfs').fetchone()[0]
for lang in ('pt','en'):
 for path in ('/','/authors/','/records/','/export.csv?view=authors&','/export.csv?'):
  sep='?' if '?' not in path else ''
  r=client.get('/administration/povoamento'+path+sep+'ln='+lang+'&analysis='+jid)
  assert r.status_code==200,(path,r.status_code,r.text[:300])
 for source in (('lume','ufsc') if os.environ.get('POPULATION_VERIFY_FAST') else ('openalex','pangaea','mendeley','lume','ufsc','unknown')):
  assert client.get('/administration/povoamento/authors/?analysis='+jid+'&source='+source+'&ln='+lang).status_code==200
assert client.get('/administration/povoamento/records/?source=invalid').status_code==400
assert client.get('/administration/openalex/statistics/').status_code==303
assert client.get('/administration/openalex/statistics/?scope=openalex&analysis='+jid).status_code==200
assert client.get('/administration/openalex/authors/').status_code==303
if evidence['staged_author']:
 r=client.get('/administration/povoamento/authors/'+evidence['staged_author']+'?analysis='+jid+'&ln=pt');assert r.status_code==200,r.text[:300]
if evidence['native_author']:
 r=client.get('/administration/povoamento/authors/'+evidence['native_author']+'?analysis='+jid);assert r.status_code==303
 assert client.get(r.location).status_code==200
cookie=next(item.value for item in client._cookies.values() if item.key==app.config.get('SESSION_COOKIE_NAME','session'))
state={'cookies':[{'name':app.config.get('SESSION_COOKIE_NAME','session'),'value':cookie,'domain':'127.0.0.1','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],'origins':[]}
p=Path('/tmp/population-browser-state.json');p.write_text(json.dumps(state));p.chmod(0o600)
Path('/tmp/population-verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps({'analysis':jid,'summary':{k:v for k,v in evidence['summary'].items() if k not in ('years','types')},'sources':evidence['sources'],'warnings':len(evidence['warnings']),'staged_author':evidence['staged_author']},ensure_ascii=False),flush=True)
