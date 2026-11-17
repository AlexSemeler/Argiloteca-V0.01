"""Catalog authoring and public SQL reads through native Invenio records.

The source files are migration inputs. Published native JSON is authoritative;
request-local caches never survive an administrative edit.
"""
from copy import deepcopy
from datetime import date
import hashlib
import html
import json

from flask import current_app, g, has_app_context, has_request_context
from invenio_db import db
from invenio_access.permissions import system_identity, any_user
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
from invenio_rdm_records.records.systemfields.deletion_status import RecordDeletionStatusEnum
from . import PROFILE_FIELD, PROFILE_VERSION
from .models import validator

FIELD = 'arg:termo_catalogo'
CORE = ('nome_pt', 'nome_en', 'nome_cientifico_padronizado', 'grupo_mineralogico',
        'classe_estrutural', 'formula_ideal', 'descricao_curta', 'descricao_classica',
        'observacao_proveniencia', 'external_uri')


def available():
    return has_app_context() and 'invenio-rdm-records' in current_app.extensions


def catalog_rows(*, drafts=False):
    model = RDMDraftMetadata if drafts else RDMRecordMetadata
    query = model.query.filter(model.json['custom_fields'][FIELD]['slug'].as_string().isnot(None))
    return query.order_by(model.created).all()


def public_catalog(term=None):
    """Return active public terms; known withdrawn/private terms suppress seeds."""
    if not available():
        return {}
    if has_request_context() and hasattr(g, 'argiloteca_native_catalog'):
        return g.argiloteca_native_catalog
    from ..mineralogia import normalize_lookup_key, _mineral_lookup_index
    key = normalize_lookup_key(term) if term is not None else None
    legacy_id = _mineral_lookup_index().get(key) if key else None
    rows = getattr(g, 'argiloteca_native_catalog_rows', None) if has_request_context() else None
    if rows is None:
        rows = catalog_rows()
        if has_request_context():g.argiloteca_native_catalog_rows = rows
    profiles = getattr(g, 'argiloteca_native_catalog_profiles', {}) if has_request_context() else {}
    result = {};seen = set()
    for row in rows:
        saved = row.json['custom_fields'][FIELD]
        slug = saved['slug']
        if slug in seen:
            raise RuntimeError('Duplicate native catalog term: ' + slug)
        seen.add(slug)
        active = (row.deletion_status == RecordDeletionStatusEnum.PUBLISHED
                  and row.json.get('access', {}).get('record') == 'public'
                  and saved.get('situacao') == 'ativo')
        if term is not None:
            enriched = saved.get('enriquecimento') or {}
            aliases = [slug, *(saved.get(k, enriched.get(k)) for k in
                       ('nome_pt', 'nome_en', 'nome_cientifico_padronizado')),
                       *(saved.get('sinonimos', enriched.get('sinonimos', [])) or [])]
            # Known private/withdrawn slugs still suppress file seeds. Names of
            # inaccessible records are never used to resolve public aliases.
            if slug not in (term, legacy_id) and not (
                    active and key in {normalize_lookup_key(v) for v in aliases}):
                continue
        if slug in profiles:
            result[slug] = profiles[slug]
            continue
        result[slug] = None
        if not active:
            profiles[slug] = None
            continue
        # No privileged identity: the same native read policy as anonymous OAI.
        from flask_principal import AnonymousIdentity
        identity = AnonymousIdentity()
        identity.provides.add(any_user)
        # Keep the native anonymous permission check, without serializing the
        # entire API response (links, vocabularies and schemas) for a menu.
        item = service.read(identity, row.json['id'])
        record = item._record
        saved = record['custom_fields'][FIELD]
        profile = deepcopy(saved.get('enriquecimento', {}))
        profile.update({key: deepcopy(value) for key, value in saved.items()
                        if key not in {'enriquecimento', 'source_sha256'}})
        profile.update(id=slug, slug=slug, nome=saved['nome_pt'],
                       classic_description=saved.get('descricao_classica', ''),
                       catalog_record_id=item.id, catalog_updated=record.updated.isoformat())
        from ..mineralogia import build_curatorial_facts, resolve_external_reference, clean_list
        profile['curatorial_facts'] = build_curatorial_facts(profile)
        profile['reference'] = resolve_external_reference(profile)
        profile['aliases'] = clean_list([saved['nome_pt'], saved['nome_en'], saved['nome_cientifico_padronizado'], *saved.get('sinonimos', [])])
        result[slug] = profile
        profiles[slug] = profile
    if has_request_context():
        g.argiloteca_native_catalog_profiles = profiles
        if term is None:g.argiloteca_native_catalog = result
    return result


def invalidate_public_catalog():
    """Invalidate full and targeted views after a committed curatorial edit."""
    if has_request_context():
        for key in ('argiloteca_native_catalog', 'argiloteca_native_catalog_rows',
                    'argiloteca_native_catalog_profiles'):
            g.pop(key, None)


