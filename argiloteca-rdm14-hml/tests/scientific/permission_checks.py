"""An authenticated second user cannot read/edit another user's draft or restriction."""
import json,secrets
from pathlib import Path
from datetime import datetime,timezone
from lxml import etree
from invenio_app.factory import create_ui
from invenio_db import db
from flask_security.utils import hash_password
app=create_ui();base='https://127.0.0.1:5101';root=Path('/tmp/scientific-tests/evidence');r=json.loads((root/'integration.json').read_text());password=secrets.token_urlsafe(32)
with app.app_context():
 store=app.extensions['security'].datastore;email='metadata.outsider.qa@argiloteca.invalid';user=store.find_user(email=email)
 if user is None:user=store.create_user(email=email,password=hash_password(password),active=True,confirmed_at=datetime.now(timezone.utc))
 else:user.password=hash_password(password);user.active=True;user.confirmed_at=datetime.now(timezone.utc)
 uid=user.id;db.session.commit()
c=app.test_client();login=c.get('/login/',base_url=base);token=etree.HTML(login.data).xpath('//input[@name="csrf_token"]/@value')[0];assert c.post('/login/',base_url=base,data={'email':email,'password':password,'csrf_token':token}).status_code==302
page=c.get('/scientific/deposit',base_url=base);cfg=json.loads(etree.HTML(page.data).xpath('//script[@id="science-config"]/text()')[0]);headers={'X-CSRFToken':cfg['csrf_token']}
checks={}
for name,method,path,body in [
 ('other owner draft read','GET','/scientific/deposit/'+r['records']['new_version_draft'],None),
 ('other owner draft update','PUT','/scientific/drafts/'+r['records']['new_version_draft'],{'custom_fields':{}}),
 ('other owner published edit','POST','/scientific/records/'+r['records']['scientific']+'/edit',{}),
 ('restricted scientific view','GET','/scientific/records/'+r['records']['restricted'],None),
 ('restricted export','GET','/scientific/records/'+r['records']['restricted']+'/export',None),
]:
 response=c.open(path,method=method,base_url=base,headers=headers,json=body);assert response.status_code in [403,404],(name,response.status_code);checks[name]=response.status_code
with app.app_context():
 user=store.find_user(email=email);user.active=False;db.session.commit()
(root/'permissions.json').write_text(json.dumps(checks,indent=2));print(json.dumps(checks,indent=2))
