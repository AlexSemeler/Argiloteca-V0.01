"""Permission-aware routes for record/RAW links and shared workbench curves."""
from io import BytesIO

from flask import abort, g, jsonify, render_template, request, send_file, redirect, url_for
from flask_wtf.csrf import generate_csrf
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from .admin_raw_views import store, admin_only, preview
from .restricted_review import can_review
from .drx_links import (DRXRecordLink, item_payload, record_package, record_for,
                        set_link, sync_metadata, visible_links, analysis_for, native_records_available)


def allowed_row(raw_id):
    try:
        row = store().get(raw_id)
    except (KeyError, FileNotFoundError):
        abort(404)
    if row['access'] != 'public_snapshot' and not can_review():
        abort(404)
    return row


def linked_curve(raw_id):
    row = allowed_row(raw_id)
    curve = preview(store(), raw_id)
    item = item_payload(row, include_pending=can_review())
    analysis = analysis_for(row)
    metadata = dict(item['metadata'], raw_id=row['id'], original_filename=row['filename'], sample_code=row['sample_code'],
        source_sha256=row['sha256'], preparation=item['preparation'], record_links=item['record_links'],
        mineral_candidates=item['mineral_candidates'], detected_peaks=item['detected_peaks'],
        argilominerais=[c['mineral'] for c in item['mineral_candidates'] if c.get('mineral')],
        record_id=item['record_id'], access=row['access'], download_url=item['download_url'])
    if analysis:
        metadata['reference_pilot'] = analysis['pilot']
        metadata['classification_revision'] = analysis['engine']
        metadata['primary_status'] = analysis['primary']['status']
        metadata['axis_provenance'] = analysis.get('axis_provenance')
        metadata['ngc_status'] = analysis['ngc']['status']
        if analysis['primary']['status'] != 'evaluated':
            from flask_babel import get_locale
            metadata['qc_flags'] = [{'code': 'PRIMARY_REQUIRES_COMPATIBLE_RADIATION_AND_AXIS',
                'message': ('Classificador primário Cu não aplicado: revise a radiação e o eixo declarados. As evidências estruturais estão separadas no piloto.'
                    if get_locale().language == 'pt' else
                    'Cu primary classifier not applied: review the declared radiation and axis. Structural evidence is provided separately in the pilot.')}]
    return dict(success=True, metadata=metadata, two_theta=curve['x'], intensity=curve['intensity'],
                render_points=len(curve['x']), total_points=curve['original_points'])


def decorate_public_items(items):
    """Add database associations to the existing snapshot contract without changing IDs."""
    if not native_records_available():
        return items
    rows = {r['filename']: r for r in store().rows() if r['access'] == 'public_snapshot'}
    for item in items:
        row = rows.get(item.get('filename') or item.get('original_filename'))
        if row:
            item['raw_id'] = row['id']
            links = visible_links(row)
            item['record_links'] = links
            confirmed = next(iter(links), None)
            item['record_id'] = confirmed['record_id'] if confirmed else None
            item['record_url'] = confirmed['record_url'] if confirmed else None
            item['package_url'] = confirmed['package_url'] if confirmed else None
            if confirmed:
                item['record_id'] = confirmed['record_id']
                item['record_url'] = confirmed['record_url']
                item['package_url'] = confirmed['package_url']
    return items


def register_links(bp):
    @bp.after_request
    def private_data(response):
        # Cookies/permission can change both content and membership; never cache
        # administrative previews or association payloads in shared caches.
        if request.endpoint and (request.endpoint.startswith('argiloteca_scientific.drx_') or
                                 request.path.startswith('/api/argiloteca/analises/')):
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
        return response

    @bp.route('/scientific/drx/records/<pid>', endpoint='drx_record_package')
    def package(pid):
        try:
            return jsonify(record_package(pid, request.args, private=can_review()))
        except ValueError:
            abort(400)

    @bp.route('/scientific/drx/raws/<raw_id>/download', endpoint='drx_raw_download')
    def download(raw_id):
        row = allowed_row(raw_id)
        response = send_file(BytesIO(store().content(row)), download_name=row['filename'],
                             as_attachment=True, mimetype='application/octet-stream')
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    @bp.route('/scientific/drx/raws/<raw_id>/links', endpoint='drx_raw_links')
    def links(raw_id):
        row = allowed_row(raw_id)
        return jsonify({'links': visible_links(row, include_pending=can_review())})

    @bp.route('/scientific/drx/related-records', endpoint='drx_related_records')
    def related_records():
        from .admin_raw_store import ITEM_ID
        identifiers = list(dict.fromkeys((request.args.get('raw_ids') or '').split(',')))
        if not identifiers or len(identifiers) > 20 or any(not ITEM_ID.fullmatch(i) for i in identifiers):
            abort(400)
        items = []
        for raw_id in identifiers:
            row = allowed_row(raw_id)
            items.append({'raw_id': raw_id, 'filename': row['filename'],
                          'record_links': visible_links(row, include_pending=can_review())})
        return jsonify({'items': items, 'source': 'persisted_record_links'})

    @bp.route('/administration/drx-links/', endpoint='drx_link_admin', methods=['GET', 'POST'])
    @admin_only
    def administration():
        error = None
        status = 200
        if request.method == 'POST':
            try:
                row = store().get(request.form.get('raw_id', ''))
                pid = request.form.get('record_id', '').strip()
                set_link(g.identity, row, pid, state=request.form.get('state'),
                    evidence=request.form.get('evidence', ''),
                    expected_revision=int(request.form.get('revision', '0')), actor=g.identity.id)
                native = sync_metadata(g.identity, pid, {r['id']: r for r in store().rows()})
                db.session.commit()
                service.indexer.index(native)
                return redirect(url_for('.drx_link_admin', record_id=pid, raw_id=row['id'], saved=1), code=303)
            except ValueError as exc:
                db.session.rollback()
                error = str(exc)
                status = 409 if error in {'link_revision_conflict', 'raw_integrity_conflict'} else 422
            except KeyError:
                db.session.rollback()
                error, status = 'raw_not_found', 404
            except Exception:
                db.session.rollback()
                raise
        pid = (request.values.get('record_id') or '').strip()
        raw_id = (request.values.get('raw_id') or '').strip()
        query = DRXRecordLink.query
        if pid:
            query = query.filter_by(record_id=pid)
        if raw_id:
            query = query.filter_by(raw_id=raw_id)
        page = max(1, request.args.get('page', 1, type=int))
        total = query.count()
        links = query.order_by(DRXRecordLink.record_id, DRXRecordLink.raw_id).offset((page-1)*25).limit(25).all()
        rows = {r['id']: r for r in store().rows()}
        selected = rows.get(raw_id)
        current = DRXRecordLink.query.filter_by(record_id=pid, raw_id=raw_id).one_or_none() if pid and raw_id else None
        return render_template('semantic-ui/argiloteca/admin_drx_links.html',
            links=links, raw_rows=rows, record_id=pid, raw_id=raw_id, selected=selected,
            current=current, page=page, total=total, csrf_token=generate_csrf(), error=error), status
