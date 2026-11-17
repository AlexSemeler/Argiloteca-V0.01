"""Rebuild only the current RDM record/draft indices; never commits record JSON."""
import json,hashlib,time
from datetime import datetime,timezone
from invenio_app.factory import create_ui
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_db import db
from invenio_search import current_search_client as search
from sqlalchemy import select
app=create_ui();report={'started':datetime.now(timezone.utc).isoformat(),'indices':[]}
with app.app_context():
 for cls,indexer in [(service.config.record_cls,service.indexer),(service.config.draft_cls,service.draft_indexer)]:
  model=cls.model_cls
  ids=list(db.session.scalars(select(model.id).where(model.json.isnot(None))))
  before=hashlib.sha256();after=hashlib.sha256();count=0
  for uuid in ids:
   record=cls.get_record(uuid)
   if record.is_deleted:continue
   value=json.dumps(record.model.json,sort_keys=True,ensure_ascii=False).encode();before.update(value)
   updated=record.model.updated
   indexer.index(record)
   assert record.model.updated==updated
   after.update(json.dumps(record.model.json,sort_keys=True,ensure_ascii=False).encode());count+=1
  assert before.hexdigest()==after.hexdigest()
  alias=app.config['SEARCH_INDEX_PREFIX']+cls.index._name;search.indices.refresh(index=alias)
  report['indices'].append({'class':cls.__name__,'alias':alias,'indexed':count,'SQL_content_unchanged_sha256':before.hexdigest()})
report['finished']=datetime.now(timezone.utc).isoformat();print(json.dumps(report,indent=2))
