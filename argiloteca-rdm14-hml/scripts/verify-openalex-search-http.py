from copy import deepcopy
import json,re
from unittest.mock import patch
from flask import jsonify
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata
from argiloteca.openalex.adapters import prepare,verify_snapshot,digest
from argiloteca.openalex.service import review_snapshot
app=create_ui();evidence={}
def fingerprint():
 return {m.__name__:digest([(str(r.id),r.json) for r in m.query.order_by(m.id)]) for m in (RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata)}
with app.app_context():before=fingerprint();user_id=db.session.get(User,4).get_id()
client=app.test_client()
def call(method,path,**kwargs):
 with app.app_context():return getattr(client,method)(path,**kwargs)
assert call('get','/administration/openalex/').status_code==403
with client.session_transaction() as s:
 s['_user_id']=user_id;s['_fresh']=True;s['identity.id']=4;s['identity.auth_type']='session'
response=call('get','/administration/openalex/?ln=pt');assert response.status_code==200
assert 'name="free_text"' in response.text and 'Sem vocabulário (busca livre)' in response.text
csrf=re.search(r'name="csrf_token" value="([^"]+)"',response.text).group(1)
with patch('argiloteca.openalex.views.enqueue',side_effect=lambda job:jsonify(job.params)):
 for values,mode in (({'free_text':'DRX'},'free'),({'term':'kaolinite'},'vocabulary'),({'term':'kaolinite','free_text':'DRX'},'combined')):
  response=call('post','/administration/openalex/extract',data={'csrf_token':csrf,**values})
  assert response.status_code==200,response.status_code
  assert response.json['search_mode']==mode,response.json
  evidence[mode+'_post_accepted']=True
 for values in ({},{'term':'unknown','free_text':'DRX'},{'free_text':'x'*501},{'term':'kaolinite','free_text':'DRX','offset':1}):
  assert call('post','/administration/openalex/extract',data={'csrf_token':csrf,**values}).status_code==303
assert call('post','/administration/openalex/extract',data={'free_text':'DRX'}).status_code==400
assert call('get','/administration/openalex/?ln=en').status_code==200
with app.app_context():
 root=app.config['ARGILOTECA_OPENALEX_ROOT'];prepared=[]
 for lot in ('v59_20261024_064248_ve80ukan','v59_20261024_064332_71ahj7k3'):
  snapshot=prepare(root,lot);verify_snapshot(root,snapshot)
  assert snapshot['extraction_search']['queries'] and 'busca.json' in snapshot['input_hashes']
  checked=review_snapshot(root,snapshot,4)
  assert len(checked['records'])==1 and checked['summary']['bloqueado']==0,checked['summary']
  prepared.append({'lot':lot,'summary':checked['summary'],'queries':snapshot['extraction_search']['queries'],
                   'classification':checked['records'][0]['classification']['state']})
 assert before==fingerprint()
 evidence.update(http_csrf=True,anonymous_denied=True,english_page=True,real_lots_prepared=prepared,native_corpus_unchanged=True)
print(json.dumps(evidence,ensure_ascii=False))