def from_profile(profile):
    term = {key: str(profile[key]) for key in CORE if profile.get(key)}
    term.update(slug=profile['slug'], situacao='ativo',
                sinonimos=list(dict.fromkeys(profile.get('aliases', []))),
                enriquecimento=deepcopy(profile),
                source_sha256=hashlib.sha256(json.dumps(profile, ensure_ascii=False,
                    sort_keys=True, allow_nan=False).encode()).hexdigest())
    term.setdefault('descricao_classica', profile.get('classic_description') or '')
    validator('arg_termo_catalogo.schema.json').validate(term)
    return term


def payload(term):
    validator('arg_termo_catalogo.schema.json').validate(term)
    return dict(metadata=dict(title=term['nome_pt'], resource_type={'id': 'other'},
        publication_date=date.today().isoformat(),
        creators=[{'person_or_org': {'type': 'organizational', 'name': 'Argiloteca / CPAA'}}],
        description='<p>' + html.escape(term.get('descricao_curta') or term['nome_cientifico_padronizado']) + '</p>',
        subjects=[{'subject': term['nome_cientifico_padronizado']}]),
        access={'record': 'public', 'files': 'public'}, files={'enabled': False},
        custom_fields={PROFILE_FIELD: PROFILE_VERSION, FIELD: deepcopy(term)})


def save_term(identity, term, *, pid=None, revision=None, publish=False):
    """One native unit of work; stale forms and existing drafts cannot be lost."""
    from invenio_records_resources.services.uow import UnitOfWork
    from sqlalchemy import text
    validator('arg_termo_catalogo.schema.json').validate(term)
    with UnitOfWork() as uow:
        # Serialize create/retry by the permanent slug across all web workers.
        db.session.execute(text('SELECT pg_advisory_xact_lock(:key)'),
            {'key': int.from_bytes(hashlib.sha256(term['slug'].encode()).digest()[:8], 'big', signed=True)})
        known = [row.json for row in [*catalog_rows(), *catalog_rows(drafts=True)]
                 if row.json['custom_fields'][FIELD]['slug'] == term['slug']]
        if any(row['id'] != pid for row in known):
            raise ValueError('duplicate_slug')
        data = payload(term)
        if pid:
            from invenio_pidstore.errors import PIDDoesNotExistError
            try:
                draft = service.read_draft(identity, pid)
            except PIDDoesNotExistError:
                published = service.read(identity, pid)
                service.check_revision_id(published._record, revision)
                draft = service.edit(identity, pid, uow=uow)
            else:
                service.check_revision_id(draft._record, revision)
            old = draft.to_dict()
            previous = old.get('custom_fields', {}).get(FIELD)
            if not previous or previous['slug'] != term['slug']:
                raise ValueError('immutable_slug')
            data = {key: deepcopy(old[key]) for key in ('metadata', 'access', 'files', 'pids', 'custom_fields') if key in old}
            data['custom_fields'][FIELD] = deepcopy(term)
            data['metadata']['title'] = term['nome_pt']
            data['metadata']['description'] = payload(term)['metadata']['description']
            data['metadata']['subjects'] = payload(term)['metadata']['subjects']
            draft = service.update_draft(identity, pid, data, uow=uow)
        else:
            draft = service.create(identity, data, uow=uow)
        if draft.to_dict().get('errors'):
            raise ValueError('native_validation_failed')
        result = service.publish(identity, draft.id, uow=uow) if publish else draft
        uow.commit()
        invalidate_public_catalog()
    return result


def public_map_records():
    """Read canonical public JSON, bypassing stale snapshots and search projections."""
    rows = RDMRecordMetadata.query.filter(
        RDMRecordMetadata.deletion_status == RecordDeletionStatusEnum.PUBLISHED,
        RDMRecordMetadata.json['access']['record'].as_string() == 'public').yield_per(100)
    for row in rows:
        fields = (row.json or {}).get('custom_fields') or {}
        if FIELD not in fields:
            yield deepcopy(row.json)


def install_catalog():
    """Idempotently promote the already-public catalog; never overwrite curation."""
    from ..mineralogia import build_file_mineral_profile, load_argilominerais_vocabulary
    known = {row.json['custom_fields'][FIELD]['slug'] for row in [*catalog_rows(), *catalog_rows(drafts=True)]}
    report = {'created': [], 'skipped': [], 'profile': PROFILE_VERSION}
    for slug in sorted(load_argilominerais_vocabulary()):
        if slug in known:
            report['skipped'].append(slug)
            # Recover the post-commit indexing step after an interrupted run.
            for row in catalog_rows():
                if row.json['custom_fields'][FIELD]['slug'] == slug and row.deletion_status == RecordDeletionStatusEnum.PUBLISHED:
                    service.indexer.index(service.record_cls.get_record(row.id))
            continue
        profile = build_file_mineral_profile(slug)
        result = save_term(system_identity, from_profile(profile), publish=True)
        report['created'].append({'slug': slug, 'id': result.id})
    from invenio_oaiserver.models import OAISet
    if OAISet.query.filter_by(spec='argiloteca:catalogo').one_or_none() is None:
        db.session.add(OAISet(spec='argiloteca:catalogo', name='Catálogo autorizado de argilominerais',
            search_pattern=r'custom_fields.arg\:indice_cientifico_v1.catalog_slug:*'))
        db.session.commit()
    report['oai_set'] = 'argiloteca:catalogo'
    return report
