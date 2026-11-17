"""Reviewed removal of anonymous RAW binaries; immutable source archives remain.

The committed clean_apply journal is the retirement registry. A cleanup checkpoint
hides retired curves before filesystem unlink, and permits an idempotent retry.
"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

from flask import current_app, has_app_context, has_request_context, g
from invenio_db import db
from sqlalchemy import text

MAX_BYTES = 512 * 1024 * 1024


def retired(*, fresh=False):
    if not has_app_context() or 'invenio-rdm-records' not in current_app.extensions:
        return set()
    if has_request_context() and not fresh and hasattr(g, '_retired_raws'):
        return g._retired_raws
    from ..openalex.models import OpenAlexJob
    values=set()
    for (result,) in db.session.query(OpenAlexJob.result).filter(OpenAlexJob.kind=='clean_apply', OpenAlexJob.result['raw_deletion'].isnot(None)):
        journal=(result or {}).get('raw_deletion') or {}
        if journal.get('phase') in {'cleanup','complete'}:
            for row in journal['rows']:
                values.update((row['id'], row['filename']))
    if has_request_context():g._retired_raws=values
    return values


def checked_path(path, roots):
    path=Path(path)
    # Resolve neither a symlink file nor any symlink parent within an allowed root.
    for root in map(Path, roots):
        try:parts=path.relative_to(root).parts
        except ValueError:continue
        if not parts or root.is_symlink():continue
        current=root
        for part in parts:
            current=current/part
            if current.is_symlink():raise ValueError('Caminho RAW contém link simbólico. / RAW path contains a symlink.')
        if path.resolve().is_relative_to(root.resolve()):return path
    raise ValueError('Arquivo fora das pastas RAW autorizadas. / File outside allowed RAW folders.')


def roots(repository):
    from ..services import drx
    return [repository.library/'files',repository.uploads,Path(drx.DRX_RAW_SNAPSHOT_PATH).parent/'raw']


def file_info(path, allowed):
    path=checked_path(path,allowed)
    try:stat=path.stat()
    except OSError:raise ValueError('RAW indisponível. Atualize a biblioteca ou revise a origem. / RAW unavailable; refresh the library or review its source.') from None
    if not path.is_file() or stat.st_size>MAX_BYTES:raise ValueError('Arquivo RAW inválido ou muito grande.')
    if not os.access(path.parent,os.W_OK):raise ValueError('Pasta RAW somente leitura. Ative a montagem local de manutenção. / RAW folder is read-only; enable the local maintenance mount.')
    return {'path':str(path),'bytes':stat.st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def snapshot(identity, raw_ids):
    from .admin_raw_views import store,curation_links
    from .admin_raw_store import FILE,CODE
    from .drx_links import DRXRecordLink,link_dict
    from ..openalex.maintenance import record_state
    from ..services import drx
    if not isinstance(raw_ids,list) or not 1<=len(raw_ids)<=100 or any(not isinstance(r,str) for r in raw_ids) or len(set(raw_ids))!=len(raw_ids):raise ValueError('Seleção RAW inválida. / Invalid RAW selection.')
    repository=store(); allowed=roots(repository); rows=[];files={};links=[];records={};blockers=[]
    for raw_id in sorted(raw_ids):
        try:row=repository.get(raw_id)
        except KeyError:raise ValueError('RAW ausente ou já excluído. Atualize a lista. / RAW absent or already deleted; refresh the list.') from None
        if not FILE.fullmatch(row['filename']) or not CODE.fullmatch(row['sample_code']):raise ValueError('Nome RAW inválido.')
        row=deepcopy(row);rows.append(row)
        if curation_links().read(row['sample_code']):blockers.append('A amostra '+row['sample_code']+' tem um envio nativo de curadoria. Resolva esse envio antes de excluir o RAW. / Sample has a native curation submission; resolve it before deleting the RAW.')
        folder=repository.uploads/row['sample_code']/'files' if row['classification_kind']=='new_provisional' else repository.library/'files'
        candidates=[folder/row['filename']]
        for public in drx._iter_raw_snapshot_rows():
            if public.get('filename')==row['filename']:
                candidates.append(drx._resolve_snapshot_raw_path(public.get('path') or public.get('raw_path')))
        for path in candidates:
            info=file_info(path,allowed)
            if info['sha256']!=row['sha256']:raise ValueError('Checksum RAW divergente. / RAW checksum mismatch.')
            files[info['path']]=info
        for link in DRXRecordLink.query.filter_by(raw_id=raw_id).filter(DRXRecordLink.state!='removed').order_by(DRXRecordLink.record_id):
            if link.sha256!=row['sha256']:raise ValueError('Checksum do vínculo DRX divergente.')
            links.append(dict(link_dict(link),id=link.id))
            if link.record_id not in records:
                state=record_state(identity,link.record_id,'published')
                from invenio_rdm_records.proxies import current_rdm_records_service as service
                record=service.read(identity,link.record_id)._record
                service.require_permission(identity,'edit',record=record)
                if state['pending_edit']:blockers.append('O registro '+link.record_id+' tem edição em rascunho. / Record has a pending draft edit.')
                records[link.record_id]=state
    if len(links)>100:raise ValueError('Mais de 100 vínculos DRX. Divida a seleção.')
    files=sorted(files.values(),key=lambda f:f['path'])
    if sum(f['bytes'] for f in files)>MAX_BYTES:raise ValueError('Seleção maior que 512 MiB. Divida a operação.')
    return {'rows':rows,'binaries':files,'links':links,'records':[records[k] for k in sorted(records)],'blockers':sorted(set(blockers))}


def write_backup(job, approved):
    from ..openalex.duplicates import backup_path,sha256_file
    path=backup_path(job.id);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.raw-backup-',dir=path.parent)
    try:
        with os.fdopen(fd,'w+b') as stream:
            with zipfile.ZipFile(stream,'w',allowZip64=True) as archive:
                for index,info in enumerate(approved['raw']['binaries']):
                    content=Path(info['path']).read_bytes()
                    if len(content)!=info['bytes'] or hashlib.sha256(content).hexdigest()!=info['sha256']:raise ValueError('RAW alterado antes do backup.')
                    archive.writestr('raw/'+str(index)+'.bin',content)
                archive.writestr('manifest.json',json.dumps({'schema':1,'job':job.id,'plan':approved},ensure_ascii=False))
            stream.flush();os.fsync(stream.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,path)
        info={'filename':path.name,'sha256':sha256_file(path),'bytes':path.stat().st_size,'binary_files':len(approved['raw']['binaries'])}
        verify_backup(job,approved,info)
        return info
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def verify_backup(job,approved,info):
    from ..openalex.duplicates import backup_path,sha256_file
    from ..openalex.adapters import digest
    path=backup_path(job.id)
    if path.is_symlink() or sha256_file(path)!=info['sha256']:raise ValueError('Backup RAW inválido. / Invalid RAW backup.')
    with zipfile.ZipFile(path) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        if manifest['job']!=job.id or digest(manifest['plan'])!=digest(approved):raise ValueError('Plano do backup RAW divergente.')
        for index,row in enumerate(approved['raw']['binaries']):
            content=archive.read('raw/'+str(index)+'.bin')
            if len(content)!=row['bytes'] or hashlib.sha256(content).hexdigest()!=row['sha256']:raise ValueError('Binário do backup RAW divergente.')


def finish(job):
    from .admin_raw_views import store
    from ..openalex.maintenance import now
    if job.result.get('raw_deletion',{}).get('phase')!='cleanup':raise ValueError('Checkpoint RAW ausente.')
    db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
    approved=job.snapshot['plan'];verify_backup(job,approved,job.result['backup'])
    allowed=roots(store())
    # Validate every remaining file before unlinking any file. Missing files are
    # permitted only after the committed retirement checkpoint (crash recovery).
    paths=[]
    for info in approved['raw']['binaries']:
        path=checked_path(info['path'],allowed)
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest()!=info['sha256']:raise ValueError('RAW alterado durante limpeza; arquivo preservado.')
            paths.append(path)
    for path in paths:path.unlink()
    job.result={**job.result,'raw_deletion':{**job.result['raw_deletion'],'phase':'complete'},'completed_at':now()}
    job.state='completed';db.session.add(job);db.session.commit()


def run(job,identity,approved,source):
    from .admin_raw_views import store,curation_links
    from .drx_links import set_link,sync_metadata
    from ..openalex.maintenance import current_plan,now
    from invenio_records_resources.services.uow import UnitOfWork,RecordCommitOp
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    with ExitStack() as locks:
        for code in sorted({r['sample_code'] for r in approved['raw']['rows']}):locks.enter_context(curation_links().lock(code))
        if job.result.get('raw_deletion',{}).get('phase')=='cleanup':return finish(job)
        with UnitOfWork(db.session) as uow:
            db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
            # Link writers use the same lock; current_plan rechecks every link,
            # record revision and byte digest after acquiring it.
            from invenio_rdm_records.records.models import RDMRecordMetadata,RDMParentMetadata
            for record in approved['raw']['records']:
                RDMRecordMetadata.query.filter_by(id=record['uuid']).with_for_update().one()
                RDMParentMetadata.query.filter_by(id=record['parent_uuid']).with_for_update().one()
            db.session.expire_all();approved=current_plan(identity,approved)
            backup=write_backup(job,approved)
            for link in approved['raw']['links']:
                set_link(identity,{'id':link['raw_id'],'sha256':link['sha256']},link['record_id'],state='removed',evidence=approved['reason'],expected_revision=link['revision'],actor=job.actor)
            available={r['id']:r for r in store().rows()}
            for record in approved['raw']['records']:
                native=sync_metadata(identity,record['id'],available)
                uow.register(RecordCommitOp(native,indexer=service.indexer,index_refresh=True))
            job.result={'backup':backup,'action':'delete_raw','target':approved['target'],'raw_deletion':{'phase':'cleanup','rows':[{'id':r['id'],'filename':r['filename'],'sha256':r['sha256']} for r in approved['raw']['rows']]},'retired_at':now()}
            job.state='queued';source.state='completed';source.result={'apply_job':job.id}
            db.session.add_all([job,source]);uow.commit()
        finish(job)
