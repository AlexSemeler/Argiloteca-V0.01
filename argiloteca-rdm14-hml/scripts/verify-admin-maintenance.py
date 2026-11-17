"""Native maintenance integration. Mutations use labelled synthetic fixtures only."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import re
import uuid
from unittest.mock import patch
import zipfile

from invenio_app.factory import create_ui
from invenio_db import db
from invenio_accounts.models import User
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata
from invenio_communities.proxies import current_communities
from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
from invenio_rdm_records.services.communities.service import ParentRecordCommitOp
from argiloteca.openalex import maintenance as clean
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.classification import community_catalog
from argiloteca.openalex.duplicates import backup_path
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.tasks import run

app=create_ui();evidence={};fixtures=[]
with app.app_context():
    identity=actor_identity(4);user_id=db.session.get(User,4).get_id()
    original={cls.__name__:{str(key):digest(data) for key,data in db.session.query(cls.id,cls.json).yield_per(25)} for cls in (RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata)}
    print('BASELINE captured',flush=True)
    job_hash=db.func.md5(db.cast(db.func.jsonb_build_array(OpenAlexJob.params,OpenAlexJob.state,OpenAlexJob.updated),db.Text))
    original_jobs=dict(db.session.query(OpenAlexJob.id,job_hash))
    print('JOB BASELINE captured',flush=True)
    catalog=community_catalog(identity);first=catalog['caulim-serpentina']['id'];second=catalog['esmectitas']['id']
    def create():
        payload={'metadata':{'title':'TESTE SINTÉTICO — manutenção '+uuid.uuid4().hex[:8],
            'resource_type':{'id':'publication-article'},'publication_date':'2026-10-24',
            'creators':[{'person_or_org':{'type':'personal','name':'Manutenção, Teste','family_name':'Manutenção','given_name':'Teste'}}]},
            'files':{'enabled':True},'access':{'record':'restricted','files':'restricted'}}
        item=service.create(identity,payload);fixtures.append(item.id)
        content=b'TEST SYNTHETIC ONLY - keep exact original bytes'
        service.draft_files.init_files(identity,item.id,[{'key':'fixture.txt'}])
        service.draft_files.set_file_content(identity,item.id,'fixture.txt',BytesIO(content),content_length=len(content))
        service.draft_files.commit_file(identity,item.id,'fixture.txt')
        with UnitOfWork(db.session) as uow:
            for cid in (first,second):item._record.parent.communities.add(current_communities.service.record_cls.pid.resolve(cid),default=cid==first)
            uow.register(ParentRecordCommitOp(item._record.parent,indexer_context={'service':service},bulk_index=False));uow.commit()
        return item.id
    def preview(kind,target,action,**kw):
        p=clean.plan(identity,4,kind,target,action,reason='TESTE SINTÉTICO: validação da manutenção',**kw)
        source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':p})
        db.session.add(source);db.session.commit();return source
    def apply(source,expect='completed'):
        p=source.snapshot['plan'];j=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(p),'test_only':True},snapshot={'plan':deepcopy(p)})
        db.session.add(j);db.session.commit();run(j.id);db.session.expire_all();j=db.session.get(OpenAlexJob,j.id)
        assert j.state==expect,(j.state,j.result);return j
    rid=create();print('SYNTHETIC draft',rid,flush=True);before=service.read_draft(identity,rid).to_dict()
    p=preview('record',rid,'delete_draft',record_kind='draft')
    assert service.read_draft(identity,rid).to_dict()['revision_id']==before['revision_id']
    with patch('argiloteca.openalex.maintenance.write_backup',side_effect=ValueError('TEST backup unavailable')):apply(p,'failed')
    assert service.read_draft(identity,rid).to_dict()['files']['entries']==before['files']['entries']
    evidence['preview_and_backup_failure_preserve_record']=True
    service.update_draft(identity,rid,{'metadata':{**before['metadata'],'title':before['metadata']['title']+' updated'},'files':{'enabled':True}})
    stale=apply(p,'failed');assert not backup_path(stale.id).exists();evidence['stale_preview_refused']=True
    p=preview('record',rid,'remove_community',record_kind='draft',selection=second);j=apply(p)
    after=service.read_draft(identity,rid).to_dict()
    assert after['parent']['communities']['ids']==[first] and after['parent']['communities']['default']==first
    assert after['parent']['access']==before['parent']['access'] and after['files']['entries']==before['files']['entries']
    evidence['draft_unlink_preserves_other_memberships_owner_and_files']=True
    p=preview('record',rid,'delete_draft',record_kind='draft');j=apply(p)
    with zipfile.ZipFile(backup_path(j.id)) as archive:
        manifest=json.loads(archive.read('manifest.json'));assert len(manifest['files'])==1
        assert archive.read(manifest['files'][0]['archive'])==b'TEST SYNTHETIC ONLY - keep exact original bytes'
    assert not RDMDraftMetadata.query.filter_by(id=p.snapshot['plan']['record']['uuid']).count()
    run(j.id);assert db.session.get(OpenAlexJob,j.id).state=='completed'
    evidence['draft_permanent_deletion_backup_and_idempotency']=True
    rid=create();service.publish(identity,rid);before=service.read(identity,rid).to_dict()
    p=preview('record',rid,'remove_community',record_kind='published',selection=second);apply(p)
    after=service.read(identity,rid).to_dict()
    assert after['parent']['communities']['ids']==[first] and after['files']['entries']==before['files']['entries']
    evidence['native_published_community_removal']=True
    from argiloteca.scientific.connections import FIELD,native_relation,relation_key
    from argiloteca.scientific.drx_links import set_link,DRXRecordLink,DRXLinkEvent
    target=create();service.publish(identity,target)
    record=service.read(identity,rid)._record
    connection={'record_id':target,'papel':'publicacao','relacao':'references','evidencia':'TEST ONLY — synthetic link','native_relation_created':False}
    citation=native_relation(connection)
    record['custom_fields']={FIELD:[connection],'arg:amostra_latitude':-30.0,'arg:amostra_longitude':-51.0}
    record['metadata']={**record['metadata'],'related_identifiers':[citation]}
    with UnitOfWork(db.session) as uow:
        uow.register(RecordCommitOp(record,indexer=service.indexer,index_refresh=True));uow.commit()
    assert preview('record',rid,'withdraw_record',record_kind='published').snapshot['plan']['blockers']
    assert preview('record',target,'withdraw_record',record_kind='published').snapshot['plan']['blockers']
    apply(preview('record',rid,'remove_connection',record_kind='published',selection=target))
    after=service.read(identity,rid).to_dict()
    assert not after['custom_fields'].get(FIELD)
    assert relation_key(citation) in {relation_key(r) for r in after['metadata']['related_identifiers']}
    apply(preview('record',rid,'clear_coordinates',record_kind='published',selection='legacy'))
    after=service.read(identity,rid).to_dict();assert 'arg:amostra_latitude' not in after['custom_fields']
    assert after['files']['entries']==before['files']['entries']
    evidence['scientific_unlink_preserves_preexisting_citation_and_incoming_guard']=True
    evidence['coordinate_removal_preserves_files_and_metadata']=True
    raw={'id':'rawtest'+uuid.uuid4().hex[:8],'sha256':'a'*64}
    set_link(identity,raw,rid,state='pending',evidence='TEST ONLY — synthetic DRX link',expected_revision=0,actor=4);db.session.commit()
    assert preview('record',rid,'withdraw_record',record_kind='published').snapshot['plan']['blockers']
    from types import SimpleNamespace
    with patch('argiloteca.scientific.admin_raw_views.store',return_value=SimpleNamespace(rows=lambda:[])):
        apply(preview('record',rid,'remove_drx',record_kind='published',selection=raw['id']))
    assert DRXRecordLink.query.filter_by(record_id=rid,raw_id=raw['id']).one().state=='removed'
    assert DRXLinkEvent.query.filter_by(record_id=rid,raw_id=raw['id']).count()==2
    evidence['drx_removal_audited_and_raw_library_not_mutated']=True
    # Discarding an edit must retain the existing publication and its files.
    service.edit(identity,rid);apply(preview('record',rid,'delete_draft',record_kind='draft'))
    assert service.read(identity,rid).to_dict()['files']['entries']==before['files']['entries']
    evidence['discard_edit_keeps_publication_and_files']=True
    before=service.read(identity,rid).to_dict()
    # A prior citation intentionally remains, so withdraw the source first.
    p=preview('record',rid,'withdraw_record',record_kind='published');j=apply(p)
    assert service.record_cls.pid.resolve(rid).deletion_status.is_deleted
    p=preview('record',rid,'restore_record',record_kind='published');apply(p)
    restored=service.read(identity,rid).to_dict()
    assert restored['metadata']==before['metadata'] and restored['files']['entries']==before['files']['entries']
    evidence['withdraw_and_restore_same_pid_files_metadata']=True
    # Retain native tombstone for a synthetic published record (native purge is unavailable).
    apply(preview('record',rid,'withdraw_record',record_kind='published'))
    apply(preview('record',target,'withdraw_record',record_kind='published'))
    target=OpenAlexJob(kind='prepare',state='failed',actor=4,params={'test_only':True},snapshot={'synthetic':True})
    db.session.add(target);db.session.commit();tid=target.id
    apply(preview('job',tid,'archive_job'));assert db.session.get(OpenAlexJob,tid).params['admin_archived']
    assert not clean.visible_jobs(OpenAlexJob.query).filter_by(id=tid).count()
    apply(preview('job',tid,'restore_job'));assert not db.session.get(OpenAlexJob,tid).params.get('admin_archived')
    child=OpenAlexJob(kind='prepare',state='failed',actor=4,params={'source_job':tid,'test_only':True});db.session.add(child);db.session.commit()
    assert preview('job',tid,'delete_job').snapshot['plan']['blockers']
    apply(preview('job',child.id,'delete_job'));apply(preview('job',tid,'delete_job'));assert db.session.get(OpenAlexJob,tid) is None
    evidence['job_archive_restore_delete_and_dependency_guard']=True
    # Leave one restricted synthetic draft for browser preview. No real record is touched.
    demo=create();demo_preview=preview('record',demo,'delete_draft',record_kind='draft')
    evidence.update(demo_draft=demo,demo_preview=demo_preview.id,fixtures=fixtures)
    Path('/tmp/admin-maintenance-native-results.json').write_text(json.dumps(evidence,indent=2))

client=app.test_client()
def call(method,path,**kw):
    with app.app_context():return getattr(client,method)(path,**kw)
assert call('get','/administration/maintenance/').status_code==403
with client.session_transaction() as session:
    session['_user_id']=user_id;session['_fresh']=True;session['identity.id']=4;session['identity.auth_type']='session'
for suffix in ('','?tab=jobs','?tab=lots','?tab=history','?ln=en',f'?record={demo}&record_kind=draft'):
    response=call('get','/administration/maintenance/'+suffix);assert response.status_code==200,(suffix,response.status_code,response.text[:300])
    assert 'no-store' in response.headers['Cache-Control']
response=call('get','/administration/maintenance/jobs/'+demo_preview.id);assert response.status_code==200
csrf=re.search(r'name="csrf_token" value="([^"]+)"',response.text).group(1)
path='/administration/maintenance/jobs/'+demo_preview.id+'/apply'
assert call('post',path,data={}).status_code==400
assert call('post',path,data={'csrf_token':csrf,'confirm':'yes','plan_sha256':digest(demo_preview.snapshot['plan'])}).status_code==409
with patch('argiloteca.openalex.maintenance_views.enqueue',side_effect=lambda j:('synthetic enqueue accepted',202)):
    assert call('post',path,data={'csrf_token':csrf,'confirm':'yes','plan_sha256':digest(demo_preview.snapshot['plan']),'permanent_confirmation':'EXCLUIR'}).status_code==202
assert call('get','/administration/maintenance/?record=x').status_code==400
evidence['admin_csrf_confirmation_private_cache_and_pt_en_rendering']=True
with app.app_context():
    for cls in (RDMRecordMetadata,RDMDraftMetadata,RDMParentMetadata):
        for key,value in original[cls.__name__].items():assert digest(db.session.get(cls,key).json)==value,(cls,key)
    for key,value in db.session.query(OpenAlexJob.id,job_hash).filter(OpenAlexJob.id.in_(original_jobs)):
        assert original_jobs[key]==value,key
    evidence['all_preexisting_records_parents_and_jobs_unchanged']=True
Path('/tmp/admin-maintenance-native-results.json').write_text(json.dumps(evidence,indent=2))
print(json.dumps(evidence,ensure_ascii=False))
