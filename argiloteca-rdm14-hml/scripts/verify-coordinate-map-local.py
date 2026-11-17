#!/usr/bin/env python3
"""Local, read-only coordinate UI integration check; never submits a record edit."""
import hashlib,json,re
from pathlib import Path
from unittest.mock import patch
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from argiloteca.scientific.catalog import public_map_records
from argiloteca.scientific.catalog_views import coordinate_targets
app=create_ui();client=app.test_client()
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101'
 uid=db.session.get(User,4).get_id()
 selected=next(row for row in public_map_records() if len(coordinate_targets(row.get('custom_fields') or {}))>1)
 pid=selected['id'];before=hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest()
assert client.get('/administration/mineral-map/').status_code==403
assert client.post('/administration/argiloteca/geocode',data={'place':'Porto Alegre'}).status_code==403
with client.session_transaction() as session:
 session['_user_id']=uid;session['_fresh']=True;session['identity.id']=int(uid);session['identity.auth_type']='session'
for language in ('pt','en'):
 response=client.get('/administration/mineral-map/?ln='+language)
 assert response.status_code==200,(response.status_code,response.text[:400])
 assert 'cm-config' in response.text and 'coordinate-map.js' in response.text
 response=client.get('/administration/mineral-map/?record_id='+pid+'&ln='+language)
 assert response.status_code==200,(response.status_code,response.text[:400])
 assert 'cm-target' in response.text
 token=re.search(r'name="csrf_token" value="([^"]+)"',response.text)[1]
assert client.post('/administration/argiloteca/geocode',data={'place':'Porto Alegre'}).status_code==400
assert client.post('/administration/argiloteca/geocode',data={'place':'x','csrf_token':token}).status_code==422
# Only this explicitly supplied, public place name is sent to the real provider.
response=client.post('/administration/argiloteca/geocode',data={'place':'Porto Alegre, Rio Grande do Sul, Brasil','csrf_token':token})
assert response.status_code==200,(response.status_code,response.text)
real=response.json;assert real['results'] and -31<real['results'][0]['latitude']<-29
cached=client.post('/administration/argiloteca/geocode',data={'place':'Porto Alegre, Rio Grande do Sul, Brasil','csrf_token':token})
assert cached.status_code==200 and cached.json['cached']
# Errors exercise the actual authenticated HTTP endpoint, no remote retries.
from argiloteca.admin_ui.geocoding import LookupError
for code,status in [('unavailable',503),('rate_limit',429)]:
 with patch('argiloteca.admin_ui.geocoding.lookup',side_effect=LookupError(code,status)):
  r=client.post('/administration/argiloteca/geocode',data={'place':'Porto Alegre','csrf_token':token})
  assert r.status_code==status and r.json['error']==code
with app.app_context():
 after=next(row for row in public_map_records() if row['id']==pid)
 assert hashlib.sha256(json.dumps(after,sort_keys=True).encode()).hexdigest()==before
 cookie_name=app.config.get('SESSION_COOKIE_NAME','session');signed=next(c.value for c in client._cookies.values() if c.key==cookie_name)
p=Path('/tmp/admin-ontology-browser-state.json');p.write_text(json.dumps({'cookies':[{'name':cookie_name,'value':signed,'domain':'127.0.0.1','path':'/','expires':-1,'httpOnly':True,'secure':True,'sameSite':'Lax'}],'origins':[]}));p.chmod(0o600)
evidence={'scope':'local only, no record POST, selected record hash unchanged','record_id':pid,'targets':len(coordinate_targets(selected.get('custom_fields') or {})),'pt_en_pages':True,'anonymous_denied':True,'csrf_enforced':True,'real_lookup':real,'cached_repeat':True,'error_http_statuses':[422,429,503]}
Path('/tmp/coordinate-map-verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2));print(json.dumps(evidence,ensure_ascii=False))
