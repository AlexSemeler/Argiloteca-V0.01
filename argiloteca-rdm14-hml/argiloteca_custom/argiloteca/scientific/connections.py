"""Explicit record relationships; native metadata and files remain authoritative.

A term citation is a subject link, never an inferred occurrence or RAW match.
"""
from copy import deepcopy
from flask import current_app
from invenio_access.permissions import any_user, system_process
from invenio_administration.permissions import administration_permission
from invenio_db import db
from sqlalchemy import cast, text
from sqlalchemy.dialects.postgresql import JSONB
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata
from invenio_rdm_records.records.systemfields.deletion_status import RecordDeletionStatusEnum
from invenio_records_resources.services.errors import PermissionDeniedError
from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError
from .drx_links import PID, record_for
from .catalog import FIELD as CATALOG_FIELD
from .models import validator

FIELD = 'arg:conexoes_cientificas'


def lock_connection_writes():
    """Serialize scientific links with reviewed imports and permanent removal."""
    if db.engine.dialect.name=='postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))

RELATIONS = {
    'issupplementedby': ('É complementado por', 'Is supplemented by'),
    'issupplementto': ('Complementa', 'Is supplement to'),
    'references': ('Faz referência a', 'References'),
    'isreferencedby': ('É referenciado por', 'Is referenced by'),
    'describes': ('Descreve', 'Describes'),
    'isdescribedby': ('É descrito por', 'Is described by'),
}


def anonymous_identity():
    from flask_principal import AnonymousIdentity
    identity = AnonymousIdentity()
    identity.provides.add(any_user)
    return identity


def read_visible(identity, pid):
    if not PID.fullmatch(str(pid)):
        return None
    try:
        return service.read(identity, pid).to_dict()
    except (PIDDoesNotExistError, PIDDeletedError, PermissionDeniedError):
        return None


def record_url(pid):
    return current_app.config['SITE_UI_URL'].rstrip('/') + '/records/' + pid


def native_relation(link):
    return {'identifier': record_url(link['record_id']), 'scheme': 'url',
            'relation_type': {'id': link['relacao']}}


def relation_key(item):
    return (item.get('identifier'), item.get('scheme'), (item.get('relation_type') or {}).get('id'))


def validate_links(identity, source_id, links, previous=()):
    if not isinstance(links, list) or len(links) > 50:
        raise ValueError('invalid_connections')
    seen = set()
    prior = {item["record_id"]: item for item in previous}
    for link in links:
        validator('arg_conexao_cientifica.schema.json').validate(link)
        target_id = link['record_id']
        if target_id == source_id or target_id in seen:
            raise ValueError('duplicate_or_self_connection')
        seen.add(target_id)
        if link == prior.get(target_id):
            continue
        target = read_visible(identity, target_id)
        if not target or target.get('access', {}).get('record') != 'public':
            raise ValueError('public_published_target_required')
        term = target.get('custom_fields', {}).get(CATALOG_FIELD)
        if link['papel'] == 'termo':
            if not term or term['slug'] != link.get('slug') or term.get('situacao') != 'ativo':
                raise ValueError('active_catalog_term_required')
        elif term:
            raise ValueError('catalog_role_required')
        elif link['papel'] == 'dados' and target['metadata']['resource_type']['id'] != 'dataset':
            raise ValueError('dataset_target_required')
        elif link['papel'] == 'publicacao' and not target['metadata']['resource_type']['id'].startswith('publication'):
            raise ValueError('publication_target_required')


def reconcile_native_relations(metadata, previous, links):
    """Remove only citations this curator adapter created; preserve every other one."""
    metadata = deepcopy(metadata)
    relations = deepcopy(metadata.get('related_identifiers') or [])
    next_keys = {relation_key(native_relation(link)) for link in links}
    for old in previous:
        key = relation_key(native_relation(old))
        if old.get('native_relation_created') and key not in next_keys:
            relations = [item for item in relations if relation_key(item) != key]
    previous_flags = {relation_key(native_relation(link)): bool(link.get('native_relation_created')) for link in previous}
    result = deepcopy(links)
    for link in result:
        item = native_relation(link)
        key = relation_key(item)
        exists = any(relation_key(current) == key for current in relations)
        link['native_relation_created'] = previous_flags.get(key, not exists)
        if not exists:
            relations.append(item)
    if relations:
        metadata['related_identifiers'] = relations
    else:
        metadata.pop('related_identifiers', None)
    return metadata, result


