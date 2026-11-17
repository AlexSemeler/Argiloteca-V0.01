"""One curatorial workspace for bibliography, native record links and DRX evidence."""
from flask import abort, g, jsonify, redirect, render_template, request, url_for
from flask_wtf.csrf import generate_csrf
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_rdm_records.records.models import RDMRecordMetadata
from invenio_rdm_records.records.systemfields.deletion_status import RecordDeletionStatusEnum
from invenio_records_resources.services.errors import RevisionIdMismatchError
from invenio_pidstore.errors import PIDDoesNotExistError
from jsonschema import ValidationError
from .admin_raw_views import admin_only, store
from .catalog_views import text
from .catalog import FIELD as CATALOG_FIELD
from .connections import (FIELD, RELATIONS, connections_for, read_visible, resources_for,
                          suggested_terms, update_connection)
from .drx_links import DRXRecordLink, record_for


def find_records(query, *, include_catalog=False):
    rows = RDMRecordMetadata.query.filter(RDMRecordMetadata.deletion_status == RecordDeletionStatusEnum.PUBLISHED)
    if not include_catalog:
        rows = rows.filter(RDMRecordMetadata.json['custom_fields'][CATALOG_FIELD]['slug'].as_string().is_(None))
    if query:
        term = query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        rows = rows.filter(db.or_(RDMRecordMetadata.json['metadata']['title'].as_string().ilike('%' + term + '%', escape='\\'),
                                 RDMRecordMetadata.json['id'].as_string() == query))
    count = rows.count()
    page = max(1, request.args.get('page', 1, type=int))
    items = []
    for row in rows.order_by(RDMRecordMetadata.updated.desc()).offset((page-1)*20).limit(20):
        data = read_visible(g.identity, row.json['id'])
        if data:
            items.append(data)
    return items, count, page


def connection_summary(pid):
    """Request-identity reads for record pages; no restricted target titles leak."""
    data = read_visible(g.identity, pid)
    if not data:
        return {'outgoing': [], 'incoming': []}
    return connections_for(g.identity, data)


