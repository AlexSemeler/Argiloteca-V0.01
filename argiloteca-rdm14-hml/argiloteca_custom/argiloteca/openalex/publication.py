"""Reviewed native publication, with bounded tasks and transactional checkpoints."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import gc
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid
import zipfile

from flask import current_app
from invenio_db import db
from sqlalchemy import text
from sqlalchemy.orm import defer

from .adapters import converter, digest, verify_snapshot
from .duplicates import fingerprint, sha256_file
from .models import OpenAlexJob
from .preview import iter_records
from .service import actor_identity, inventory, matches, tokens

BATCH_SIZES = (100, 200, 500)
KINDS = {'publish_scan', 'publish'}


def publication_summary(records, items=None):
    items = items or {}
    counts = Counter(r['status'] for r in records)
    outcomes = Counter(v['state'] for v in items.values())
    return {'total': len(records), 'ready': counts['ready'],
            'already_published': counts['already_published'] + outcomes['already_published'],
            'blocked': counts['blocked'] + outcomes['blocked'],
            'published': outcomes['published'],
            'new': sum(v.get('state') == 'published' and not v.get('was_published') for v in items.values()),
            'updated': sum(v.get('state') == 'published' and bool(v.get('was_published')) for v in items.values()),
            'processed': len(items), 'unclassified': sum(not r.get('communities') for r in records if r['status'] == 'ready')}


def imported_targets(source):
    """Only records actually imported by this source; never arbitrary record IDs."""
    import_kind = 'oai_import' if source.kind.startswith('oai_') else 'men_import' if source.kind.startswith('men_') else 'pan_import' if source.kind.startswith('pan_') else 'import'
    jobs = [source] if source.kind == import_kind else OpenAlexJob.query.filter_by(kind=import_kind, state='completed').filter(
        OpenAlexJob.params['source_job'].as_string() == source.id).options(defer(OpenAlexJob.snapshot)).yield_per(1)
    targets = {}
    for job in jobs:
        for key, outcome in job.result.get('items', {}).items():
            if outcome.get('state') not in {'created', 'updated'}:
                continue
            rid = str(outcome['draft_id'])
            if key in targets and targets[key] != rid:
                raise ValueError('A mesma obra possui resultados de importação divergentes. Verifique os duplicados.')
            targets[key] = rid
    if not targets:
        raise ValueError('Esta revisão ainda não possui rascunhos importados.')
    return targets


def read_state(identity, rid):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
    from sqlalchemy.orm.exc import NoResultFound
    try:
        draft = service.draft_cls.pid.resolve(rid, registered_only=False)
    except (PIDDoesNotExistError, PIDDeletedError, NoResultFound):
        draft = None
    if draft is not None:
        model = db.session.get(RDMDraftMetadata, draft.id)
        if not model or not model.json:
            draft = None
    if draft is None:
        published = service.read(identity, rid)
        if published._record.model.deletion_status.value != 'P':
            raise ValueError('O registro está retirado ou excluído.')
        return None, published.to_dict(), None
    service.require_permission(identity, 'read_draft', record=draft)
    model = db.session.get(RDMRecordMetadata, draft.id)
    if model and model.deletion_status.value != 'P':
        raise ValueError('O registro está retirado ou excluído.')
    data = service.result_item(service, identity, draft, links_tpl=service.links_item_tpl).to_dict()
    published = service.record_cls.get_record(draft.id) if model else None
    stamp = digest({'record': fingerprint(data), 'parent_revision': draft.parent.revision_id,
                    'published': deepcopy(dict(published)) if published else None,
                    'published_revision': published.revision_id if published else None})
    return draft, data, stamp


def validate(identity, draft, data):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    if data.get('parent', {}).get('review') or data.get('review'):
        raise ValueError('Há solicitação de revisão. Conclua-a individualmente antes da publicação em lote.')
    if current_app.config.get('RDM_COMMUNITY_REQUIRED_TO_PUBLISH') and not draft.parent.communities.ids:
        raise ValueError('A configuração exige uma comunidade antes da publicação.')
    service.require_permission(identity, 'publish', record=draft)
    service._validate_draft(identity, draft)


def error_message(exc):
    from marshmallow import ValidationError
    if isinstance(exc, ValidationError):
        return json.dumps(exc.messages, ensure_ascii=False, default=str)[:2000]
    if isinstance(exc, ValueError):
        return str(exc)[:2000]
    return 'A validação nativa recusou a operação. Confira o registro e prepare outra prévia.'


def prepare(job):
    source = db.session.get(OpenAlexJob, job.params['source_job'])
    kinds = {'oai_prepare', 'oai_import'} if job.kind == 'oai_publish_scan' else {'men_prepare', 'men_import'} if job.kind == 'men_publish_scan' else {'pan_prepare', 'pan_import'} if job.kind == 'pan_publish_scan' else {'prepare', 'import'}
    if not source or source.kind not in kinds or source.state not in {'review', 'completed'}:
        raise ValueError('Selecione uma importação concluída ou sua revisão de origem.')
    if job.params.get('batch_size') not in BATCH_SIZES:
        raise ValueError('Tamanho de lote inválido.')
    targets = imported_targets(source)
    snapshot = source.snapshot
    root = current_app.config['ARGILOTECA_OPENALEX_ROOT']
    if job.kind == 'oai_publish_scan':
        from ..repositories.workflow import verify_snapshot as verify_repositories, root as repositories_root
        verify_repositories(repositories_root(), {**snapshot, 'records': []})
    elif job.kind == 'men_publish_scan':
        from ..mendeley.workflow import verify_snapshot as verify_mendeley, root as mendeley_root
        verify_mendeley(mendeley_root(), {**snapshot, 'records': []})
    elif job.kind == 'pan_publish_scan':
        from ..pangaea.workflow import verify_snapshot as verify_pangaea, root as pangaea_root
        verify_pangaea(pangaea_root(), {**snapshot, 'records': []})
    else:
        verify_snapshot(root, {**snapshot, 'records': []})
    identity = actor_identity(job.actor)
    metadata = converter(root)[0]
    index = inventory(metadata)
    records, seen = [], set()
    from marshmallow import ValidationError
    from invenio_records_resources.services.errors import PermissionDeniedError
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
    for row in iter_records(snapshot):
        rid = targets.get(row['key'])
        if not rid or row['status'] == 'bloqueado':
            continue
        if rid in seen:
            raise ValueError('Dois itens importados apontam para o mesmo registro. Resolva o conflito antes de publicar.')
        seen.add(rid)
        item = {'key': row['key'], 'id': rid, 'title': row['payload']['metadata']['title'],
                'identity': deepcopy(row['identity']), 'status': 'blocked', 'issues': [], 'communities': []}
        try:
            found = matches(row, index, metadata)
            if len(found) != 1 or str(found[0]['id']) != rid:
                raise ValueError('Correspondência DOI/OpenAlex divergente ou duplicada. Resolva antes de publicar.')
            draft, data, stamp = read_state(identity, rid)
            if not tokens(row['payload'], metadata).issubset(tokens(data, metadata)):
                raise ValueError('A identidade atual difere da importação revisada.')
            item['title'] = data['metadata']['title']
            item['communities'] = [{'id': str(c['id']), 'title': c['metadata']['title'], 'slug': c['slug']}
                                  for c in data.get('parent', {}).get('communities', {}).get('entries', [])]
            item['access'] = data.get('access', {}).get('record')
            if draft is None:
                item['status'] = 'already_published'
            else:
                validate(identity, draft, data)
                item.update(status='ready', fingerprint=stamp, uuid=str(draft.id),
                            parent_uuid=str(draft.parent.id), was_published=bool(data.get('is_published')),
                            revision=draft.revision_id, tokens=sorted(tokens(data, metadata)),
                            files=sum(data.get(k, {}).get('count', 0) for k in ('files', 'media_files')))
        except (ValueError, ValidationError, PermissionDeniedError, PIDDoesNotExistError, PIDDeletedError) as exc:
            item['issues'].append(error_message(exc))
        records.append(item)
        if len(records) % 100 == 0:
            job.result = {'progress': {'processed': len(records), 'total': len(targets)}}
            job.updated = datetime.now(timezone.utc)
            db.session.commit()
            gc.collect()
    if len(seen) != len(targets):
        raise ValueError('Há resultados de importação fora da prévia. Prepare outra revisão antes de publicar.')
    job.snapshot = {'schema': 1, 'source_job': source.id, 'prepared_at': datetime.now(timezone.utc).isoformat(),
                    'records': records, 'batch_size': job.params['batch_size'],
                    'summary': publication_summary(records)}
    job.state = 'review'
    job.result = {'message': 'Prévia pronta; confira os registros antes de publicar.'}


def backup_path(job_id, number):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id) or not 0 <= number <= 10000:
        raise ValueError('Identificador de backup inválido.')
    folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'publication-backups' / job_id
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder / (str(number) + '.zip')


def backup_chunk(job, number, rows, identity):
    """Private, verified metadata and original binaries, before native publication."""
    path = backup_path(job.id, number)
    known = job.result.get('backups', {}).get(str(number))
    if known:
        if not path.is_file() or path.is_symlink() or sha256_file(path) != known['sha256']:
            raise ValueError('Backup ausente ou alterado. A publicação foi interrompida.')
        return known
    manifest = {'schema': 1, 'job': job.id, 'plan_sha256': job.params['plan_sha256'],
                'chunk': number, 'keys': [r['key'] for r in rows], 'records': [], 'files': []}
    if path.exists():
        # Recover a fully written orphan after rename but before journal commit.
        if path.is_symlink():
            raise ValueError('Caminho de backup inválido.')
        with zipfile.ZipFile(path) as archive:
            saved = json.loads(archive.read('manifest.json'))
            if archive.testzip() or any(saved.get(k) != manifest[k] for k in ('schema', 'job', 'plan_sha256', 'chunk', 'keys')):
                raise ValueError('Backup preservado não corresponde a esta publicação.')
        return {'filename': path.name, 'sha256': sha256_file(path), 'bytes': path.stat().st_size, 'chunk': number,
                'fingerprints': {r['key']: r['fingerprint'] for r in saved['records']}}
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w+b') as destination, zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            for row in rows:
                draft, data, stamp = read_state(identity, row['id'])
                if draft is None or stamp != row['fingerprint']:
                    continue  # Changed/missing records will be blocked, never published.
                record = {'key': row['key'], 'id': row['id'], 'fingerprint': stamp,
                          'draft': data, 'draft_raw': deepcopy(dict(draft)), 'parent_raw': deepcopy(dict(draft.parent))}
                candidates = [('draft', draft, data)]
                if row['was_published']:
                    from invenio_rdm_records.proxies import current_rdm_records_service as service
                    published = service.read(identity, row['id'])
                    record['published'] = published.to_dict()
                    record['published_raw'] = deepcopy(dict(published._record))
                    candidates.append(('published', published._record, record['published']))
                manifest['records'].append(record)
                for kind, native, payload in candidates:
                    for category in ('files', 'media_files'):
                        for key, entry in payload.get(category, {}).get('entries', {}).items():
                            file = getattr(native, category)[key]
                            algorithm, expected = entry['checksum'].split(':', 1)
                            checksum, size = hashlib.new(algorithm), 0
                            name = 'files/' + str(len(manifest['files'])) + '.bin'
                            with file.open_stream('rb') as source, archive.open(name, 'w', force_zip64=True) as target:
                                while chunk := source.read(1048576):
                                    checksum.update(chunk); size += len(chunk); target.write(chunk)
                            if size != entry['size'] or checksum.hexdigest() != expected:
                                raise ValueError('Um arquivo não corresponde ao checksum. Publicação interrompida.')
                            manifest['files'].append({'id': row['id'], 'kind': kind, 'category': category,
                                                      'key': key, 'checksum': entry['checksum'], 'size': size, 'archive': name})
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, default=str))
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip():
                raise ValueError('Falha de integridade no backup.')
        os.replace(temporary, path)
        return {'filename': path.name, 'sha256': sha256_file(path), 'bytes': path.stat().st_size, 'chunk': number,
                'fingerprints': {r['key']: r['fingerprint'] for r in manifest['records']}}
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def preserved(before, after):
    for field in ('metadata', 'custom_fields'):
        if before.get(field) != after.get(field):
            raise ValueError('A publicação alterou metadados inesperadamente; transação desfeita.')
    for field in ('record', 'files', 'embargo'):
        if before.get('access', {}).get(field) != after.get('access', {}).get(field):
            raise ValueError('A publicação alterou o acesso; transação desfeita.')
    for field in ('access', 'communities'):
        if before.get('parent', {}).get(field) != after.get('parent', {}).get(field):
            raise ValueError('A publicação alterou vínculos ou propriedade; transação desfeita.')
    for category in ('files', 'media_files'):
        def contents(data):
            return {key: {k: value.get(k) for k in ('checksum', 'size', 'metadata')}
                    for key, value in data.get(category, {}).get('entries', {}).items()}
        if contents(before) != contents(after):
            raise ValueError('A publicação alterou arquivos; transação desfeita.')


def repair_checkpoint_index(job, identity, service):
    """Recover native index hooks that may fail after the SQL checkpoint commits."""
    cursor = job.result.get('cursor', 0)
    if not cursor:
        return
    row = job.snapshot['records'][cursor - 1]
    if job.result.get('items', {}).get(row['key'], {}).get('state') != 'published':
        return
    published = service.read(identity, row['id'])
    service.indexer.index(published._record)
    draft = service.draft_cls.get_record(uuid.UUID(row['uuid']), with_deleted=True)
    if draft.model.is_deleted:
        service.indexer.delete(draft, ignore=[404])


def run_chunk(job):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_rdm_records.records.models import RDMParentMetadata, RDMDraftMetadata, RDMRecordMetadata
    from invenio_records_resources.services.uow import UnitOfWork
    from invenio_records_resources.services.errors import PermissionDeniedError
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
    from marshmallow import ValidationError
    from sqlalchemy.orm.exc import NoResultFound
    if digest(job.snapshot) != job.params['plan_sha256']:
        raise ValueError('A prévia de publicação foi alterada. Prepare outra prévia.')
    identity = actor_identity(job.actor)
    records = job.snapshot['records']
    if any(r['status'] != 'ready' for r in records):
        raise ValueError('A seleção contém registros não liberados.')
    size = job.params['batch_size']
    if size not in BATCH_SIZES:
        raise ValueError('Tamanho de lote inválido.')
    cursor = job.result.get('cursor', 0)
    repair_checkpoint_index(job, identity, service)
    if cursor >= len(records):
        job.state = 'completed'
        db.session.commit()
        return False
    number = cursor // size
    rows = records[number * size:(number + 1) * size]
    backup = backup_chunk(job, number, rows, identity)
    job.result = {**job.result, 'backups': {**job.result.get('backups', {}), str(number): backup}}
    db.session.commit()  # Pin backup checksum durably before the first write.
    metadata = converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])[0]
    index = inventory(metadata)
    for offset in range(cursor, min((number + 1) * size, len(records))):
        row = records[offset]
        try:
            with UnitOfWork() as uow:
                db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
                db.session.query(RDMParentMetadata).filter_by(id=uuid.UUID(row['parent_uuid'])).with_for_update().one()
                db.session.query(RDMDraftMetadata).filter_by(id=uuid.UUID(row['uuid'])).with_for_update().one()
                db.session.query(RDMRecordMetadata).filter_by(id=uuid.UUID(row['uuid'])).with_for_update().all()
                db.session.expire_all()
                draft, before, stamp = read_state(identity, row['id'])
                if draft is None:
                    # Another confirmed publication may have completed this PID.
                    if set(row['tokens']).issubset(tokens(before, metadata)):
                        outcome = {'state': 'already_published', 'record_id': row['id']}
                    else:
                        raise ValueError('Identidade do registro publicado divergente.')
                else:
                    if backup.get('fingerprints', {}).get(row['key']) != row['fingerprint']:
                        raise ValueError('O registro mudou antes do backup. Prepare outra prévia de publicação.')
                    if stamp != row['fingerprint']:
                        raise ValueError('O rascunho, os arquivos ou os vínculos mudaram desde a prévia. Prepare outra prévia.')
                    found = {str(v['id']) for token in row['tokens'] for v in index.get(token, {}).values()}
                    if found != {row['id']}:
                        raise ValueError('Conflito DOI/OpenAlex detectado. Nenhuma publicação feita para este item.')
                    validate(identity, draft, before)
                    result = service.publish(identity, row['id'], uow=uow)
                    after = result.to_dict()
                    if str(after['id']) != row['id'] or not set(row['tokens']).issubset(tokens(after, metadata)):
                        raise ValueError('A publicação não preservou o identificador revisado.')
                    preserved(before, after)
                    outcome = {'state': 'published', 'record_id': row['id'],
                               'was_published': row['was_published'], 'published_at': datetime.now(timezone.utc).isoformat()}
                job.result = {**job.result, 'items': {**job.result.get('items', {}), row['key']: outcome}, 'cursor': offset + 1}
                job.result = {**job.result, 'summary': publication_summary(records, job.result['items'])}
                job.updated = datetime.now(timezone.utc)
                db.session.add(job)
                uow.commit()  # Publication and its checkpoint are one SQL transaction.
        except (ValueError, ValidationError, PermissionDeniedError, PIDDoesNotExistError, PIDDeletedError, NoResultFound) as exc:
            db.session.rollback()
            job = db.session.get(OpenAlexJob, job.id)
            job.result = {**job.result, 'items': {**job.result.get('items', {}), row['key']: {
                'state': 'blocked', 'record_id': row['id'], 'message': error_message(exc)}}, 'cursor': offset + 1}
            job.result = {**job.result, 'summary': publication_summary(records, job.result['items'])}
            job.updated = datetime.now(timezone.utc)
            db.session.commit()
    job.state = 'completed' if job.result.get('cursor', 0) >= len(records) else 'queued'
    db.session.commit()
    return job.state == 'queued'