def update_connection(identity, pid, *, target_id, role, relation, evidence, revision, remove=False):
    """Narrow native maintenance, protected by SQL row lock and revision check."""
    if not (system_process in identity.provides or administration_permission.allows(identity)):
        raise PermissionDeniedError('administration-access')
    from invenio_records_resources.services.uow import UnitOfWork, RecordCommitOp
    with UnitOfWork() as uow:
        lock_connection_writes()
        item = record_for(identity, pid, write=True)
        record = item._record
        record.model.__class__.query.filter_by(id=record.id).with_for_update().one()
        db.session.expire(record.model)
        record = service.record_cls.get_record(record.id)
        service.check_revision_id(record, revision)
        try:
            service.read_draft(identity, pid)
        except PIDDoesNotExistError:
            pass
        else:
            raise ValueError('existing_draft')
        fields = deepcopy(record.get('custom_fields') or {})
        if CATALOG_FIELD in fields:
            raise ValueError('select_bibliographic_or_data_record')
        previous = deepcopy(fields.get(FIELD) or [])
        links = [entry for entry in previous if entry['record_id'] != target_id]
        if remove:
            if len(links) == len(previous):
                raise ValueError('connection_not_found')
        else:
            target = read_visible(identity, target_id)
            link = {'record_id': target_id, 'papel': role, 'relacao': relation,
                    'evidencia': evidence.replace('\r\n', '\n').replace('\r', '\n').strip()}
            term = (target or {}).get('custom_fields', {}).get(CATALOG_FIELD)
            if role == 'termo' and term:
                link['slug'] = term['slug']
            links.append(link)
        validate_links(identity, pid, links, previous)
        metadata, links = reconcile_native_relations(record['metadata'], previous, links)
        fields[FIELD] = links
        record['custom_fields'] = fields
        record['metadata'] = metadata
        uow.register(RecordCommitOp(record, indexer=service.indexer, index_refresh=True))
        uow.commit()
    return record


def connections_for(identity, data, *, incoming=True):
    output = []
    for link in data.get('custom_fields', {}).get(FIELD) or []:
        target = read_visible(identity, link['record_id'])
        if target:
            output.append({'link': {key: value for key, value in link.items() if key != 'native_relation_created'},
                'record': target, 'url': '/records/' + target['id']})
    reverse = []
    if incoming:
        rows = RDMRecordMetadata.query.filter(
            RDMRecordMetadata.deletion_status == RecordDeletionStatusEnum.PUBLISHED,
            cast(RDMRecordMetadata.json['custom_fields'][FIELD], JSONB).contains([{'record_id': data['id']}])).all()
        for row in rows:
            for link in row.json.get('custom_fields', {}).get(FIELD) or []:
                if link['record_id'] == data['id']:
                    source = read_visible(identity, row.json['id'])
                    if source:
                        reverse.append({'link': {key: value for key, value in link.items() if key != 'native_relation_created'},
                            'record': source, 'url': '/records/' + source['id']})
    return {'outgoing': output, 'incoming': reverse}


def suggested_terms(data):
    """Exact declared names only; suggestions require an explicit curator action."""
    from ..mineralogia import build_mineral_profile
    found = {}
    fields = data.get('custom_fields') or {}
    names = [row.get('nome_cientifico_padronizado') or row.get('nome')
             for row in fields.get('arg:argilominerais') or [] if isinstance(row, dict)]
    names.extend(item.get('subject') for item in data.get('metadata', {}).get('subjects') or [])
    for name in filter(None, names):
        profile = build_mineral_profile(name)
        if profile and profile.get('catalog_record_id'):
            found[profile['slug']] = profile
    return list(found.values())


def resources_for(data, *, private=False):
    from ..views import _extract_points_from_record
    from .drx_links import DRXRecordLink
    query = DRXRecordLink.query.filter_by(record_id=data['id'])
    if not private and query.filter(DRXRecordLink.state != 'removed').first() is None:
        drx = 0
    elif not private:
        # Public counts cannot reveal restricted RAW associations.
        from .drx_links import record_package
        package = record_package(data['id'], {'limit': 1}, private=False)
        drx = package['pagination']['total']
    else:
        drx = query.filter(DRXRecordLink.state != 'removed').count()
    points = _extract_points_from_record(data)
    return {'drx': drx, 'points': len(points), 'terms': suggested_terms(data)}
