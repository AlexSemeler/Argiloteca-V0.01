"""Administrative catalog and coordinate curation, using native authorization."""
from copy import deepcopy
import math

from flask import abort, current_app, g, redirect, render_template, request, url_for
from flask_wtf.csrf import generate_csrf
from flask_babel import get_locale
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_records_resources.services.errors import RevisionIdMismatchError
from jsonschema import ValidationError
from .admin_raw_views import admin_only
from .catalog import CORE, FIELD, catalog_rows, save_term, public_map_records


def text(pt, en):
    return pt if get_locale().language == 'pt' else en


def coordinate_targets(fields):
    targets = []
    if not any(isinstance(item, dict) for item in fields.get('arg:amostras') or []):
        targets.append(('legacy', '', fields.get('arg:amostra_latitude'), fields.get('arg:amostra_longitude')))
    for field, label in [('arg:amostras', 'Amostra'), ('arg:argilominerais', 'Argilomineral')]:
        for index, item in enumerate(fields.get(field) or []):
            if isinstance(item, dict):
                targets.append((field + '/' + str(index),
                    str(item.get('codigo_amostra') or item.get('nome') or index + 1),
                    item.get('latitude'), item.get('longitude')))
    return targets


def patch_coordinates(fields, target, latitude, longitude):
    """Edit the existing canonical location; never replace unrelated metadata."""
    if target not in {entry[0] for entry in coordinate_targets(fields)}:
        raise ValueError('invalid_target')
    try:
        lat, lon = float(latitude), float(longitude)
    except (TypeError, ValueError):
        raise ValueError('invalid_coordinates') from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError('invalid_coordinates')
    fields = deepcopy(fields)
    if target == 'legacy':
        if fields.get('arg:amostras'):
            raise ValueError('select_structured_sample')
        fields.update({'arg:amostra_latitude': lat, 'arg:amostra_longitude': lon})
    else:
        field, index = target.rsplit('/', 1)
        fields[field][int(index)].update(latitude=lat, longitude=lon)
    return fields


