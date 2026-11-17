#!/usr/bin/env python3
"""Read-only local verification of ontology navigation, source brands and entity views."""
import json,re
from pathlib import Path
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from argiloteca.admin_ui.views import counts
app=create_ui();client=app.test_client();results=[]
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101','Local instance only'
 assert app.config['ARGILOTECA_ADMIN_ONTOLOGY_ENABLED']
 uid=db.session.get(User,4).get_id();census=counts()
for route in ['/administration/argiloteca/fontes/','/administration/argiloteca/entidades/campo/']:
 assert client.get(route).status_code==403
with client.session_transaction() as session:
 session['_user_id']=uid;session['_fresh']=True;session['identity.id']=int(uid);session['identity.auth_type']='session'
paths=['/administration/','/administration/argiloteca/fontes/']+['/administration/argiloteca/entidades/'+key+'/' for key in ['campo','amostra','analise','argilomineral','publicacoes']]+['/administration/openalex/','/administration/pangaea/','/administration/mendeley/','/administration/repositories/','/administration/povoamento/','/administration/povoamento/authors/','/administration/records','/administration/drafts']
for language in ('pt','en'):
 for path in paths:
  r=client.get(path+'?ln='+language);results.append({'path':path,'language':language,'status':r.status_code})
  assert r.status_code==200,(path,language,r.status_code,r.text[:1000])
  assert 'admin-ontology.css' in r.text,(path,'missing shared shell stylesheet')
  if path=='/administration/':assert 'au-chain' in r.text and 'au-source-list' in r.text
  if path=='/administration/argiloteca/fontes/':
   for name in ('openalex.png','pangaea.png','mendeley.svg','lume.png','ufsc.svg'):assert 'images/sources/'+name in r.text
r=client.get('/administration/repositories/?repository=ufsc&ln=pt')
assert '<option value="ufsc" selected>' in r.text,'UFSC source link must select UFSC'
assert client.get('/administration/argiloteca/entidades/invalid/').status_code==404
assert client.get('/administration/argiloteca/entidades/campo/?page=wrong').status_code==400
assert client.get('/administration/argiloteca/entidades/campo/?stage=invalid').status_code==400
r=client.get('/administration/argiloteca/entidades/amostra/?q=unfindable-ontology-validation&ln=pt');assert r.status_code==200 and 'Nenhum registro neste recorte' in r.text
r=client.get('/administration/argiloteca/entidades/publicacoes/?stage=draft&ln=en');assert r.status_code==200
# Check the exact legacy fallback without changing the running service configuration.
with app.app_context():
 app.config['ARGILOTECA_ADMIN_ONTOLOGY_ENABLED']=False
 try:
  legacy=client.get('/administration/?ln=pt')
  assert legacy.status_code==200 and 'sc-admin-intro' in legacy.text and 'au-chain' not in legacy.text
 finally: app.config['ARGILOTECA_ADMIN_ONTOLOGY_ENABLED']=True
# A locale selected through the existing language picker must survive clean URLs.
locale_response=client.get('/lang/en?next=/administration/argiloteca/entidades/campo/',follow_redirects=True)
assert locale_response.status_code==200 and 'Fieldwork' in locale_response.text
assert 'name="ln" value="en"' in locale_response.text
locale_cookie_preserved=True
# A test-only session to inspect the actual UI, without printing the cookie.
with app.app_context():
 cookie_name=app.config.get('SESSION_COOKIE_NAME','session');signed=next(c.value for c in client._cookies.values() if c.key==cookie_name)
p=Path('/tmp/admin-ontology-browser-state.json');p.write_text(json.dumps({'cookies':[{'name':cookie_name,'value':signed,'domain':'127.0.0.1','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],'origins':[]}));p.chmod(0o600)
evidence={'scope':'local only; native metadata unchanged','counts':census,'responses':results,'anonymous_denied':True,'ufsc_source_selected':True,'filters_and_empty_state':True,'legacy_fallback_verified':True,'english_cookie_preserved_in_filters':locale_cookie_preserved,'orcid_token_configured':bool(app.config.get('ARGILOTECA_ORCID_READ_PUBLIC_TOKEN'))}
Path('/tmp/admin-ontology-verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
print(json.dumps(evidence,ensure_ascii=False),flush=True)
