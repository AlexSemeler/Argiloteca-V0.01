import json,uuid
from copy import deepcopy
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from argiloteca.openalex.models import OpenAlexJob,OpenAlexClaim
from argiloteca.openalex.adapters import digest,converter
from argiloteca.openalex.service import actor_identity,inventory,matches
from argiloteca.openalex import maintenance as c
from argiloteca.openalex.tasks import run
app=create_ui()
with app.app_context():
 identity=actor_identity(4);work='W'+str(int(uuid.uuid4().hex[:12],16));doi='10.99999/test-maintenance-'+uuid.uuid4().hex
 payload={'metadata':{'title':'TESTE SINTÉTICO — reserva de identidade removida','resource_type':{'id':'publication-article'},'creators':[{'person_or_org':{'type':'personal','family_name':'Teste','name':'Teste'}}], 'identifiers':[{'scheme':'doi','identifier':doi},{'scheme':'url','identifier':'https://openalex.org/'+work}]},'files':{'enabled':False},'access':{'record':'restricted','files':'restricted'}}
 item=service.create(identity,payload);rid=item.id
 assert db.session.get(OpenAlexClaim,'doi:'+doi) is None
 p=c.plan(identity,4,'record',rid,'delete_draft',record_kind='draft',reason='TEST ONLY — legacy identity reservation')
 source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':p});db.session.add(source);db.session.commit()
 job=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(p),'test_only':True},snapshot={'plan':deepcopy(p)});db.session.add(job);db.session.commit();run(job.id)
 assert db.session.get(OpenAlexJob,job.id).state=='completed',job.result
 for token in ('doi:'+doi,'openalex:'+work):assert db.session.get(OpenAlexClaim,token).draft_id==rid
 metadata=converter(app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
 found=matches({'payload':payload},inventory(metadata),metadata);assert len(found)==1 and found[0]['id']==rid
 evidence={'legacy_doi_openalex_claims_created_before_deletion':True,'deleted_item_cannot_be_silently_recreated':True,'synthetic_fixture_removed':rid,'audit_job':job.id}
 print(json.dumps(evidence))