def register_catalog(bp):
    @bp.after_request
    def private_admin(response):
        if request.endpoint and request.endpoint.rsplit('.', 1)[-1] in {'catalog_admin', 'catalog_edit', 'map_admin'}:
            response.headers['Cache-Control'] = 'private, no-store'
        return response

    @bp.route('/administration/mineral-catalog/', endpoint='catalog_admin')
    @admin_only
    def listing():
        # Drafts take precedence for editing; the public site still reads published JSON.
        entries = {row.json['custom_fields'][FIELD]['slug']: dict(row.json, revision=row.version_id, draft=False)
                   for row in catalog_rows()}
        for row in catalog_rows(drafts=True):
            entries[row.json['custom_fields'][FIELD]['slug']] = dict(row.json, revision=row.version_id, draft=True)
        q = request.args.get('q', '').strip().casefold()
        rows = sorted(entries.values(), key=lambda row: row['custom_fields'][FIELD]['nome_pt'].casefold())
        rows = [row for row in rows if not q or q in str(row['custom_fields'][FIELD]).casefold()]
        from ..mineralogia import build_mineral_profile
        images = {row['id']: (build_mineral_profile(row['custom_fields'][FIELD]['slug']) or {}).get('reusable_image') or {} for row in rows}
        return render_template('semantic-ui/argiloteca/admin_mineral_catalog.html',
            rows=rows, images=images, field=FIELD, t=text, q=request.args.get('q', ''))

    @bp.route('/administration/mineral-catalog/new', defaults={'pid': None}, methods=['GET', 'POST'], endpoint='catalog_edit')
    @bp.route('/administration/mineral-catalog/<pid>', methods=['GET', 'POST'], endpoint='catalog_edit')
    @admin_only
    def edit(pid):
        from invenio_pidstore.errors import PIDDoesNotExistError
        item, term, revision = None, {'situacao': 'ativo'}, 0
        if pid:
            try:
                item = service.read_draft(g.identity, pid)
            except PIDDoesNotExistError:
                item = service.read(g.identity, pid)
            service.require_permission(g.identity, 'edit', record=item._record)
            term = deepcopy(item.to_dict().get('custom_fields', {}).get(FIELD))
            if not term:
                abort(404)
            revision = item._record.revision_id
        error, status = None, 200
        if request.method == 'POST':
            try:
                # HTML forms encode textarea newlines as CRLF. Keep the
                # canonical LF representation so an untouched description is
                # not rewritten merely by opening and publishing the form.
                term.update({key: request.form.get(key, '').replace('\r\n', '\n').replace('\r', '\n').strip()
                             for key in CORE if key != 'external_uri'})
                if request.form.get('external_uri', '').strip():
                    term['external_uri'] = request.form['external_uri'].strip()
                else:
                    term.pop('external_uri', None)
                term.update(slug=request.form.get('slug', '').strip(), situacao=request.form.get('situacao'),
                    sinonimos=[value.strip() for value in request.form.get('sinonimos', '').splitlines() if value.strip()])
                if term.get('external_uri') and not term['external_uri'].startswith(('https://', 'http://')):
                    raise ValueError('invalid_source_url')
                result = save_term(g.identity, term, pid=pid,
                    revision=int(request.form.get('revision', '-1')), publish=request.form.get('action') == 'publish')
                return redirect(url_for('.catalog_edit', pid=result.id, saved=request.form.get('action')), code=303)
            except (ValueError, ValidationError, RevisionIdMismatchError) as exc:
                db.session.rollback()
                status = 409 if isinstance(exc, RevisionIdMismatchError) else 422
                error = text('Não foi possível salvar. Confira os campos obrigatórios e o identificador. Se outra pessoa editou o termo, reabra a página.',
                             'Could not save. Check the required fields and identifier. If another person edited this term, reopen the page.')
        return render_template('semantic-ui/argiloteca/admin_mineral_term.html',
            term=term, pid=pid, revision=revision, csrf_token=generate_csrf(), t=text, error=error), status

    @bp.route('/administration/mineral-map/', methods=['GET', 'POST'], endpoint='map_admin')
    @admin_only
    def map_admin():
        from .drx_links import record_for
        from invenio_records_resources.services.uow import RecordCommitOp, UnitOfWork
        from invenio_pidstore.errors import PIDDoesNotExistError
        pid = request.values.get('record_id', '').strip()
        item = record_for(g.identity, pid, write=True) if pid else None
        error, status = None, 200
        if request.method == 'POST':
            if not item:
                abort(400)
            try:
                with UnitOfWork() as uow:
                    # Use the narrow native maintenance pattern from DRX links.
                    # Republishing an old record would validate/copy unrelated
                    # historical files; a coordinate correction must preserve them.
                    record = item._record
                    record.model.__class__.query.filter_by(id=record.id).with_for_update().one()
                    db.session.expire(record.model)
                    record = service.record_cls.get_record(record.id)
                    service.check_revision_id(record, int(request.form.get('revision', '-1')))
                    try:
                        service.read_draft(g.identity, pid)
                    except PIDDoesNotExistError:
                        pass
                    else:
                        raise ValueError('existing_draft')
                    fields = record.get('custom_fields') or {}
                    updated_fields = patch_coordinates(fields,
                        request.form.get('target'), request.form.get('latitude'), request.form.get('longitude'))
                    if updated_fields != fields:
                        record['custom_fields'] = updated_fields
                        uow.register(RecordCommitOp(record))
                    uow.commit()
            except (ValueError, RevisionIdMismatchError) as exc:
                db.session.rollback()
                status = 409 if isinstance(exc, RevisionIdMismatchError) or str(exc) == 'existing_draft' else 422
                error = text('Confira as coordenadas. Se há um rascunho aberto, conclua a edição no depósito antes de atualizar o mapa.',
                             'Check the coordinates. If there is an open draft, finish editing it in the deposit before updating the map.')
            else:
                # Indexing runs after the database commit. Its failure cannot
                # undo the saved coordinates; resubmitting them only reindexes.
                try:
                    service.indexer.index(record, arguments={'refresh': True})
                except Exception:
                    current_app.logger.exception('Could not index saved coordinates for record %s', pid)
                    return redirect(url_for('.map_admin', record_id=pid, saved='index_pending'), code=303)
                return redirect(url_for('.map_admin', record_id=pid, saved=1), code=303)
        from ..views import _extract_points_from_record
        q = request.args.get('q', '').strip().casefold()
        records = []
        for row in public_map_records():
            if q and q not in (row['id'] + ' ' + row['metadata']['title']).casefold(): continue
            points = _extract_points_from_record(row)
            if points:
                records.append(dict(id=row['id'], title=row['metadata']['title'], points=len(points), locations=points))
        page = max(1, request.args.get('page', 1, type=int))
        page = min(page, max(1, math.ceil(len(records)/25)))
        visible = records[(page-1)*25:page*25]
        locations = [point for row in visible for point in row['locations']]
        if item:
            locations = _extract_points_from_record(item.to_dict()) + [point for point in locations if point['record_id'] != pid]
        map_points = [dict(record_id=p['record_id'], label=p['label'], title=p['title'], lat=p['lat'], lon=p['lon'],
            href=url_for('.map_admin', record_id=p['record_id'])) for p in locations
            if math.isfinite(p['lat']) and math.isfinite(p['lon']) and -90<=p['lat']<=90 and -180<=p['lon']<=180][:2000]
        return render_template('semantic-ui/argiloteca/admin_mineral_map.html',
            records=visible, map_points=map_points, total=len(records), page=page, q=request.args.get('q', ''),
            item=item.to_dict() if item else None, pid=pid, revision=item._record.revision_id if item else 0,
            targets=coordinate_targets(item.to_dict().get('custom_fields') or {}) if item else [],
            csrf_token=generate_csrf(), t=text, error=error), status
