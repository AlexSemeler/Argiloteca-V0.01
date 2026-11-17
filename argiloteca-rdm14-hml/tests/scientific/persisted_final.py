"""Read-only committed SQL proof, in a separate Python process and connection."""
import json,subprocess,sys
from pathlib import Path
from invenio_app.factory import create_ui
from invenio_access.permissions import system_identity
from invenio_rdm_records.proxies import current_rdm_records_service as service
from fixtures import publication
app=create_ui()
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101'
 record=service.read(system_identity,'4wy5b-k2304')._record
 uuid=str(record.id)
script='''import json,sys
from invenio_app.factory import create_ui
from invenio_rdm_records.records.models import RDMRecordMetadata
from invenio_db import db
app=create_ui()
with app.app_context():
 row=db.session.get(RDMRecordMetadata,sys.argv[1]);print(json.dumps(row.json['custom_fields'],ensure_ascii=False))
'''
result=subprocess.run([sys.executable,'-c',script,uuid],capture_output=True,text=True,check=True)
actual=json.loads(result.stdout);expected=publication()['custom_fields'];expected['arg:amostras'][0]['observacoes_campo']='Incremental QA — updated only a scientific field';expected['arg:amostras'][0]['descricao_local']='Playwright — edited complete nested scientific record'
assert actual==expected,'Committed SQL differs from independent expected values'
print(json.dumps({'verified':True,'record_id':'4wy5b-k2304','uuid':uuid,'source':'fresh subprocess, native ORM direct SQL JSONB','custom_fields':actual},ensure_ascii=False,indent=2))
