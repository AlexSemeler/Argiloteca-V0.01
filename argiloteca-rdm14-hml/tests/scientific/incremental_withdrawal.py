"""Native metadata-only update and temporary withdrawal, on synthetic records only."""
import json
from pathlib import Path
from datetime import datetime,timezone
from flask import g
from invenio_app.factory import create_ui
from invenio_access.permissions import system_identity
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_search import current_search_client as search
from fixtures import publication
root=Path('/tmp/scientific-tests/evidence');report=json.loads((root/'integration.json').read_text());app=create_ui()
with app.app_context():
 g.identity=system_identity;rid=report['records']['scientific'];record=service.read(system_identity,rid);before=record.to_dict()['updated']
 draft=service.edit(system_identity,rid);data=draft.to_dict();data['custom_fields']['arg:amostras'][0]['observacoes_campo']='Incremental QA — updated only a scientific field'
 service.update_draft(system_identity,rid,data);updated=service.publish(system_identity,rid).to_dict();after=updated['updated'];assert after!=before
 # Separate disposable public record becomes restricted; its former OAI ID
 # must disappear because the native Identify advertises deletedRecord=no.
 payload=publication();payload['metadata']['title']='SINTÉTICO — QA withdrawal';draft=service.create(system_identity,payload);item=service.publish(system_identity,draft.id).to_dict();wid=item['id'];oai=item['pids']['oai']['identifier']
 draft=service.edit(system_identity,wid);data=draft.to_dict();data['access']={'record':'restricted','files':'restricted'};service.update_draft(system_identity,wid,data);restricted=service.publish(system_identity,wid).to_dict();assert restricted['access']['record']=='restricted'
 search.indices.refresh(index=app.config['SEARCH_INDEX_PREFIX']+service.config.record_cls.index._name)
 stamp=datetime.fromisoformat(after).astimezone(timezone.utc).replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%SZ')
 report['incremental']={'before':before,'after':after,'from':stamp,'until':stamp,'record_id':rid,'expected_value':'Incremental QA — updated only a scientific field'}
 report['withdrawal']={'record_id':wid,'former_identifier':oai,'policy':'native deletedRecord=no; anonymous absence; periodic full reconciliation required'}
 (root/'integration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({'incremental':report['incremental'],'withdrawal':report['withdrawal']},ensure_ascii=False))
