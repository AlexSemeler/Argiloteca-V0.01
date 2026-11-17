"""Local-only disposable RAW deletion integration; never targets existing samples.

Run in the local UI container with its temporary test suite installed.
Synthetic originals and audited backups intentionally remain private.
"""
from invenio_app.factory import create_ui
app=create_ui()
import hashlib,json,math,struct,time,unittest
from pathlib import Path
from invenio_db import db
from argiloteca.scientific.admin_raw_views import store
from argiloteca.scientific.admin_raw_service import submit_trio
from argiloteca.scientific.raw_removal import retired
from argiloteca.openalex import maintenance as clean
from argiloteca.openalex.models import OpenAlexJob
from argiloteca.openalex.service import actor_identity
from argiloteca.openalex.adapters import digest
from argiloteca.openalex.tasks import run
with app.app_context():
 assert app.config['SITE_UI_URL']=='https://127.0.0.1:5101'
 print('real_registry_enabled', 'invenio-rdm-records' in app.extensions,flush=True)
 assert 'invenio-rdm-records' in app.extensions
 repository=store();before={r['id'] for r in repository.rows()}
 def curve(role):
  count=1486;data=bytearray(1016+count*4);data[:8]=b'RAW1.01\0'
  struct.pack_into('<II',data,8,1,1);struct.pack_into('<II',data,712,304,count);struct.pack_into('<d',data,728,2.3);struct.pack_into('<d',data,888,.02);struct.pack_into('<d',data,952,1.5406)
  data[100:109]=b'TEST-ONLY'
  values=[12+102*math.exp(-((2.3+i*.02-(6+role*3))/.12)**2) for i in range(count)]
  struct.pack_into('<%df'%count,data,1016,*values);return bytes(data)
 files={p:('DISPOSABLE_DELETE_'+p+'.raw',curve(i)) for i,p in enumerate('NGC')}
 code=submit_trio(repository,files,preparation_confirmed=True,actor='4',test_only=True)
 rows=[r for r in repository.rows() if r['sample_code']==code]
 assert len(rows)==3 and all(r.get('test_only') for r in rows)
 assert all((repository.uploads/code/'originals'/(p+'.raw')).read_bytes()==files[p][1] for p in 'NGC')
 before-= {r['id'] for r in rows}
 original_hashes={p:hashlib.sha256((repository.uploads/code/'originals'/(p+'.raw')).read_bytes()).hexdigest() for p in 'NGC'}
 from invenio_rdm_records.proxies import current_rdm_records_service as service
 from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
 from argiloteca.scientific.drx_links import set_link,sync_metadata,DRXRecordLink
 identity=actor_identity(4)
 payload={'metadata':{'title':'TEST ONLY RAW deletion linked publication 20261101','resource_type':{'id':'dataset'},'publication_date':'2026-11-01','creators':[{'person_or_org':{'type':'personal','given_name':'Pessoa','family_name':'TesteRAW'}}]},'access':{'record':'public','files':'public'},'files':{'enabled':False}}
 draft=service.create(identity,payload);pid=draft.id
 Path('/tmp/raw-linked-fixture.json').write_text(json.dumps({'pid':pid,'code':code}))
 assert not draft.to_dict().get('pids')
 service.publish(identity,pid)
 with UnitOfWork() as uow:
  for row in rows[:2]:set_link(identity,row,pid,state='pending',evidence='Disposable RAW deletion association',expected_revision=0,actor=4)
  native=sync_metadata(identity,pid,{r['id']:r for r in repository.rows()})
  uow.register(RecordCommitOp(native,indexer=service.indexer,index_refresh=True));uow.commit()
 plan=clean.plan(actor_identity(4),4,'raw','selected-raws','delete_raw',selection=json.dumps([r['id'] for r in rows]),reason='TEST ONLY disposable anonymous RAW removal 20261101')
 assert not plan['blockers'],plan['blockers']
 source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':plan});db.session.add(source);db.session.flush()
 job=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(plan),'test_only':True},snapshot={'plan':plan});db.session.add(job);db.session.commit();jid=job.id
 run.delay(jid)
 for _ in range(40):
  time.sleep(1);db.session.expire_all();job=db.session.get(OpenAlexJob,jid)
  if job.state in {'completed','failed'}:break
 assert job.state=='completed',(job.state,job.result)
 assert job.result['raw_deletion']['phase']=='complete'
 assert len(plan['raw']['links'])==2
 assert all(link.state=='removed' for link in DRXRecordLink.query.filter_by(record_id=pid))
 assert service.read(identity,pid).to_dict()['metadata']['title']==payload['metadata']['title']
 try:set_link(identity,rows[0],pid,state='pending',evidence='Should reject deleted raw file',expected_revision=2,actor=4)
 except ValueError as error:assert str(error)=='raw_retired'
 else:raise AssertionError('Retired raw accepted a new association')
 db.session.rollback()
 assert all(not (repository.uploads/code/'files'/r['filename']).exists() for r in rows)
 assert all(r['id'] in retired(fresh=True) for r in rows)
 assert {r['id'] for r in repository.rows()}==before
 for p in 'NGC':assert hashlib.sha256((repository.uploads/code/'originals'/(p+'.raw')).read_bytes()).hexdigest()==original_hashes[p]
 raw_job_id=jid
 # Remove only this newly created temporary publication after verifying preservation.
 purge=clean.plan(identity,4,'record',pid,'purge_published',record_kind='published',reason='TEST ONLY clean up temporary RAW test publication')
 assert not purge['blockers'],purge['blockers']
 source=OpenAlexJob(kind='clean_preview',state='review',actor=4,params={'test_only':True},snapshot={'plan':purge});db.session.add(source);db.session.flush()
 cleanup=OpenAlexJob(kind='clean_apply',actor=4,params={'source_job':source.id,'plan_sha256':digest(purge),'test_only':True},snapshot={'plan':purge});db.session.add(cleanup);db.session.commit();cleanup_id=cleanup.id
 run.delay(cleanup_id)
 for _ in range(40):
  time.sleep(1);db.session.expire_all();cleanup=db.session.get(OpenAlexJob,cleanup_id)
  if cleanup.state in {'completed','failed'}:break
 assert cleanup.state=='completed',(cleanup.state,cleanup.result)
 print(json.dumps({'worker_job':raw_job_id,'cleanup_job':cleanup_id,'linked_record_preserved_before_fixture_cleanup':True,'links_removed':2,'retired_raw_cannot_be_relinked':True,'deleted_ids':[r['id'] for r in rows],'fixture_code':code,'anonymous_files_physically_deleted':3,'private_originals_preserved':3,'backup_verified':True,'existing_raw_files_deleted':0,'registry_filters_deleted_rows':True}),flush=True)

