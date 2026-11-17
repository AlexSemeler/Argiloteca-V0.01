"""Confined, backed-up maintenance of V59 lots; usable in the Mac agent."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

LOT=re.compile(r'v59_[A-Za-z0-9_]+')
JOB=re.compile(r'[a-f0-9]{32}')


def source_path(root,lot,archived=False):
    if not LOT.fullmatch(str(lot)):raise ValueError('Identificador de lote inválido.')
    base=Path(root).resolve();parent=base/('.admin-trash' if archived else 'lotes')
    path=parent/lot
    if parent.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(base):
        raise ValueError('Caminho de lote não permitido.')
    return path


def manifest(root,lot,archived=False):
    path=source_path(root,lot,archived)
    if not path.is_dir():raise ValueError('Lote indisponível. Atualize a página.')
    files=[];total=0
    for entry in sorted(path.rglob('*')):
        if entry.is_symlink():raise ValueError('Lote contém link simbólico; manutenção recusada.')
        if entry.is_dir():continue
        if not entry.is_file():raise ValueError('Entrada irregular no lote.')
        if len(files)>=20000:raise ValueError('Lote excede 20 mil arquivos; divida a manutenção.')
        with entry.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        size=entry.stat().st_size;total+=size
        files.append({'path':entry.relative_to(path).as_posix(),'bytes':size,'sha256':sha})
    return {'lot':lot,'archived':archived,'files':files,'bytes':total}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def backup(root,queue,jid,plan):
    if not JOB.fullmatch(jid):raise ValueError('Identificador de tarefa inválido.')
    folder=Path(queue)/'maintenance-backups';folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    target=folder/(jid+'.zip');fd,temp=tempfile.mkstemp(dir=folder,prefix='.backup-')
    source=source_path(root,plan['target'],plan['archived'])
    try:
        with os.fdopen(fd,'w+b') as handle,zipfile.ZipFile(handle,'w',allowZip64=True) as archive:
            for entry in plan['lot_manifest']['files']:
                archive.write(source/entry['path'],'lot/'+entry['path'])
            archive.writestr('manifest.json',json.dumps(plan,ensure_ascii=False,indent=2))
        with open(temp,'rb') as stream:os.fsync(stream.fileno())
        os.chmod(temp,0o600);os.replace(temp,target)
        with zipfile.ZipFile(target) as archive:
            if archive.testzip():raise ValueError('Backup inválido; lote preservado.')
            for entry in plan['lot_manifest']['files']:
                with archive.open('lot/'+entry['path']) as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:
                        raise ValueError('O conteúdo mudou durante o backup; lote preservado.')
        with target.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        return {'filename':target.name,'sha256':sha,'bytes':target.stat().st_size,'lot_backup':True}
    finally:
        if os.path.exists(temp):os.unlink(temp)


def apply_on_mac(root,queue,jid,params):
    """Only three literal operations, after a verified server-side ZIP exists."""
    if not JOB.fullmatch(jid):raise ValueError('Tarefa inválida.')
    plan=params['plan'];mode=plan['action']
    if mode not in {'archive_lot','restore_lot','delete_lot'} or plan['kind']!='lot':raise ValueError('Operação de lote inválida.')
    current=manifest(root,plan['target'],plan['archived'])
    if fingerprint(current)!=plan['lot_sha256']:raise ValueError('O lote mudou após a prévia. Nenhum arquivo foi removido.')
    info=params['backup'];path=Path(queue)/'maintenance-backups'/(jid+'.zip')
    if info['filename']!=path.name or path.is_symlink():raise ValueError('Backup inválido.')
    with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha!=info['sha256']:raise ValueError('Hash do backup divergente.')
    with zipfile.ZipFile(path) as archive:
        if archive.testzip():raise ValueError('Backup corrompido.')
        saved=json.loads(archive.read('manifest.json'))
        if saved!=plan:raise ValueError('O backup pertence a outra prévia.')
    source=source_path(root,plan['target'],plan['archived'])
    if mode=='delete_lot':shutil.rmtree(source)
    else:
        target=source_path(root,plan['target'],mode=='archive_lot')
        target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if target.exists() or target.is_symlink():raise ValueError('Já existe um lote no destino. Nada foi substituído.')
        os.rename(source,target)
    return {'state':'completed','message':'Manutenção do lote concluída no Mac.','lot':plan['target'],'backup':info}
