"""Prepare a stable mixed OAI test set and a genuine restricted synthetic file."""
import json,inspect
from pathlib import Path
from io import BytesIO
from datetime import datetime,timezone
from flask import g
from invenio_app.factory import create_ui
from fixtures import publication
from invenio_access.permissions import system_identity
from invenio_db import db
from invenio_search import current_search_client as search
from invenio_oaiserver.models import OAISet
from invenio_rdm_records.proxies import current_rdm_records_service as service
root=Path('/tmp/scientific-tests/evidence');report=json.loads((root/'integration.json').read_text());app=create_ui()
with app.app_context():
 g.identity=system_identity
 data=publication();data['metadata']['title']='SINTÉTICO — QA actual restricted file';data['files']={'enabled':True};data['access']={'record':'public','files':'restricted'}
 draft=service.create(system_identity,data);rid=draft.id
 report['records']['files_restricted']=rid
 service.draft_files.init_files(system_identity,rid,[{'key':'synthetic.txt'}])
 content=b'SYNTHETIC Argiloteca QA file. Not research data.\n'
 service.draft_files.set_file_content(system_identity,rid,'synthetic.txt',BytesIO(content),content_length=len(content))
 service.draft_files.commit_file(system_identity,rid,'synthetic.txt')
 item=service.publish(system_identity,rid).to_dict()
 report['oai']['files_restricted']=item['pids']['oai']['identifier']
 assert item['access']['record']=='public' and item['access']['files']=='restricted'
 assert item['files']['entries']['synthetic.txt']['size']==len(content)
 report['checks']['actual restricted file persisted']=True
 # The set is an explicit stable ID list, with both legacy and profiled records.
 ids={report['records'][k] for k in ['scientific','legacy','files_restricted']}
 for hit in service.search(system_identity,params={'size':30}).to_dict()['hits']['hits']:
  if hit['access']['record']=='public':ids.add(hit['id'])
  if len(ids)>=15:break
 query='id:('+ ' OR '.join(sorted(ids))+')'
 row=db.session.query(OAISet).filter_by(spec='argiloteca-hml-metadata-qa-v1').one_or_none()
 if row is None:row=OAISet(spec='argiloteca-hml-metadata-qa-v1',name='Synthetic metadata extension QA — mixed stable set');db.session.add(row)
 row.search_pattern=query;row.description='Homologation validation set; synthetic QA plus existing public legacy records.';db.session.commit()
 # Native OAI set query fetcher evaluates this query at harvest time.
 report['harvest_set']={'spec':row.spec,'record_ids':sorted(ids),'count':len(ids)}
 # Metadata-only change after a separate UTC second; collector must observe it.
 before=service.read(system_identity,report['records']['scientific']).to_dict()['updated'];report['before_incremental']=before
 for cls in [app.config['RDM_RECORD_CLS'],app.config['RDM_DRAFT_CLS']]:search.indices.refresh(index=app.config['SEARCH_INDEX_PREFIX']+cls.index._name)
 (root/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'checks':report['checks'],'harvest_set':report['harvest_set']},ensure_ascii=False))
