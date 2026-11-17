"""Private integrated administration; all mutations use the existing durable journal."""
from datetime import datetime, timezone
import csv
import io
import json
import math
import re
from urllib.parse import urlencode

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, Response, url_for
from flask_login import current_user
from invenio_db import db
from sqlalchemy.orm import defer

from ..openalex.adapters import digest
from ..openalex.analytics import connect
from ..openalex.analytics_views import view_store
from ..openalex.models import OpenAlexJob
from ..openalex.orcid import normalize_orcid
from ..openalex.service import job_lock
from ..openalex.views import protect, private, context, preserve_language, t
from .queries import listing, summary, source_summary
from .snapshot import SOURCES, PREPARE

blueprint = Blueprint('argiloteca_population', __name__, url_prefix='/administration/povoamento')
blueprint.before_request(protect)
blueprint.after_request(private)
blueprint.context_processor(context)
blueprint.url_defaults(preserve_language)


def analysis():
    aid = request.values.get('analysis', '')
    query = OpenAlexJob.query.filter_by(kind='stats_scan', state='completed')
    if aid:
        if not re.fullmatch('[a-f0-9]{32}', aid): abort(404)
        job = query.filter_by(id=aid).first()
        if not job or not job.snapshot.get('population'): abort(409, description=t('Atualize o retrato integrado.', 'Refresh the integrated snapshot.'))
        return job
    return query.filter(OpenAlexJob.snapshot['population'].isnot(None)).order_by(OpenAlexJob.created.desc()).first()


def filters():
    source = request.args.get('source', ''); stage = request.args.get('stage', ''); status = request.args.get('status', '')
    if source and source not in SOURCES: abort(400)
    if stage not in ('', 'published', 'draft', 'editing', 'recovered'): abort(400)
    if status not in ('', 'linked', 'missing', 'conflict', 'suggested'): abort(400)
    try: year = int(request.args['year']) if request.args.get('year') else None
    except ValueError: abort(400)
    if year is not None and not 1 <= year <= 9999: abort(400)
    return {'source': source, 'stage': stage, 'q': request.args.get('q', '')[:150].strip(), 'status': status, 'year': year}


def job_url(job):
    if job.kind == 'pop_orcid_preview': return url_for('.job_detail', job_id=job.id)
    return url_for('argiloteca_openalex.job_detail', job_id=job.id)


def dispatch(job):
    db.session.add(job); db.session.commit()
    from ..openalex.tasks import run
    try: run.delay(job.id)
    except Exception: current_app.logger.warning('Population job pending journal recovery: %s', job.id)
    return redirect(job_url(job), code=303)


