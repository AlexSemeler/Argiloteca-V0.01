"""Local published-record purge for InvenioRDM 14's unimplemented service.

SQL removal is atomic. Storage/index cleanup has a durable, idempotent checkpoint.
Reserved identifiers, import claims, administrative backup and audit are retained.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

from invenio_db import db
from invenio_files_rest.models import Bucket,FileInstance,ObjectVersion,MultipartObject
from invenio_pidstore.models import PersistentIdentifier,PIDStatus
from invenio_rdm_records.records import models as models
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_records_resources.services.uow import RecordDeleteOp
from sqlalchemy import inspect,text
from sqlalchemy_continuum import version_class

from .adapters import digest
from .duplicates import backup_path,sha256_file

FILE_MODELS=(models.RDMFileRecordMetadata,models.RDMMediaFileRecordMetadata,
             models.RDMFileDraftMetadata,models.RDMMediaFileDraftMetadata)
VERSIONED=(models.RDMRecordMetadata,models.RDMFileRecordMetadata,models.RDMMediaFileRecordMetadata)


def serial(value):return json.loads(json.dumps(value,default=str,sort_keys=True))

def row_data(row):return serial({c.name:getattr(row,c.name) for c in row.__table__.columns})


def snapshot(row):
    """Include hidden file versions, media and revision history in approval/backup."""
    uid=uuid.UUID(row['uuid']);parent=uuid.UUID(row['parent_uuid']);blockers=[]
    siblings=[v for v in row['versions'] if v['uuid']!=row['uuid']]
    if siblings:blockers.append('Outras versões ou rascunhos dependem deste registro. A purga individual está bloqueada; preserve essas versões.')
    if row['pending_edit']:blockers.append('Existe edição em rascunho. Descarte ou conclua a edição antes da exclusão definitiva.')
    records=[db.session.get(models.RDMRecordMetadata,uid),db.session.get(models.RDMDraftMetadata,uid)]
    bids=sorted({str(getattr(r,key)) for r in records if r for key in ('bucket_id','media_bucket_id') if getattr(r,key)})
    for historical in version_class(models.RDMRecordMetadata).query.filter_by(id=uid):
        for key in ('bucket_id','media_bucket_id'):
            bid=getattr(historical,key)
            if bid and db.session.get(Bucket,bid) is not None:bids.append(str(bid))
    bids=sorted(set(bids));bucket_ids=[uuid.UUID(b) for b in bids]
    for cls in (models.RDMRecordMetadata,models.RDMDraftMetadata):
        if cls.query.filter(cls.id!=uid,db.or_(cls.bucket_id.in_(bucket_ids),cls.media_bucket_id.in_(bucket_ids))).first():
            blockers.append('Um bucket é usado por outro registro; seus arquivos não podem ser removidos.')
    if MultipartObject.query.filter(MultipartObject.bucket_id.in_(bucket_ids)).count():blockers.append('Há upload multipart no lote de arquivos. Conclua ou cancele o upload antes da purga.')
    objects=ObjectVersion.query.filter(ObjectVersion.bucket_id.in_(bucket_ids)).order_by(ObjectVersion.version_id).all()
    object_ids=[o.version_id for o in objects]
    for cls in FILE_MODELS:
        if cls.query.filter(cls.record_id!=uid,cls.object_version_id.in_(object_ids)).first():blockers.append('Há arquivo nativo vinculado a outro registro.')
    # Native non-RDM owners must also prevent deletion of a shared bucket/object.
    native_tables=set(inspect(db.engine).get_table_names())
    for name,column,values in [('communities_metadata','bucket_id',bids),('records_buckets','bucket_id',bids),('request_metadata','bucket_id',bids),('communities_files','object_version_id',[str(v) for v in object_ids]),('request_files','object_version_id',[str(v) for v in object_ids])]:
        if name in native_tables and values:
            statement=text('SELECT count(*) FROM "'+name+'" WHERE CAST("'+column+'" AS text) = ANY(:values)')
            if db.session.execute(statement,{'values':values}).scalar():blockers.append('Dependência nativa em '+name+'; resolva-a antes da purga.')
    # Unlike reversible withdrawal, even withdrawn incoming references block purge.
    identities={row['id'],row['parent_uuid'],row['data'].get('parent',{}).get('id','')}-{''}
    from .maintenance import references
    for cls in (models.RDMRecordMetadata,models.RDMDraftMetadata):
        for (data,) in db.session.query(cls.json).filter(cls.json.isnot(None),cls.parent_id!=parent).yield_per(25):
            if references(data,identities):blockers.append('Referência de outro registro, inclusive retirado: '+str(data.get('id','')))
    files=[]
    for fid in sorted({str(o.file_id) for o in objects if o.file_id}):
        f=db.session.get(FileInstance,uuid.UUID(fid))
        if type(f.storage()).__module__!='invenio_files_rest.storage.pyfs':blockers.append('Este armazenamento não é local; a purga física requer um adaptador validado.')
        shared=ObjectVersion.query.filter(ObjectVersion.file_id==f.id,~ObjectVersion.bucket_id.in_(bucket_ids)).count()
        files.append({**row_data(f),'shared_references':shared})
    history={version_class(cls).__table__.name:[row_data(r) for r in (version_class(cls).query.filter_by(id=uid) if cls is models.RDMRecordMetadata else version_class(cls).query.filter_by(record_id=uid)).order_by(version_class(cls).transaction_id)] for cls in VERSIONED}
    return {'schema':1,'blockers':list(dict.fromkeys(blockers)),'buckets':[row_data(db.session.get(Bucket,uuid.UUID(b))) for b in bids],
        'objects':[row_data(o) for o in objects],'file_instances':files,'history':history,
        'file_rows':{cls.__tablename__:[row_data(r) for r in cls.query.filter_by(record_id=uid).order_by(cls.id)] for cls in FILE_MODELS},
        'inactive_draft':row_data(records[1]) if records[1] else None,
        'version_state':row_data(db.session.get(models.RDMVersionsState,parent)),
        'identifiers':[row_data(p) for p in PersistentIdentifier.query.filter(PersistentIdentifier.object_uuid.in_([uid,parent])).order_by(PersistentIdentifier.id)]}


def write_backup(job,plan,identity):
    """Full native snapshot plus every binary in all target object versions."""
    path=backup_path(job.id);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.purge-backup-');manifest={'schema':1,'job':job.id,'actor':job.actor,'plan':plan,'files':[]}
    try:
        with os.fdopen(fd,'w+b') as stream,zipfile.ZipFile(stream,'w',allowZip64=True) as archive:
            for index,entry in enumerate(plan['purge']['file_instances']):
                f=db.session.get(FileInstance,uuid.UUID(entry['id']));algorithm,expected=entry['checksum'].split(':',1)
                checksum=hashlib.new(algorithm);sha=hashlib.sha256();size=0;name='files/'+str(index)+'.bin'
                with f.storage().open('rb') as source,archive.open(name,'w',force_zip64=True) as target:
                    while data:=source.read(1024*1024):target.write(data);sha.update(data);checksum.update(data);size+=len(data)
                if checksum.hexdigest()!=expected or size!=entry['size']:raise ValueError('Checksum/tamanho divergente no backup. Publicação preservada.')
                manifest['files'].append({'file_id':entry['id'],'archive':name,'sha256':sha.hexdigest(),'bytes':size})
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        with open(tmp,'rb') as stream:os.fsync(stream.fileno())
        with zipfile.ZipFile(tmp) as archive:
            if archive.testzip():raise ValueError('Backup ZIP inválido. Publicação preservada.')
            for entry in manifest['files']:
                with archive.open(entry['archive']) as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:raise ValueError('Falha na conferência do backup.')
        os.chmod(tmp,0o600);os.replace(tmp,path)
        return {'filename':path.name,'sha256':sha256_file(path),'bytes':path.stat().st_size,'binary_files':len(manifest['files'])}
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def remove_metadata(identity,plan,uow):
    """Remove only the approved single version and its private native containers."""
    uid=uuid.UUID(plan['record']['uuid']);parent_id=uuid.UUID(plan['record']['parent_uuid'])
    record=service.record_cls.get_record(uid);service.require_permission(identity,'purge',record=record)
    parent=record.parent;purge=plan['purge']
    indexes=[{'index':service.indexer._prepare_index(service.indexer.record_to_index(record)),'id':str(uid)}]
    draft_model=db.session.get(models.RDMDraftMetadata,uid)
    # The draft index name is captured before its SQL row disappears.
    if draft_model:
        draft=service.draft_cls({},model=draft_model)
        indexes.append({'index':service.draft_indexer._prepare_index(service.draft_indexer.record_to_index(draft)),'id':str(uid)})
    bids=[uuid.UUID(b['id']) for b in purge['buckets']]
    Bucket.query.filter(Bucket.id.in_(bids)).order_by(Bucket.id).with_for_update().all()
    FileInstance.query.filter(FileInstance.id.in_([uuid.UUID(f['id']) for f in purge['file_instances']])).order_by(FileInstance.id).with_for_update().all()
    state=db.session.get(models.RDMVersionsState,parent_id);state.latest_id=None;state.next_draft_id=None;db.session.flush()
    for cls in FILE_MODELS:cls.query.filter_by(record_id=uid).delete(synchronize_session=False)
    if draft_model:db.session.delete(draft_model)
    uow.register(RecordDeleteOp(record,force=True))
    db.session.flush()
    # Continuum writes deleted revisions at flush; remove those as well.
    for cls in VERSIONED:
        table=version_class(cls).__table__;column=table.c.id if cls is models.RDMRecordMetadata else table.c.record_id
        db.session.execute(table.delete().where(column==uid))
    parent.delete(force=True);db.session.flush()
    for bid in bids:
        bucket=db.session.get(Bucket,bid);bucket.locked=False;bucket.remove()
    for pid in PersistentIdentifier.query.filter(PersistentIdentifier.object_uuid.in_([uid,parent_id])):
        # Keep even NEW identifiers reserved: never reassign a purged PID.
        pid.status=PIDStatus.DELETED
    db.session.flush()
    return {'phase':'cleanup','record_uuid':str(uid),'indexes':indexes,
        'files':[{key:f[key] for key in ('id','uri','storage_class','checksum','size')} for f in purge['file_instances']],
        'shared_files':[],'removed_files':[]}


def finish(job):
    """Resume only cleanup after committed SQL deletion, never repeat the purge."""
    checkpoint=deepcopy(job.result['purge']);path=backup_path(job.id)
    if not path.is_file() or path.is_symlink() or sha256_file(path)!=job.result['backup']['sha256']:
        raise ValueError('Backup ausente ou alterado. Limpeza física interrompida; consulte a auditoria.')
    for item in checkpoint['indexes']:
        service.indexer.client.delete(index=item['index'],id=item['id'],ignore=[404],refresh=True)
    for entry in checkpoint['files']:
        if entry.get('storage_removed') or entry['id'] in checkpoint['shared_files']:continue
        f=FileInstance.query.filter_by(id=uuid.UUID(entry['id'])).with_for_update().one_or_none()
        if f is not None:
            if ObjectVersion.query.filter_by(file_id=f.id).count() or MultipartObject.query.filter_by(file_id=f.id).count():
                checkpoint['shared_files'].append(entry['id'])
                job.result={**job.result,'purge':deepcopy(checkpoint)};db.session.commit();continue
            if any(getattr(f,key)!=entry[key] for key in ('checksum','size','uri','storage_class')):
                raise ValueError('O arquivo mudou após a purga SQL. Limpeza recusada.')
            # Check all database constraints before touching storage. The URI is
            # retained in the same committed checkpoint for crash recovery.
            db.session.delete(f);entry['database_removed']=True
            job.result={**job.result,'purge':deepcopy(checkpoint)};db.session.commit()
        elif not entry.get('database_removed'):
            raise ValueError('Arquivo removido fora desta tarefa. Confira o backup antes de continuar.')
        shadow=FileInstance(id=uuid.UUID(entry['id']),uri=entry['uri'],storage_class=entry['storage_class'],size=entry['size'],checksum=entry['checksum'])
        try:shadow.storage().delete()
        except FileNotFoundError:pass
        entry['storage_removed']=True
        if entry['id'] not in checkpoint['removed_files']:checkpoint['removed_files'].append(entry['id'])
        job.result={**job.result,'purge':deepcopy(checkpoint)};db.session.commit()
    checkpoint['phase']='complete';job.result={**job.result,'purge':checkpoint};job.state='completed';db.session.commit()
