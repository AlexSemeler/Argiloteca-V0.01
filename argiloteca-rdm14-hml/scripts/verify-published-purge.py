"""Native published purge tests. Only labelled restricted fixtures are mutated."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import uuid
from unittest.mock import patch
import zipfile
from invenio_app.factory import create_ui
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records import models as m
from invenio_files_rest.models import FileInstance,ObjectVersion,Bucket
from invenio_pidstore.models import PersistentIdentifier,PIDStatus
from sqlalchemy_continuum import version_class
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.tasks import run
from argiloteca.openalex.duplicates import backup_path
from argiloteca.openalex import maintenance as c

app=create_ui();evidence={};fixtures=[]
with app.app_context():
 identity=actor_identity(4)
 baseline={cls.__tablename__:{str(k):digest(j) for k,j in db.session.query(cls.id,cls.json).yield_per(25)} for cls in (m.RDMRecordMetadata,m.RDMDraftMetadata,m.RDMParentMetadata)}
 def create(publish=True):
  payload={'metadata':{'title':'TESTE SINTÉTICO — purga publicada '+uuid.uuid4().hex[:8],
   'resource_type':{'id':'publication-article'},'publication_date':'2026-10-24',
   'creators':[{'person_or_org':{'type':'personal','family_name':'Teste','given_name':'Purga','name':'Teste, Purga'}}]},
   'files':{'enabled':True},'access':{'record':'restricted','files':'restricted'}}
  item=service.create(identity,payload);rid=item.id;fixtures.append(rid)
  data=b'TEST SYNTHETIC PURGE - exact backup bytes'
  service.draft_files.init_files(identity,rid,[{'key':'original.txt'}]);service.draft_files.set_file_content(identity,rid,'original.txt',BytesIO(data),content_length=len(data));service.draft_files.commit_file(identity,rid,'original.txt')
  if publish:service.publish(identity,rid)
  print('FIXTURE',rid,flush=True);return rid
 def preview(rid):
  p=c.plan(identity,4,'record',rid,'purge_published',record_kind='published',reason='TEST ONLY — native published purge verification')
  source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':p});db.session.add(source);db.session.commit();return source
 def apply(source,expected='completed'):
  p=source.snapshot['plan'];job=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(p),'test_only':True},snapshot={'plan':deepcopy(p)});db.session.add(job);db.session.commit();jid=job.id;run(jid);db.session.expire_all();job=db.session.get(OpenAlexJob,jid)
  assert job.state==expected,(job.state,job.result);return job
 rid=create();source=preview(rid);assert not source.snapshot['plan']['blockers'],source.snapshot['plan']['blockers']
 before=service.read(identity,rid).to_dict();uid=source.snapshot['plan']['record']['uuid'];parent=source.snapshot['plan']['record']['parent_uuid']
 # A backup failure and SQL failure cannot remove records or original bytes.
 with patch('argiloteca.openalex.published_purge.write_backup',side_effect=ValueError('TEST backup failure')):apply(source,'failed')
 assert service.read(identity,rid).to_dict()['files']['entries']==before['files']['entries']
 with patch('invenio_records_resources.services.uow.UnitOfWork.commit',side_effect=RuntimeError('TEST SQL commit failure')):apply(source,'failed')
 assert service.read(identity,rid).to_dict()['metadata']==before['metadata']
 evidence['backup_and_sql_failures_preserve_original']=True
 job=apply(source);assert job.result['purge']['phase']=='complete'
 for cls in (m.RDMRecordMetadata,m.RDMDraftMetadata):assert db.session.get(cls,uid) is None
 assert db.session.get(m.RDMParentMetadata,parent) is None
 for cls in (m.RDMRecordMetadata,m.RDMFileRecordMetadata,m.RDMMediaFileRecordMetadata):
  q=version_class(cls).query.filter_by(id=uid) if cls is m.RDMRecordMetadata else version_class(cls).query.filter_by(record_id=uid)
  assert not q.count()
 for entry in source.snapshot['plan']['purge']['file_instances']:assert db.session.get(FileInstance,entry['id']) is None
 for entry in source.snapshot['plan']['purge']['buckets']:assert db.session.get(Bucket,entry['id']) is None
 assert PersistentIdentifier.query.filter_by(pid_type='recid',pid_value=rid).one().status==PIDStatus.DELETED
 with zipfile.ZipFile(backup_path(job.id)) as archive:
  manifest=json.loads(archive.read('manifest.json'));assert archive.read(manifest['files'][0]['archive'])==b'TEST SYNTHETIC PURGE - exact backup bytes'
  assert manifest['plan']['purge']['history']['rdm_records_metadata_version']
 run(job.id);assert db.session.get(OpenAlexJob,job.id).state=='completed'
 evidence.update(physical_metadata_revisions_buckets_removed=True,backup_all_original_bytes=True,reserved_pid=True,idempotent_redelivery=True,job=job.id)
 # Shared file instances survive until their last native reference is gone.
 from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
 first=create();second=create(publish=False)
 source_record=service.read(identity,first)._record;other=service.read_draft(identity,second)._record
 original=source_record.files['original.txt'].object_version;fid=str(original.file_id)
 copy=original.copy(bucket=other.files.bucket,key='shared.txt')
 other.files.create('shared.txt',obj=copy,data={});other.files.commit('shared.txt')
 with UnitOfWork(db.session) as uow:uow.register(RecordCommitOp(other,indexer=service.indexer));uow.commit()
 approved=preview(first);assert any(f['shared_references'] for f in approved.snapshot['plan']['purge']['file_instances'])
 apply(approved);assert db.session.get(FileInstance,fid) is not None
 with service.draft_files.get_file_content(identity,second,'shared.txt').open_stream('rb') as stream:assert stream.read()==b'TEST SYNTHETIC PURGE - exact backup bytes'
 service.publish(identity,second);apply(preview(second));assert db.session.get(FileInstance,fid) is None
 evidence['shared_native_binary_preserved_until_last_reference']=True
 # Hidden object versions and media are included in the same verified backup.
 rid=create();record=service.read(identity,rid)._record
 record.files.bucket.locked=False
 old=ObjectVersion.create(record.files.bucket,'historical.txt',stream=BytesIO(b'TEST historical object'))
 record.files.bucket.locked=True
 # Create media through native file management while drafting a publication.
 service.edit(identity,rid)
 with UnitOfWork(db.session) as uow:
  media=service.read_draft(identity,rid)._record;media.media_files.enabled=True
  if not media.media_files.bucket:media.media_files.create_bucket()
  media.media_files.create('figure.txt',stream=BytesIO(b'TEST media'),transfer={'type':'L'});media.media_files.commit('figure.txt')
  uow.register(RecordCommitOp(media,indexer=service.indexer));uow.commit()
 service.publish(identity,rid)
 p=preview(rid);assert not p.snapshot['plan']['blockers'],p.snapshot['plan']['blockers']
 job=apply(p)
 with zipfile.ZipFile(backup_path(job.id)) as archive:
  saved=json.loads(archive.read('manifest.json'));contents={archive.read(f['archive']) for f in saved['files']}
  assert b'TEST media' in contents and b'TEST historical object' in contents
 evidence['hidden_objects_and_media_backed_up_and_purged']=True
 # A changed record and active edit cannot be purged from an old preview.
 rid=create();p=preview(rid);draft=service.edit(identity,rid)
 blocked=preview(rid);assert blocked.snapshot['plan']['blockers'];apply(p,'failed')
 service.delete_draft(identity,rid)
 # Physical cleanup failure is distinct from SQL rollback, and resumes safely.
 p=preview(rid)
 with patch('invenio_files_rest.storage.pyfs.PyFSFileStorage.delete',side_effect=OSError('TEST storage unavailable')):job=apply(p,'failed')
 assert job.result['purge']['phase']=='cleanup' and job.result['purge']['files'][0]['database_removed']
 assert db.session.get(m.RDMRecordMetadata,p.snapshot['plan']['record']['uuid']) is None
 # Failed cleanup cannot replace the approved backup hash with a corrupt ZIP.
 original_zip=backup_path(job.id).read_bytes();approved_sha=job.result['backup']['sha256']
 backup_path(job.id).write_bytes(b'TEST corrupt backup')
 job.state='queued';db.session.commit();run(job.id);db.session.expire_all()
 assert job.state=='failed' and job.result['backup']['sha256']==approved_sha
 assert not job.result['purge']['files'][0].get('storage_removed')
 backup_path(job.id).write_bytes(original_zip)
 job.state='queued';db.session.commit();run(job.id);assert job.state=='completed',job.result
 evidence['cleanup_rejects_changed_backup_without_repinning_checksum']=True
 evidence['stale_edit_blocked_and_cleanup_resumable_after_sql_removal']=True
 # Other versions are dependencies, never silently swept into one purge.
 rid=create();service.new_version(identity,rid)
 assert preview(rid).snapshot['plan']['blockers']
 newdraft=m.RDMDraftMetadata.query.filter(m.RDMDraftMetadata.parent_id==service.read(identity,rid)._record.parent.id,m.RDMDraftMetadata.json.isnot(None)).one()
 service.delete_draft(identity,newdraft.json['id']);apply(preview(rid))
 evidence['other_versions_block_individual_purge']=True
 # Dependencies from scientific links, RAW associations and requests block purge.
 rid=create();target=create();record=service.read(identity,target)._record
 record['metadata']={**record['metadata'],'related_identifiers':[{'identifier':app.config['SITE_UI_URL'].rstrip('/')+'/records/'+rid,'scheme':'url','relation_type':{'id':'references'}}]}
 with UnitOfWork(db.session) as uow:uow.register(RecordCommitOp(record,indexer=service.indexer));uow.commit()
 assert preview(rid).snapshot['plan']['blockers']
 record=service.read(identity,target)._record;record['metadata'].pop('related_identifiers',None)
 with UnitOfWork(db.session) as uow:uow.register(RecordCommitOp(record,indexer=service.indexer));uow.commit()
 from argiloteca.scientific.drx_links import set_link
 raw={'id':'purgetest'+uuid.uuid4().hex[:8],'sha256':'b'*64}
 set_link(identity,raw,rid,state='pending',evidence='TEST ONLY — purge dependency',expected_revision=0,actor=4);db.session.commit()
 assert preview(rid).snapshot['plan']['blockers']
 set_link(identity,raw,rid,state='removed',evidence='TEST ONLY — dependency released',expected_revision=1,actor=4);db.session.commit()
 from invenio_requests.records.models import RequestMetadata
 request=RequestMetadata(id=uuid.uuid4(),json={'topic':{'record':rid},'title':'TEST ONLY — purge dependency'})
 db.session.add(request);db.session.commit();assert preview(rid).snapshot['plan']['blockers']
 db.session.delete(request);db.session.commit();apply(preview(rid));apply(preview(target))
 evidence['incoming_references_drx_and_requests_block_purge']=True
 # Leave one labelled publication for browser preview; remove it after screenshots.
 demo=create();demo_preview=preview(demo);evidence.update(demo_record=demo,demo_preview=demo_preview.id,fixtures=fixtures)
 for cls in (m.RDMRecordMetadata,m.RDMDraftMetadata,m.RDMParentMetadata):
  for uid,sha in baseline[cls.__tablename__].items():assert digest(db.session.get(cls,uid).json)==sha,(cls,uid)
 evidence['all_preexisting_native_records_unchanged']=True
 Path('/tmp/published-purge-results.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence))