def render(section):
    job = analysis(); selected = filters(); data = None; rows = []; total = 0; pages = 1
    try: page = int(request.args.get('page', 1))
    except ValueError: abort(400)
    if page < 1: abort(400)
    sources = []; warnings = []; pdfs = 0; lots = []
    if job:
        with view_store(job) as c:
            data = summary(c, selected); sources = source_summary(c)
            warnings = [dict(r) for r in c.execute('SELECT * FROM p_warnings')]
            lots = [{**dict(r), 'scope':json.loads(r['coverage'])} for r in c.execute('SELECT * FROM p_lots ORDER BY source,lot DESC')]
            pdfs = c.execute('SELECT count(*) FROM p_pdfs').fetchone()[0]
            if section != 'overview':
                _, total = listing(c, selected, section == 'authors', limit=0)
                pages = max(1, math.ceil(total / 25)); page = min(page, pages)
                rows, _ = listing(c, selected, section == 'authors', offset=(page-1)*25)
    for source in sources:
        if source['id']=='unknown': source['label']=t('Sem fonte identificada','Unidentified source')
        kind = {'openalex':'extract','pangaea':'pan_extract','mendeley':'men_extract','lume':'oai_extract','ufsc':'oai_extract'}.get(source['id'])
        last = None
        if kind:
            query = OpenAlexJob.query.filter_by(kind=kind)
            if source['id'] in ('lume','ufsc'):
                query = query.filter(OpenAlexJob.params['repository'].as_string()==source['id'])
            last = query.options(defer(OpenAlexJob.snapshot),defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).first()
        source['latest'] = last
    busy = OpenAlexJob.query.filter_by(kind='stats_scan').filter(OpenAlexJob.state.in_(['queued', 'running'])).first()
    recent = OpenAlexJob.query.options(defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(12).all()
    quality = {kind: OpenAlexJob.query.options(defer(OpenAlexJob.snapshot)).filter(OpenAlexJob.kind==kind,OpenAlexJob.state.in_(['review','completed'])).order_by(OpenAlexJob.created.desc()).first() for kind in ('manual_scan','dedup_scan')}

    # Tasks are live; record counts come exclusively from the dated snapshot.
    return render_template('semantic-ui/argiloteca/admin_population.html', title=t('Povoamento integrado', 'Integrated population'),
                           section=section, analysis=job, data=data, rows=rows, total=total, page=page, pages=pages,
                           sources=sources, source_names={**SOURCES,'unknown':t('Sem fonte identificada','Unidentified source')}, filters=selected, warnings=warnings, lots=lots,
                           pdfs=pdfs, recent=recent, busy=busy, job_url=job_url, quality=quality,
                           page_link=lambda n: url_for('.'+('authors' if section == 'authors' else 'records'), analysis=job.id, page=n, **selected))


@blueprint.get('/')
def index(): return render('overview')


@blueprint.get('/records/')
def records(): return render('records')


@blueprint.get('/authors/')
def authors(): return render('authors')


@blueprint.post('/refresh')
def refresh():
    with job_lock('statistics-enqueue') as locked:
        if not locked: abort(409)
        prior = OpenAlexJob.query.filter_by(kind='stats_scan').filter(OpenAlexJob.state.in_(['queued', 'running'])).first()
        if prior: return redirect(job_url(prior), code=303)
        return dispatch(OpenAlexJob(kind='stats_scan', actor=int(current_user.id)))


@blueprint.get('/export.csv')
def export():
    job = analysis()
    if not job: abort(409)
    selected = filters(); authors = request.args.get('view') == 'authors'
    with view_store(job) as c:
        rows, count = listing(c, selected, authors, limit=100001)
    if count > 100000: abort(413, description=t('Refine os filtros para exportar até 100.000 linhas.', 'Refine filters to export up to 100,000 rows.'))
    fields = ['name', 'orcid', 'status', 'title', 'rid', 'kind', 'sources'] if authors else ['title', 'rid', 'kind', 'year', 'type', 'published', 'draft', 'conflict', 'sources']
    stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(['analysis', *fields])
    def safe(value):
        value = str(value if value is not None else '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value
    for row in rows: writer.writerow([job.id, *(safe(row.get(key)) for key in fields)])
    return Response('\ufeff'+stream.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename=povoamento-'+job.id+'.csv'})


@blueprint.get('/authors/<key>')
def author(key):
    if not re.fullmatch('[a-f0-9]{64}', key): abort(404)
    job = analysis()
    if not job: abort(404)
    with view_store(job) as c:
        row = c.execute('''SELECT a.*,r.title,r.rid,r.kind,r.review,r.conflict,r.row_key
                           FROM p_authors a JOIN p_records r ON r.id=a.record WHERE a.key=?''', (key,)).fetchone()
        if not row: abort(404)
        row = dict(row)
        if row['native_key']:
            return redirect(url_for('argiloteca_openalex.author_detail', gid=row['gid'], analysis=job.id), code=303)
        entries = [dict(r) for r in c.execute('SELECT source,lot,row_key,review,sha FROM p_entries WHERE record=? ORDER BY source,lot', (row['record'],))]
    search = None; options = []
    if row['status'] == 'linked': options = [{'orcid': row['orcid'], 'name': row['name'], 'method': t('Declarado na fonte', 'Declared by source')}]
    if request.args.get('search_job'):
        search = db.session.get(OpenAlexJob, request.args['search_job'])
        if not search or search.kind not in ('orcid_search', 'orcid_lookup') or search.params.get('population_key') != key or search.params.get('analysis') != job.id or search.actor != int(current_user.id): abort(404)
        if search.state == 'review': options = search.snapshot.get('candidates', [])
    return render_template('semantic-ui/argiloteca/admin_population_author.html', title=t('Autor recuperado e ORCID', 'Recovered author and ORCID'),
                           analysis=job, row=row, entries=entries, source_names=SOURCES, options=options, search=search,
                           registry_url='https://orcid.org/orcid-search/search?'+urlencode({'searchQuery': row['name']}))


@blueprint.post('/authors/<key>/search')
def search(key):
    job = analysis()
    if not job: abort(409)
    with view_store(job) as c:
        if not c.execute('SELECT 1 FROM p_authors WHERE key=?', (key,)).fetchone(): abort(404)
    params = {'analysis': job.id, 'population_key': key}
    value = request.form.get('orcid', '').strip()
    if value:
        value = normalize_orcid(value)
        if not value: abort(400)
        params['orcid'] = value; kind = 'orcid_lookup'
    else:
        for field in ('given', 'family', 'institution', 'doi'):
            value = request.form.get(field, '').strip()
            if len(value) > 250 or any(ord(x) < 32 for x in value): abort(400)
            params[field] = value
        if not params['given'] and not params['family']: abort(400)
        kind = 'orcid_search'
    return dispatch(OpenAlexJob(kind=kind, actor=int(current_user.id), params=params))


@blueprint.post('/authors/<key>/preview')
def preview(key):
    job = analysis(); value = normalize_orcid(request.form.get('orcid'))
    if not job or not value or not re.fullmatch('[a-f0-9]{64}', key): abort(400)
    return dispatch(OpenAlexJob(kind='pop_orcid_preview', actor=int(current_user.id),
                               params={'analysis': job.id, 'key': key, 'orcid': value, 'evidence_job': request.form.get('evidence_job', '')}))


@blueprint.get('/jobs/<job_id>')
def job_detail(job_id):
    job = db.session.get(OpenAlexJob, job_id)
    if not job or job.kind != 'pop_orcid_preview': abort(404)
    return render_template('semantic-ui/argiloteca/admin_population_orcid.html', title=t('Prévia ORCID do lote', 'Batch ORCID preview'), job=job)


@blueprint.post('/jobs/<job_id>/apply')
def apply(job_id):
    job = db.session.get(OpenAlexJob, job_id)
    if not job or job.actor != int(current_user.id): abort(403)
    if request.form.get('confirm') != 'yes' or request.form.get('plan_sha256') != digest(job.snapshot): abort(409)
    note = request.form.get('note', '').strip()
    if len(note) > 2000: abort(400)
    with job_lock('population-orcid-'+job.id) as locked:
        if not locked: abort(409)
        prior = OpenAlexJob.query.filter(OpenAlexJob.params['population_orcid_review']['preview'].as_string() == job.id).first()
        if prior: return redirect(job_url(prior), code=303)
        from .orcid import revised_job
        try: revised = revised_job(job, int(current_user.id), note)
        except ValueError as exc: abort(409, description=str(exc))
        return dispatch(revised)
