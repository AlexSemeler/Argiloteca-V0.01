"""Admin-only Repositórios OAI review, import and reports, with explicit CSRF checks."""
from copy import deepcopy
import csv
import io
import json
from types import SimpleNamespace
import time

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, stream_with_context, url_for
from flask_babel import get_locale
from flask_login import current_user
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from invenio_db import db
from sqlalchemy.orm import defer

from ..openalex.adapters import digest
from ..openalex.models import OpenAlexJob
from ..openalex.preview import iter_records, page_records
from ..openalex.service import job_lock
from ..openalex.views import admin_only, t, LABELS
from .client import parameters, REPOSITORIES
from .workflow import CORRECTABLE, root, terms, lots, lot_path

blueprint = Blueprint('argiloteca_repositories', __name__, url_prefix='/administration/repositories')
KINDS = {'oai_extract', 'oai_prepare', 'oai_import', 'oai_publish_scan', 'oai_publish', 'oai_pdf'}


@blueprint.before_request
@admin_only
def protect():
    if request.method == 'POST':
        if request.content_length and request.content_length > 1024 * 1024:
            abort(413)
        try:
            validate_csrf(request.form.get('csrf_token'))
        except ValidationError:
            abort(400, description=t('Sessão expirada. Recarregue a página.', 'Session expired. Reload the page.'))


