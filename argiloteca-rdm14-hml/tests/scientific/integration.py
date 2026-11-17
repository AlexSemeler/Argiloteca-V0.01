"""Real native service/SQL/index/WSGI tests. Creates labelled synthetic HML records.

Run inside the live HML web-ui container, with fixtures.py alongside this file.
Credentials are saved locally with mode 0600 for the browser test, never printed.
"""
import json,re,secrets,os,sys,subprocess
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from lxml import etree
from invenio_app.factory import create_ui,create_api
from invenio_db import db
from invenio_access.permissions import system_identity
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_search import current_search_client as search
from flask_security.utils import hash_password
from argiloteca.scientific import PROFILE_FIELD,PROFILE_VERSION,SEARCH_FIELD
from argiloteca.scientific.models import BINDINGS
from fixtures import publication

app=create_ui();base='https://127.0.0.1:5101';out=Path('/tmp/scientific-tests/evidence');out.mkdir(exist_ok=True)
report={'checks':{},'records':{},'started':datetime.now(timezone.utc).isoformat()}
def check(name,condition):
    if not condition:raise AssertionError(name)
    report['checks'][name]=True
    (out/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('PASS',name,flush=True)

def main():
    credentials=out/'credentials.json'
    with app.app_context():
        store=app.extensions['security'].datastore
        email='metadata.qa.20261018@argiloteca.invalid'
        if credentials.exists():auth=json.loads(credentials.read_text())
        else:
            auth={'email':email,'password':secrets.token_urlsafe(32)}
            credentials.write_text(json.dumps(auth));credentials.chmod(0o600)
        user=store.find_user(email=email)
        if user is None:user=store.create_user(email=email,password=hash_password(auth['password']),active=True,confirmed_at=datetime.now(timezone.utc))
        else:user.password=hash_password(auth['password']);user.active=True;user.confirmed_at=datetime.now(timezone.utc)
        db.session.commit();report['qa_user_id']=user.id
    client=app.test_client();anonymous=app.test_client();api=create_api();anonymous_api=api.test_client()
    def call(path,method='GET',body=None,expected=200,token=None,c=client):
        if method=='PUT' and path.startswith('/scientific/drafts/') and body:
            body=deepcopy(body);body['custom_fields']={k:v for k,v in body.get('custom_fields',{}).items() if k in {*BINDINGS,PROFILE_FIELD}}
        if path.startswith('/api/'):
            c=anonymous_api;path=path.removeprefix('/api')
        response=c.open(path,method=method,base_url=base,json=body,headers={'X-CSRFToken':token} if token else {})
        if response.status_code!=expected:raise AssertionError(f'{method} {path}: {response.status_code}; {response.get_data(as_text=True)[:1200]}')
        return response
    login=call('/login/');csrf=etree.HTML(login.data).xpath('//input[@name="csrf_token"]/@value')[0]
    response=client.post('/login/',base_url=base,data={**auth,'csrf_token':csrf},follow_redirects=False)
    check('owner real form login',response.status_code==302 and '/login' not in response.location)
    page=call('/scientific/deposit');doc=etree.HTML(page.data)
    cfg=json.loads(doc.xpath('//script[@id="science-config"]/text()')[0]);csrf=cfg['csrf_token']
    check('structured form authenticated',len(cfg['schemas'])==14)
    check('anonymous form requires login',anonymous.get('/scientific/deposit',base_url=base).status_code in [302,401])
    check('CSRF enforced',client.post('/scientific/drafts',base_url=base,json=publication()).status_code==400)
    invalid=publication();invalid['custom_fields']['arg:amostras'][0]['latitude']='not-a-number'
    draft=call('/scientific/drafts','POST',invalid,201,csrf).json;badid=draft['record']['id']
    report['records']['invalid_draft']=badid
    check('invalid draft saves values with errors',bool(draft['errors']) and draft['record']['custom_fields']['arg:amostras'][0]['latitude']=='not-a-number')
    check('invalid draft publication blocked',call('/scientific/drafts/'+badid+'/publish','POST',{},422,csrf).status_code==422)
    # Correct it through the same custom authoring endpoint.
    data=publication();data['revision_id']=draft['revision_id']
    fixed=call('/scientific/drafts/'+badid,'PUT',data,200,csrf).json
    check('corrected draft no errors',not fixed['errors'])
    check('unrelated custom field survives scientific edit',fixed['record']['custom_fields']['arg:usos_descricao']==data['custom_fields']['arg:usos_descricao'])
    stale=deepcopy(data);stale['revision_id']=0
    check('stale draft edit rejected',call('/scientific/drafts/'+badid,'PUT',stale,409,csrf).status_code==409)
    published=call('/scientific/drafts/'+badid+'/publish','POST',{},200,csrf).json['record'];id_=published['id'];report['records']['scientific']=id_
    (out/'expected.json').write_text(json.dumps(data['custom_fields'],ensure_ascii=False,indent=2))
    (out/'record.json').write_text(json.dumps(published,ensure_ascii=False,indent=2))
    check('publication succeeds without DOI',published['is_published'] and 'doi' not in published.get('pids',{}))
    # A wholly separate process/connection verifies committed canonical SQL JSON.
    script="""import json,sys
from invenio_app.factory import create_ui
from invenio_rdm_records.records.models import RDMRecordMetadata
from invenio_db import db
app=create_ui()
with app.app_context():
 row=db.session.get(RDMRecordMetadata,sys.argv[1]);print(json.dumps(row.json['custom_fields'],ensure_ascii=False))
"""
    with app.app_context():
        canonical=service.read(system_identity,id_)._record
        uuid=str(canonical.id)
    result=subprocess.run([sys.executable,'-c',script,uuid],capture_output=True,text=True,check=True)
    persisted=json.loads(result.stdout.strip());check('independent process committed SQL equals input',persisted==data['custom_fields'])
    check('projection not persisted in SQL',SEARCH_FIELD not in persisted)
    (out/'sql-custom-fields.json').write_text(json.dumps(persisted,ensure_ascii=False,indent=2))
    check('anonymous public REST reread equals source',call('/api/records/'+id_,c=anonymous).json['custom_fields']==persisted)
    with app.app_context():
        for cls in [app.config['RDM_RECORD_CLS'],app.config['RDM_DRAFT_CLS']]:
            alias=app.config['SEARCH_INDEX_PREFIX']+cls.index._name
            search.indices.refresh(index=alias)
    # The same mineral/latitude must match one nested item, not different items.
    positive=call('/scientific/search.json?arg_mineral=Kaolinite&arg_mineral_sample=0001').json
    negative=call('/scientific/search.json?arg_mineral=Kaolinite&arg_mineral_latitude=1').json
    check('nested search positive',id_ in [r['id'] for r in positive['hits']['hits']])
    check('nested search excludes cross-item false match',id_ not in [r['id'] for r in negative['hits']['hits']])
    check('scientific facets returned',all(k in positive['scientific_facets'] for k in ['arg_samples','arg_analyses','arg_minerals']))
    (out/'search.json').write_text(json.dumps(positive,ensure_ascii=False,indent=2))
    xml=call('/scientific/records/'+id_+'/export',c=anonymous);(out/'record.xml').write_bytes(xml.data)
    native=call('/records/'+id_+'/export/argiloteca',c=anonymous)
    check('native XML export wired',etree.fromstring(native.data).tag==etree.fromstring(xml.data).tag)
    check('XML unknown enrichments not exported',b'unknown_enrichment' not in xml.data)
    # Native edit and new-version flows must preserve every extension value.
    edited=call('/scientific/records/'+id_+'/edit','POST',{},200,csrf).json
    change=deepcopy(data);change['revision_id']=edited['revision_id'];change['custom_fields']['arg:amostras'][0]['observacoes_campo']='Updated scientific field only / Campo atualizado'
    call('/scientific/drafts/'+id_,'PUT',change,200,csrf)
    updated=call('/scientific/drafts/'+id_+'/publish','POST',{},200,csrf).json['record']
    report['updated']=updated['updated'];check('scientific-only edit republishes',updated['custom_fields']['arg:amostras'][0]['observacoes_campo']==change['custom_fields']['arg:amostras'][0]['observacoes_campo'])
    with app.app_context():version=service.new_version(system_identity,id_).to_dict()
    versionid=version['id'];report['records']['new_version_draft']=versionid
    check('new version conserves all scientific and unrelated fields',version['custom_fields']==updated['custom_fields'])
    # Legacy and access-policy fixtures, always synthetic.
    for label,record_access,file_access,profile in [('legacy','public','public',False),('restricted','restricted','restricted',True),('files_restricted','public','restricted',True)]:
        value=publication();value['metadata']['title']='SINTÉTICO — QA '+label
        if not profile:value['custom_fields']={'arg:usos_descricao':'Legacy without scientific profile'}
        value['access']={'record':record_access,'files':file_access}
        draft=call('/scientific/drafts','POST',value,201,csrf).json
        check(label+' draft validates',not draft['errors'])
        item=call('/scientific/drafts/'+draft['record']['id']+'/publish','POST',{},200,csrf).json['record'];report['records'][label]=item['id']
    check('restricted REST denied anonymously',anonymous_api.get('/records/'+report['records']['restricted'],base_url=base).status_code in [403,404])
    check('restricted XML denied anonymously',anonymous.get('/scientific/records/'+report['records']['restricted']+'/export',base_url=base).status_code in [403,404])
    check('draft denied anonymously',anonymous_api.get('/records/'+versionid+'/draft',base_url=base).status_code in [403,404])
    with app.app_context():
        search.indices.refresh(index=app.config['SEARCH_INDEX_PREFIX']+'rdmrecords*')
        report['oai']={label:service.read(system_identity,rid).to_dict().get('pids',{}).get('oai',{}).get('identifier') for label,rid in report['records'].items() if label in ['scientific','legacy','restricted','files_restricted']}
    (out/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('COMPLETE',json.dumps(report['records']),flush=True)

if __name__=='__main__':main()