def register_connections(bp):
    @bp.app_context_processor
    def connection_helpers():
        return {'argilo_record_connections': connection_summary}

    @bp.after_request
    def connection_cache(response):
        if request.endpoint in {'argiloteca_scientific.connections_admin',
                                'argiloteca_scientific.connections_public',
                                'argiloteca_scientific.connections_json'}:
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
        return response

    @bp.route('/administration/scientific-connections/', methods=['GET', 'POST'], endpoint='connections_admin')
    @admin_only
    def administration():
        pid = request.values.get('record_id', '').strip()
        if pid and not read_visible(g.identity, pid):
            abort(404)
        item = record_for(g.identity, pid, write=True) if pid else None
        data = item.to_dict() if item else None
        if data and CATALOG_FIELD in data.get('custom_fields', {}):
            return redirect(url_for('.connections_public', pid=pid), code=303)
        error, status = None, 200
        if request.method == 'POST':
            if not item:
                abort(400)
            try:
                if request.form.get('confirm') != 'yes':
                    raise ValueError('confirmation_required')
                if request.form.get('action') == 'drx':
                    from .drx_links import set_link, sync_metadata
                    from invenio_records_resources.services.uow import UnitOfWork, RecordIndexOp
                    with UnitOfWork() as uow:
                        model = item._record.model
                        model.__class__.query.filter_by(id=model.id).with_for_update().one()
                        db.session.expire(model)
                        current = service.record_cls.get_record(model.id)
                        service.check_revision_id(current, int(request.form.get('revision', '-1')))
                        try:
                            service.read_draft(g.identity, pid)
                        except PIDDoesNotExistError:
                            pass
                        else:
                            raise ValueError('existing_draft')
                        repository = store()
                        row = repository.get(request.form.get('raw_id', ''))
                        set_link(g.identity, row, pid, state=request.form.get('state', 'pending'),
                            evidence=request.form.get('evidence', ''),
                            expected_revision=int(request.form.get('link_revision', '0')), actor=g.identity.id)
                        native = sync_metadata(g.identity, pid, {r['id']: r for r in repository.rows()})
                        uow.register(RecordIndexOp(native, indexer=service.indexer, index_refresh=True))
                        uow.commit()
                else:
                    update_connection(g.identity, pid, target_id=request.form.get('target_id', '').strip(),
                        role=request.form.get('role'), relation=request.form.get('relation'),
                        evidence=request.form.get('evidence', ''), revision=int(request.form.get('revision', '-1')),
                        remove=request.form.get('action') == 'remove')
                return redirect(url_for('.connections_admin', record_id=pid, saved=1), code=303)
            except (ValueError, ValidationError, RevisionIdMismatchError, KeyError) as exc:
                db.session.rollback()
                status = 409 if isinstance(exc, RevisionIdMismatchError) or str(exc) in {'existing_draft', 'link_revision_conflict'} else 422
                error = text('Não foi possível salvar. Confira o destino, a justificativa e a confirmação. Se há um rascunho aberto ou uma revisão mais recente, conclua essa edição e reabra o registro.',
                             'Could not save. Check the target, justification and confirmation. If there is an open draft or a newer revision, finish that edit and reopen the record.')
        q = request.args.get('q', '').strip()[:200]
        records, total, page = find_records(q) if not item else ([], 0, 1)
        graph = connections_for(g.identity, data) if data else {'outgoing': [], 'incoming': []}
        resources = resources_for(data, private=True) if data else None
        target_id = request.args.get('target_id', '').strip()
        target = read_visible(g.identity, target_id) if target_id else None
        if target and target.get('access', {}).get('record') != 'public':
            target = None
        target_q = request.args.get('target_q', '').strip()[:200]
        candidates = find_records(target_q, include_catalog=True)[0] if data and target_q else []
        terms = suggested_terms(data) if data else []
        linked_ids = {entry['link']['record_id'] for entry in graph['outgoing']}
        terms = [term for term in terms if term['catalog_record_id'] not in linked_ids]
        raw_q = request.args.get('raw_q', '').strip()[:100]
        raw_rows = []
        selected_raw = None
        raw_id = request.args.get('raw_id', '').strip()
        if item and (raw_q or raw_id):
            repository = store()
            if raw_id:
                try:
                    selected_raw = repository.get(raw_id)
                except KeyError:
                    abort(404)
            if raw_q:
                raw_rows = [row for row in repository.rows()
                            if raw_q.casefold() in row['filename'].casefold() or raw_q == row['id']][:15]
        drx_page = max(1, request.args.get('drx_page', 1, type=int))
        drx_query = DRXRecordLink.query.filter_by(record_id=pid).filter(DRXRecordLink.state != 'removed')
        drx_total = drx_query.count() if pid else 0
        drx_links = drx_query.order_by(DRXRecordLink.id).offset((drx_page-1)*20).limit(20).all() if pid else []
        selected_connection = next((link for link in (data or {}).get('custom_fields', {}).get(FIELD, []) if link['record_id'] == target_id), None)
        raw_link = DRXRecordLink.query.filter_by(record_id=pid, raw_id=raw_id).one_or_none() if pid and raw_id else None
        image_term = next((term for term in (resources or {}).get('terms', [])
                           if (term.get('reusable_image') or {}).get('image_url')), None)
        if not image_term and graph['outgoing']:
            for entry in graph['outgoing']:
                if CATALOG_FIELD in entry['record'].get('custom_fields', {}):
                    from ..mineralogia import build_mineral_profile
                    image_term = build_mineral_profile(entry['record']['custom_fields'][CATALOG_FIELD]['slug'])
                    break
        return render_template('semantic-ui/argiloteca/admin_scientific_connections.html',
            t=text, data=data, pid=pid, revision=item._record.revision_id if item else 0,
            records=records, total=total, page=page, q=q, graph=graph, resources=resources,
            terms=terms, target=target, target_q=target_q, candidates=candidates,
            relations=RELATIONS, error=error, csrf_token=generate_csrf(), image_term=image_term,
            raw_q=raw_q, raw_rows=raw_rows, selected_raw=selected_raw, raw_link=raw_link, drx_links=drx_links,
            drx_total=drx_total, drx_page=drx_page, selected_connection=selected_connection), status

    @bp.route('/scientific/connections/<pid>', endpoint='connections_public')
    def public(pid):
        data = read_visible(g.identity, pid)
        if not data:
            abort(404)
        graph = connections_for(g.identity, data)
        entries = [dict(entry, resources=resources_for(entry['record'])) for entry in graph['outgoing']]
        return render_template('semantic-ui/argiloteca/scientific_connections.html',
            t=text, data=data, graph=dict(graph, outgoing=entries), resources=resources_for(data))

    @bp.route('/scientific/records/<pid>/connections', endpoint='connections_json')
    def graph_json(pid):
        data = read_visible(g.identity, pid)
        if not data:
            abort(404)
        graph = connections_for(g.identity, data)
        def entry(item):
            return {'id': item['record']['id'], 'title': item['record']['metadata']['title'],
                    'url': item['url'], 'connection': item['link']}
        return jsonify({'schema_version': 1, 'record_id': pid,
                        'outgoing': [entry(item) for item in graph['outgoing']],
                        'incoming': [entry(item) for item in graph['incoming']]})