@blueprint.after_request
def private(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@blueprint.context_processor
def context():
    return {'oa_locale': get_locale().language, 'oa_json': lambda value: json.dumps(value, ensure_ascii=False, indent=2),
            'oa_digest': digest, 'oa_t': t, 'oa_label': lambda value: t(*({'oai_pdf':('Download de PDFs','PDF download')}.get(value) or LABELS.get(value.removeprefix('oai_'), (value, value)))),
            'csrf_token': generate_csrf}


@blueprint.url_defaults
def preserve_language(endpoint, values):
    values.setdefault('ln', get_locale().language)


def get_job(job_id):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        abort(404)
    job = db.get_or_404(OpenAlexJob, job_id)
    if job.kind not in KINDS:
        abort(404)
    return job


def enqueue(job):
    db.session.add(job)
    db.session.commit()
    from ..openalex.tasks import run
    try:
        run.delay(job.id)
    except Exception:
        current_app.logger.warning('Repositórios OAI dispatch pending recovery: %s', job.id)
    return redirect(url_for('.job_detail', job_id=job.id), code=303)


@blueprint.get('/')
def index():
    error, available = None, []
    try:
        available = [{'id': row['id'], 'title': row.get('title', {}).get(get_locale().language, row['id'])} for row in terms()]
    except (ValueError, OSError) as exc:
        error = str(exc)
    heartbeat = root() / 'heartbeat.json'
    online = heartbeat.is_file() and time.time() - heartbeat.stat().st_mtime < 60
    return render_template('semantic-ui/argiloteca/admin_repositories.html', title=t('Importação de repositórios', 'Repository import'),
        available_terms=available, repositories=REPOSITORIES, selected_repository=request.args.get('repository') if request.args.get('repository') in REPOSITORIES else 'lume', catalogues=catalogues(), lots=lots(), setup_error=error, online=online,
        jobs=OpenAlexJob.query.filter(OpenAlexJob.kind.in_(KINDS),OpenAlexJob.params['admin_archived'].as_boolean().isnot(True)).options(defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(50).all())


@blueprint.post('/extract')
def extract():
    try:
        form = request.form.to_dict()
        if not form.get('set_spec', '').strip():
            form.pop('set_spec', None)
        params = parameters(form, terms())
        heartbeat = root() / 'heartbeat.json'
        if not heartbeat.is_file() or time.time() - heartbeat.stat().st_mtime > 60:
            raise ValueError('O agente local de repositórios está offline. Inicie scripts/repositories-local-agent.py.')
    except (ValueError, OSError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.index'), code=303)
    return enqueue(OpenAlexJob(kind='oai_extract', actor=int(current_user.id), params=params))


@blueprint.post('/prepare')
def prepare_lot():
    try:
        name = request.form.get('lot', '')
        lot_path(root(), name)
        limit = int(request.form.get('limit', 0))
        if not 0 <= limit <= 8100 or not any(l['name'] == name and l['complete'] and l['count'] for l in lots()):
            raise ValueError('Selecione um lote concluído e um limite válido.')
    except (ValueError, OSError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.index'), code=303)
    return enqueue(OpenAlexJob(kind='oai_prepare', actor=int(current_user.id), params={'lot': name, 'limit': limit}))


@blueprint.get('/jobs/<job_id>')
def job_detail(job_id):
    job = get_job(job_id)
    if job.kind == 'oai_pdf':
        return redirect(url_for('.pdf_detail',job_id=job.id),code=303)
    if job.kind in {'oai_publish_scan', 'oai_publish'}:
        return redirect(url_for('.publication_detail', job_id=job.id), code=303)
    q, status = request.args.get('q', '').strip()[:200], request.args.get('status', '')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        abort(400)
    rows, total, page, pages = page_records(job.snapshot, q, status, page)
    key = request.args.get('record')
    detail = next(iter_records(job.snapshot, [key]), None) if key else None
    display = SimpleNamespace(**{k: getattr(job, k) for k in ('id', 'state', 'actor', 'params', 'result', 'created', 'updated')},
        kind=job.kind.removeprefix('oai_'), snapshot={**job.snapshot, 'records': bool(job.snapshot.get('record_store', {}).get('count') or job.snapshot.get('records'))})
    published_ids = set()
    ids = {str(value['draft_id']) for value in job.result.get('items', {}).values() if value.get('draft_id')}
    if ids:
        from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
        drafts = {rid for (rid,) in db.session.query(RDMDraftMetadata.json['id'].as_string()).filter(RDMDraftMetadata.json['id'].as_string().in_(ids))}
        published_ids = {rid for (rid,) in db.session.query(RDMRecordMetadata.json['id'].as_string()).filter(RDMRecordMetadata.deletion_status == 'P', RDMRecordMetadata.json['id'].as_string().in_(ids))} - drafts
    return render_template('semantic-ui/argiloteca/admin_repositories_job.html', title=t('Revisão de repositórios', 'Repository review'),
        job=display, rows=rows, total=total, page=page, pages=pages, q=q, status=status,
        counts={state: job.snapshot.get('summary', {}).get(state, 0) for state in ('apto', 'apto_com_alertas', 'bloqueado')},
        detail=detail, outcomes=job.result.get('items', {}), published_ids=published_ids,
        busy=job.state in {'queued', 'running', 'waiting_host'})


@blueprint.post('/jobs/<job_id>/correct')
def correct(job_id):
    job = get_job(job_id)
    if job.kind != 'oai_prepare' or job.state != 'review':
        abort(409)
    row = next(iter_records(job.snapshot, [request.form.get('record')]), None)
    if not row:
        abort(404)
    try:
        patch = json.loads(request.form.get('corrections', '{}'))
        if not isinstance(patch, dict) or not patch or set(patch) - CORRECTABLE:
            raise ValueError('Informe somente campos descritivos permitidos em um objeto JSON.')
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.job_detail', job_id=job.id, record=row['key']), code=303)
    corrections = deepcopy(job.params.get('corrections', {}))
    corrections[row['key']] = {**corrections.get(row['key'], {}), **patch}
    return enqueue(OpenAlexJob(kind='oai_prepare', actor=int(current_user.id), params={**job.params, 'previous_job': job.id, 'corrections': corrections}))


@blueprint.post('/jobs/<job_id>/import')
def import_selected(job_id):
    source = get_job(job_id)
    if source.kind != 'oai_prepare' or source.state != 'review':
        abort(409)
    selected = sorted(set(request.form.getlist('selected')))
    if not selected or len(selected) > 20 or request.form.get('confirm') != 'yes':
        abort(400)
    rows = list(iter_records(source.snapshot, selected))
    if set(selected) != {row['key'] for row in rows if row['status'] != 'bloqueado'}:
        abort(409)
    communities = {}
    for row in rows:
        destinations = sorted(set(request.form.getlist('community:' + row['key'])))
        if set(destinations) - {c['id'] for c in row.get('classification', {}).get('communities', [])}:
            abort(409)
        communities[row['key']] = destinations
    signature = digest({'source': source.id, 'selected': selected, 'communities': communities, 'actor': int(current_user.id)})
    with job_lock('repositories-import-' + signature) as locked:
        if not locked:
            abort(409)
        prior = OpenAlexJob.query.filter_by(kind='oai_import', actor=int(current_user.id)).filter(OpenAlexJob.params['signature'].as_string() == signature).first()
        if prior:
            return redirect(url_for('.job_detail', job_id=prior.id), code=303)
        snapshot = deepcopy({k: v for k, v in source.snapshot.items() if k not in ('records', 'record_store')})
        snapshot['records'] = rows
        return enqueue(OpenAlexJob(kind='oai_import', actor=int(current_user.id), snapshot=snapshot,
            params={'selected': selected, 'source_job': source.id, 'signature': signature, 'communities': communities}))


@blueprint.post('/jobs/<job_id>/resume')
def resume(job_id):
    job = get_job(job_id)
    if job.state != 'failed' or job.actor != int(current_user.id):
        abort(409)
    if job.kind == 'oai_extract':
        return enqueue(OpenAlexJob(kind='oai_extract', actor=job.actor,
            params={**job.params, 'previous_job': job.id, 'collection_id': job.params.get('collection_id', job.id)}))
    job.state = 'queued'
    job.result = {k: v for k, v in job.result.items() if k != 'error'}
    return enqueue(job)


@blueprint.get('/jobs/<job_id>/report.<format>')
def report(job_id, format):
    job = get_job(job_id)
    if job.kind in {'oai_publish_scan', 'oai_publish'}:
        return redirect(url_for('.publication_report', job_id=job.id, format=format), code=303)
    if format == 'json':
        header = {'id': job.id, 'kind': job.kind, 'state': job.state, 'actor': job.actor,
                  'created': job.created.isoformat(), 'updated': job.updated.isoformat(),
                  'params': job.params, 'result': job.result}
        def json_report():
            yield json.dumps(header, ensure_ascii=False)[:-1] + ',"snapshot":{'
            for key, value in job.snapshot.items():
                if key != 'records':
                    yield json.dumps(key) + ':' + json.dumps(value, ensure_ascii=False) + ','
            yield '"records":['
            separator = ''
            for row in iter_records(job.snapshot):
                yield separator + json.dumps(row, ensure_ascii=False)
                separator = ','
            yield ']}}'
        response = current_app.response_class(stream_with_context(json_report()), mimetype='application/json')
    elif format == 'csv':
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['key', 'doi', 'handle', 'title', 'status', 'record_id', 'outcome', 'issues'])
        for row in iter_records(job.snapshot):
            outcome = job.result.get('items', {}).get(row['key'], {})
            values = [row['key'], row['identity']['doi'], row['identity']['handle'], row['payload']['metadata']['title'], row['status'],
                      outcome.get('draft_id', ''), outcome.get('state', ''), json.dumps(row['issues'], ensure_ascii=False)]
            writer.writerow(["'" + str(v) if str(v).startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
        response = current_app.response_class('\ufeff' + stream.getvalue(), mimetype='text/csv')
    else:
        abort(404)
    response.headers['Content-Disposition'] = f'attachment; filename="repositories-{job.id}.{format}"'
    return response


@blueprint.post('/jobs/<job_id>/continue')
def continue_collection(job_id):
    source=get_job(job_id)
    if source.kind!='oai_extract' or source.state!='completed': abort(409)
    if not source.result.get('coverage') or source.result['coverage'].get('complete'): abort(409)
    params={**parameters(source.params,terms()),'previous_job':source.id}
    if not params['max_pages']: params['max_pages']=10
    return enqueue(OpenAlexJob(kind='oai_extract',actor=int(current_user.id),params=params))


def catalogues():
    results=[]
    for path in (root()/'catalogues').glob('*/status.json'):
        try:
            status=__import__('json').loads(path.read_text())
            results.append(status)
        except (ValueError,OSError): continue
    return sorted(results,key=lambda s:(s['scope']['repository'],s['scope']['catalog_cycle']),reverse=False)
