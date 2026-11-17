"""Publication controls on the existing administration/CSRF-protected blueprint."""
from copy import deepcopy
import csv
import io
import json

from flask import abort, current_app, jsonify, redirect, render_template, request, send_file, stream_with_context, url_for
from flask_login import current_user
from invenio_db import db
from sqlalchemy.orm import defer

from ..openalex.adapters import digest
from ..openalex.models import OpenAlexJob
from ..openalex.publication import BATCH_SIZES, backup_path, publication_summary, sha256_file
from ..openalex.service import job_lock
from .views import blueprint, enqueue, get_job, t

KINDS = {'pan_publish_scan', 'pan_publish'}


@blueprint.get('/publication/')
def publication_index():
    sources = OpenAlexJob.query.filter(OpenAlexJob.kind.in_(['pan_prepare', 'pan_import']),
        OpenAlexJob.state.in_(['review', 'completed'])).options(defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(100).all()
    preparations = OpenAlexJob.query.filter_by(kind='pan_prepare', state='review').options(
        defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(20).all()
    sources = list({job.id: job for job in [*preparations, *sources]}.values())
    jobs = OpenAlexJob.query.filter(OpenAlexJob.kind.in_(KINDS)).options(defer(OpenAlexJob.snapshot)).order_by(OpenAlexJob.created.desc()).limit(20).all()
    return render_template('semantic-ui/argiloteca/admin_pangaea_publication.html',
        title=t('Publicação PANGAEA em lote', 'Bulk PANGAEA publication'), sources=sources,
        jobs=jobs, job=None, rows=[], busy=False)


@blueprint.post('/jobs/<job_id>/publication/preview')
def publication_preview(job_id):
    source = get_job(job_id)
    if source.kind not in {'pan_prepare', 'pan_import'} or source.state not in {'review', 'completed'}:
        abort(409)
    try:
        size = int(request.form.get('batch_size', 100))
    except ValueError:
        abort(400)
    if size not in BATCH_SIZES:
        abort(400)
    return enqueue(OpenAlexJob(kind='pan_publish_scan', actor=int(current_user.id),
        params={'source_job': source.id, 'batch_size': size}))


@blueprint.post('/publication/preview')
def publication_select_source():
    return publication_preview(request.form.get('source_job', ''))


@blueprint.get('/publication/jobs/<job_id>')
def publication_detail(job_id):
    job = get_job(job_id)
    if job.kind not in KINDS:
        abort(404)
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        abort(400)
    q = request.args.get('q', '').strip()[:200]
    status = request.args.get('status', '')
    applied = OpenAlexJob.query.filter_by(kind='pan_publish').filter(
        OpenAlexJob.params['preview_job'].as_string() == job.id).options(
        defer(OpenAlexJob.snapshot)).first() if job.kind == 'pan_publish_scan' else None
    outcomes = job.result.get('items', {})
    if applied:
        outcomes = applied.result.get('items', {})
    records = job.snapshot.get('records', [])
    filtered = [r for r in records if (not q or q.casefold() in json.dumps(
        [r['title'], r['identity'], r['id']], ensure_ascii=False).casefold()) and
        (not status or outcomes.get(r['key'], {}).get('state', r['status']) == status)]
    pages = max(1, (len(filtered) + 19) // 20)
    page = min(page, pages)
    return render_template('semantic-ui/argiloteca/admin_pangaea_publication.html',
        title=t('Publicação PANGAEA em lote', 'Bulk PANGAEA publication'), job=job,
        rows=filtered[(page-1)*20:page*20], total=len(filtered), page=page, pages=pages,
        q=q, status=status, outcomes=outcomes, summary=publication_summary(records, outcomes),
        busy=job.state in {'queued', 'running'}, applied=applied)


@blueprint.post('/publication/jobs/<job_id>/apply')
def publication_apply(job_id):
    source = get_job(job_id)
    if source.kind != 'pan_publish_scan' or source.actor != int(current_user.id):
        abort(403)
    if request.form.get('confirm') != 'yes' or request.form.get('plan_sha256') != digest(source.snapshot):
        abort(409)
    with job_lock('publication-apply-' + source.id) as locked:
        if not locked:
            abort(409)
        prior = OpenAlexJob.query.filter_by(kind='pan_publish').filter(
            OpenAlexJob.params['preview_job'].as_string() == source.id).first()
        if prior:
            return redirect(url_for('.publication_detail', job_id=prior.id), code=303)
        if source.state != 'review':
            abort(409)
        records = [deepcopy(r) for r in source.snapshot['records'] if r['status'] == 'ready']
        if not records:
            abort(409, description=t('Nenhum rascunho está apto para publicação.', 'No draft is ready for publication.'))
        snapshot = {**deepcopy(source.snapshot), 'records': records,
                    'source_summary': deepcopy(source.snapshot['summary']), 'summary': publication_summary(records)}
        return enqueue(OpenAlexJob(kind='pan_publish', actor=int(current_user.id), snapshot=snapshot,
            params={'source_job': source.params['source_job'], 'preview_job': source.id,
                    'batch_size': snapshot['batch_size'], 'plan_sha256': digest(snapshot)}))


@blueprint.get('/publication/jobs/<job_id>/backups/<int:number>')
def publication_backup(job_id, number):
    job = get_job(job_id)
    saved = job.result.get('backups', {}).get(str(number))
    if job.kind != 'pan_publish' or not saved:
        abort(404)
    path = backup_path(job.id, number)
    if not path.is_file() or path.is_symlink() or sha256_file(path) != saved['sha256']:
        abort(409)
    return send_file(path, as_attachment=True, mimetype='application/zip',
        download_name=f'pangaea-publicacao-{job.id}-{number}.zip', max_age=0)


@blueprint.get('/publication/jobs/<job_id>/report.<format>')
def publication_report(job_id, format):
    job = get_job(job_id)
    if job.kind not in KINDS:
        abort(404)
    if format == 'json':
        response = jsonify(id=job.id, kind=job.kind, state=job.state, params=job.params, snapshot=job.snapshot, result=job.result)
    elif format == 'csv':
        def rows():
            stream = io.StringIO(); writer = csv.writer(stream)
            writer.writerow(['id', 'title', 'doi', 'openalex', 'status', 'message'])
            yield '\ufeff' + stream.getvalue()
            for row in job.snapshot.get('records', []):
                outcome = job.result.get('items', {}).get(row['key'], {})
                values = [row['id'], row['title'], row['identity'].get('doi', ''), row['identity'].get('openalex_id', ''),
                          outcome.get('state', row['status']), outcome.get('message', '; '.join(row.get('issues', [])))]
                stream.seek(0); stream.truncate()
                writer.writerow(["'"+str(v) if str(v).startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
                yield stream.getvalue()
        response = current_app.response_class(stream_with_context(rows()), mimetype='text/csv')
    else:
        abort(404)
    response.headers['Content-Disposition'] = f'attachment; filename="pangaea-publicacao-{job.id}.{format}"'
    return response
