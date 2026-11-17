"""Transactional native imports with complete database identity inventory."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

from flask import current_app
from invenio_db import db
from sqlalchemy import text

from .adapters import converter, digest, verify_snapshot
from .models import OpenAlexClaim, OpenAlexJob


def actor_identity(actor):
    from invenio_accounts.models import User
    from invenio_access.utils import get_identity
    from invenio_access.permissions import authenticated_user, any_user
    from invenio_administration.permissions import administration_permission
    user = db.session.get(User, int(actor))
    if not user or not user.active:
        raise ValueError('A conta responsável está inativa ou indisponível.')
    identity = get_identity(user)
    identity.provides.update({authenticated_user, any_user})
    if not administration_permission.allows(identity):
        raise ValueError('A conta responsável não possui mais permissão administrativa.')
    return identity


def repository_handle(item):
    """Only explicit Handles or exact institutional landing URLs are identities."""
    value = str(item.get('identifier', ''))
    if item.get('scheme') == 'handle' and re.fullmatch(r'(?:10183|123456789)/[0-9]+', value):
        return value
    if item.get('scheme') != 'url': return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http','https'} or parsed.username or parsed.password or parsed.port not in (None,80,443) or parsed.query or parsed.fragment: return ''
        prefix = {'lume.ufrgs.br':'10183','www.lume.ufrgs.br':'10183','repositorio.ufsc.br':'123456789'}.get(parsed.hostname)
        match = re.fullmatch(r'/(?:xmlui/)?handle/(' + re.escape(prefix) + r'/[0-9]+)/?', parsed.path) if prefix else None
        return match[1] if match else ''
    except ValueError:
        return ''


def tokens(payload, metadata):
    """Only declared primary DOI and structured DOI/OpenAlex identifiers."""
    result = set()
    pid = (payload.get('pids') or {}).get('doi', {})
    doi = metadata.normalize_doi(pid.get('identifier')) if isinstance(pid, dict) else ''
    if doi:
        result.add('doi:' + doi)
    openalex_pid = (payload.get('pids') or {}).get('openalex', {})
    work = metadata.normalize_openalex_id(openalex_pid.get('identifier')) if isinstance(openalex_pid, dict) else ''
    if work:
        result.add('openalex:' + work)
    for item in (payload.get('metadata') or {}).get('identifiers', []) or []:
        if not isinstance(item, dict):
            continue
        value = item.get('identifier', '')
        # A declared identifier can be a DOI even in legacy exports with a
        # nonstandard scheme. Never extract identities from descriptions/references.
        doi = metadata.normalize_doi(value)
        if doi:
            result.add('doi:' + doi)
        handle = repository_handle(item)
        if handle:
            result.add('handle:' + handle)
        work = metadata.normalize_openalex_id(value)
        if work:
            result.add('openalex:' + work)
    return result


def inventory(metadata):
    """Scan live records and drafts, excluding edits of retired publications."""
    from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
    index = {}
    for model, kind in ((RDMRecordMetadata, 'published'), (RDMDraftMetadata, 'draft')):
        query = db.session.query(model.json).filter(model.json.isnot(None))
        if kind == 'published':
            query = query.filter(model.deletion_status == 'P')
        else:
            # Native soft deletion retains edit-draft JSON for recovery. Such
            # drafts must not compete with the canonical record after a merge.
            from sqlalchemy import or_
            query = query.outerjoin(RDMRecordMetadata, model.id == RDMRecordMetadata.id).filter(
                or_(RDMRecordMetadata.id.is_(None), RDMRecordMetadata.deletion_status == 'P'))
        for (data,) in query.yield_per(300):
            rid = data.get('id')
            if not rid:
                raise ValueError('Inventário encontrou registro sem identificador; importação interrompida.')
            for token in tokens(data, metadata):
                index.setdefault(token, {})[(str(rid), kind)] = {'id': str(rid), 'kind': kind}
    # Claims remain even if a record was deleted, preventing silent re-creation.
    for claim in OpenAlexClaim.query.yield_per(300):
        index.setdefault(claim.token, {}).setdefault((claim.draft_id, 'draft'),
            {'id': claim.draft_id, 'kind': 'draft', 'previous_job': claim.job_id})
    return index


def unique_matches(values):
    """Published, draft and claim entries with the same PID are one record."""
    found = {}
    for value in values:
        rid = str(value['id'])
        if rid not in found or value['kind'] == 'published':
            found[rid] = value
    return list(found.values())


def matches(row, index, metadata):
    found = []
    for token in tokens(row['payload'], metadata):
        found.extend(index.get(token, {}).values())
    return unique_matches(found)


def external_doi_payload(payload, external_doi_enabled):
    """Retain an external bibliographic DOI when native DOI PIDs are disabled.

    Never move a locally managed PID or mutate the reviewed source snapshot.
    """
    result = deepcopy(payload)
    doi = result.get('pids', {}).get('doi', {})
    if external_doi_enabled or doi.get('provider') != 'external':
        return result
    value = doi.get('identifier')
    if not value:
        return result
    identifiers = result.setdefault('metadata', {}).setdefault('identifiers', [])
    identifier = {'scheme': 'doi', 'identifier': value}
    if identifier not in identifiers:
        identifiers.append(identifier)
    del result['pids']['doi']
    if not result['pids']:
        del result['pids']
    return result


def native_payload(service, payload):
    providers = service.config.pids_providers
    return external_doi_payload(payload, 'external' in providers.get('doi', {}))


def validate_native(identity, payload, requirements=None, vocabulary_cache=None):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    payload = native_payload(service, payload)
    # Schema loading checks structure; vocabulary existence requires explicit reads.
    service.schema.load(deepcopy(payload), context={'identity': identity}, raise_errors=True)
    from invenio_vocabularies.proxies import current_service as vocabularies
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
    from sqlalchemy.orm.exc import NoResultFound
    from marshmallow import ValidationError
    if requirements is None:
        requirements = converter(current_app.config['ARGILOTECA_OPENALEX_ROOT'])[0].required_vocabularies
    for vocabulary, identifier in requirements(payload):
        token = (vocabulary, identifier)
        if vocabulary_cache is not None and token in vocabulary_cache:
            continue
        try:
            vocabularies.read(identity, (vocabulary, identifier))
            if vocabulary_cache is not None:
                vocabulary_cache.add(token)
        except (PIDDoesNotExistError, PIDDeletedError, NoResultFound):
            raise ValidationError({vocabulary: ['Identificador ausente ou excluído na instância: ' + identifier]}) from None


def review_context(root, actor):
    """One immutable, task-local identity/classifier inventory for all blocks."""
    metadata, _, _ = converter(root)
    identity = actor_identity(actor)
    from .classification import load_vocabulary, community_catalog
    vocabulary, version = load_vocabulary(root)
    return {'metadata': metadata, 'identity': identity, 'index': inventory(metadata),
            'classification': (vocabulary, version, community_catalog(identity)),
            'vocabulary_cache': set()}


def review_snapshot(root, snapshot, actor, context=None):
    context = context or review_context(root, actor)
    metadata, identity, index = context['metadata'], context['identity'], context['index']
    for row in snapshot['records']:
        row['instance_validation'] = 'not_run'
        row['duplicates'] = matches(row, index, metadata)
        if len({m['id'] for m in row['duplicates']}) > 1:
            row['issues'].append({'severity': 'error', 'code': 'duplicate_conflict', 'path': 'identity',
                'message': 'Múltiplos registros existentes correspondem à identidade. Resolva o conflito antes de importar.'})
            row['status'] = 'bloqueado'
        if row['status'] != 'bloqueado':
            try:
                validate_native(identity, row['payload'], metadata.required_vocabularies,
                                vocabulary_cache=context['vocabulary_cache'])
                row['instance_validation'] = 'valid'
            except Exception as exc:
                from marshmallow import ValidationError
                if not isinstance(exc, ValidationError):
                    raise
                row['issues'].append({'severity': 'error', 'code': 'native_schema', 'path': 'metadata',
                                      'message': json.dumps(exc.messages, ensure_ascii=False, default=str)})
                row['status'] = 'bloqueado'
                row['instance_validation'] = 'invalid'
    snapshot['source_summary'] = deepcopy(snapshot['summary'])
    snapshot['summary'] = {**snapshot['summary'], **{status: sum(row['status'] == status for row in snapshot['records'])
        for status in ('apto', 'apto_com_alertas', 'bloqueado')}}
    from .classification import classify_snapshot
    return classify_snapshot(root,snapshot,identity, context=context['classification'])


@contextmanager
def job_lock(job_id):
    key = int.from_bytes(hashlib.sha256(job_id.encode()).digest()[:8], 'big', signed=True)
    # A dedicated connection keeps the session lock across item transactions.
    with db.engine.connect() as connection:
        locked = connection.execute(text('SELECT pg_try_advisory_lock(:key)'), {'key': key}).scalar()
        try:
            yield bool(locked)
        finally:
            if locked:
                connection.execute(text('SELECT pg_advisory_unlock(:key)'), {'key': key})
                connection.commit()



def update_payload(current, incoming, metadata):
    """Replace supplied bibliography fields, retaining curated and native state."""
    existing_tokens, incoming_tokens = tokens(current, metadata), tokens(incoming, metadata)
    if not existing_tokens.intersection(incoming_tokens):
        raise ValueError('A identidade atual do registro não confirma a correspondência histórica. Nenhum registro novo foi criado.')
    old_doi = {v for v in existing_tokens if v.startswith('doi:')}
    new_doi = {v for v in incoming_tokens if v.startswith('doi:')}
    if old_doi and new_doi and old_doi != new_doi:
        raise ValueError('DOIs diferentes para a mesma correspondência OpenAlex. Confira a identidade antes de sobrescrever.')
    proposed = {**deepcopy(current.get('metadata', {})), **deepcopy(incoming['metadata'])}
    identifiers = deepcopy(current.get('metadata', {}).get('identifiers', []))
    for identifier in incoming['metadata'].get('identifiers', []):
        if identifier not in identifiers:
            identifiers.append(deepcopy(identifier))
    if identifiers:
        proposed['identifiers'] = identifiers
    result = {'metadata': proposed, 'custom_fields': deepcopy(current.get('custom_fields', {}))}
    for field in ('files', 'media_files'):
        existing = current.get(field, {})
        result[field] = {key: deepcopy(existing[key]) for key in ('enabled', 'default_preview') if key in existing}
    # Access, ownership, communities and PID providers remain under native control.
    # An absent DOI may be completed using the incoming external identifier.
    if not old_doi and incoming.get('pids', {}).get('doi'):
        result['pids'] = {**deepcopy(current.get('pids', {})), 'doi': deepcopy(incoming['pids']['doi'])}
    return result


def update_existing(service, identity, target, row, metadata, uow):
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
    from sqlalchemy.orm.exc import NoResultFound
    rid = str(target['id'])
    try:
        # edit() returns the existing draft or edits the SAME published PID.
        # It never allocates a new record/version identifier.
        existing = service.edit(identity, rid, uow=uow)
    except (PIDDoesNotExistError, PIDDeletedError, NoResultFound):
        raise ValueError('O registro existente ' + rid + ' foi excluído ou está indisponível. A importação não cria uma substituição automática.') from None
    before = existing.to_dict()
    revision = existing._record.revision_id
    payload = native_payload(service, update_payload(before, row['payload'], metadata))
    validate_native(identity, payload, metadata.required_vocabularies)
    updated = service.update_draft(identity, rid, payload, revision_id=revision, uow=uow)
    data = updated.to_dict()
    if str(data['id']) != rid or data.get('errors'):
        raise ValueError('Atualização recusada pela validação nativa: ' + json.dumps(data.get('errors', []), ensure_ascii=False))
    return data, {
        'state': 'updated', 'draft_id': rid, 'record_id': rid,
        'published_record': bool(before.get('is_published')),
        'before': {key: deepcopy(before[key]) for key in ('metadata', 'custom_fields', 'pids', 'access', 'files', 'media_files') if key in before},
        'before_revision': revision,
    }


def checkpoint_claims(data, job, row, metadata):
    for token in tokens(data, metadata):
        claim = db.session.get(OpenAlexClaim, token)
        if claim and claim.draft_id != str(data['id']):
            raise ValueError('A identidade já pertence a outro registro. Nenhum registro novo foi criado.')
        if not claim:
            claim = OpenAlexClaim(token=token, draft_id=str(data['id']), job_id=job.id,
                                  payload_sha256=row['payload_sha256'])
            db.session.add(claim)
        else:
            claim.job_id = job.id
            claim.payload_sha256 = row['payload_sha256']


def import_job(job, root, verify=verify_snapshot):
    from invenio_rdm_records.proxies import current_rdm_records_service as service
    from invenio_records_resources.services.uow import UnitOfWork
    snapshot = job.snapshot
    from .maintenance import pending_lot_maintenance
    if pending_lot_maintenance(Path(snapshot['source']).name):
        raise ValueError('Há manutenção confirmada do lote; importação interrompida antes da escrita.')
    verify(root, snapshot)
    metadata, _, _ = converter(root)
    identity = actor_identity(job.actor)
    # Failure of a complete inventory aborts the job before any creation.
    index = inventory(metadata)
    selected = set(job.params['selected'])
    outcomes = deepcopy(job.result.get('items', {}))
    for row in snapshot['records']:
        key = row['key']
        if key not in selected or outcomes.get(key, {}).get('state') in {'created', 'updated', 'duplicate'}:
            continue
        if not tokens(row['payload'], metadata):
            raise ValueError('Identidade DOI/OpenAlex/Handle ausente.')
        if row['status'] == 'bloqueado':
            raise ValueError('Um registro selecionado está bloqueado.')
        if digest(row['payload']) != row['payload_sha256']:
            raise ValueError('Hash do payload divergente.')
        with UnitOfWork() as uow:
            # All module imports serialize creation and claim writes in PostgreSQL.
            db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
            found = matches(row, index, metadata)
            for claim in OpenAlexClaim.query.filter(OpenAlexClaim.token.in_(tokens(row['payload'], metadata))):
                if not any(m['id'] == claim.draft_id for m in found):
                    found.append({'id': claim.draft_id, 'kind': 'draft', 'previous_job': claim.job_id})
            found = unique_matches(found)
            if len(found) > 1:
                raise ValueError('Mais de um registro corresponde ao DOI/OpenAlex. Resolva o conflito antes de sobrescrever; nenhum registro novo foi criado.')
            if found:
                data, outcomes[key] = update_existing(service, identity, found[0], row, metadata, uow)
            else:
                payload = native_payload(service, row['payload'])
                validate_native(identity, payload, metadata.required_vocabularies)
                draft = service.create(identity, payload, uow=uow)
                data = draft.to_dict()
                if data.get('errors') or data.get('is_published'):
                    raise ValueError('O rascunho não passou na validação nativa: ' + json.dumps(data.get('errors', []), ensure_ascii=False))
                draft_id = str(data['id'])
                outcomes[key] = {'state': 'created', 'draft_id': draft_id}
            if 'communities' in job.params:
                from .classification import attach_communities
                selected_communities = job.params['communities'].get(key,[])
                classification = row.get('classification')
                if selected_communities and not classification:
                    raise ValueError('Prepare outra revisão para classificar este lote nas comunidades.')
                if classification:
                    record = service.draft_cls.pid.resolve(str(data['id']),registered_only=False)
                    applied = attach_communities(identity,record,classification,selected_communities,uow)
                    outcomes[key]['communities'] = applied
            if row['payload'].get('pids', {}).get('doi') and not data.get('pids', {}).get('doi'):
                outcomes[key]['doi_storage'] = 'metadata_identifier'
            checkpoint_claims(data, job, row, metadata)
            for token in tokens(data, metadata):
                index.setdefault(token, {})[(str(data['id']), 'draft')] = {'id': str(data['id']), 'kind': 'draft'}
            # The checkpoint and native draft commit in the SAME database transaction.
            job.result = {'items': deepcopy(outcomes)}
            job.updated = datetime.now(timezone.utc)
            db.session.add(job)
            uow.commit()
    job.state = 'completed'
    job.result = {'items': outcomes, 'summary': {
        state: sum(v.get('state') == state for v in outcomes.values()) for state in ('created', 'updated', 'duplicate')}}
    db.session.commit()
