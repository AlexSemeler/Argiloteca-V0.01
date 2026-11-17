"""Administration-only OpenAlex workflow; all mutations are CSRF protected."""
from copy import deepcopy
from functools import wraps
import csv
import io
import json
from pathlib import Path
from types import SimpleNamespace

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for, send_file, stream_with_context
from flask_babel import get_locale
from flask_login import current_user
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from invenio_db import db
from sqlalchemy.orm import defer

from .adapters import digest, extraction_parameters, lots, lot_path, terms
from .models import OpenAlexJob
from .preview import iter_records, page_records

blueprint = Blueprint('argiloteca_openalex', __name__, url_prefix='/administration/openalex')
LABELS = {
    'waiting_api': ('Aguardando a API','Waiting for API'),
    'queued': ('Na fila', 'Queued'), 'running': ('Em processamento', 'Running'),
    'waiting_host': ('Coleta no Mac', 'Collecting on Mac'), 'review': ('Pronto para revisão', 'Ready for review'),
    'completed': ('Concluído', 'Completed'), 'failed': ('Falha — pode retomar', 'Failed — resumable'),
    'prepare': ('Preparação', 'Preparation'), 'extract': ('Extração', 'Extraction'), 'import': ('Importação', 'Import'),
    'apto': ('Apto', 'Ready'), 'apto_com_alertas': ('Apto com alertas', 'Ready with warnings'),
    'bloqueado': ('Bloqueado', 'Blocked'), 'created': ('Rascunho criado', 'Draft created'),
    'duplicate': ('Já existe', 'Already exists'),
    'updated': ('Metadados atualizados', 'Metadata updated')}
LABELS.update({'manual_scan':('Verificação de classificação','Classification scan'),
    'stats_scan':('Estatísticas e autores','Statistics and authors'),
    'orcid_search':('Busca no ORCID','ORCID search'),
    'orcid_lookup':('Consulta do perfil ORCID','ORCID profile lookup'),
    'orcid_preview':('Prévia de vinculação ORCID','ORCID association preview'),
    'orcid_apply':('Vinculação ORCID','ORCID association'),
    'publish_scan':('Prévia de publicação','Publication preview'),
    'publish':('Publicação em lote','Bulk publication'),
    'ready':('Apto para publicar','Ready to publish'),
    'published':('Publicado','Published'),
    'already_published':('Já publicado','Already published'),
    'blocked':('Bloqueado','Blocked'),
    'manual_preview':('Prévia da associação manual','Manual association preview'),
    'manual_apply':('Associação manual de comunidades','Manual community association'),
    'classify_existing':('Classificação do acervo','Collection classification'),
    'dedup_scan':('Verificação de duplicados','Duplicate scan'),
    'dedup_preview':('Prévia da consolidação','Consolidation preview'),
    'dedup_merge':('Consolidação de duplicados','Duplicate consolidation'),
    'keep':('Manter','Keep'),'copy':('Acrescentar','Add'),
    'rename':('Preservar com outro nome','Keep with another name'),
    'same_content':('Conteúdo já presente','Content already present')})


def t(pt, en):
    return pt if get_locale().language == 'pt' else en


def admin_only(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from ..scientific.restricted_review import can_review
        if not can_review():
            abort(403)
        return function(*args, **kwargs)
    return wrapped


@blueprint.before_request
@admin_only
def protect():
    if request.method == 'POST':
        if request.content_length and request.content_length > 1024*1024:
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
    return {'oa_locale': get_locale().language, 'oa_json': lambda value: json.dumps(value, ensure_ascii=False, indent=2), 'oa_digest':digest, 'oa_t': t, 'oa_label': lambda value: t(*LABELS.get(value, (value, value))), 'csrf_token': generate_csrf}


@blueprint.url_defaults
def preserve_language(endpoint, values):
    values.setdefault('ln', get_locale().language)


def root():
    return current_app.config['ARGILOTECA_OPENALEX_ROOT']


def get_job(job_id):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        abort(404)
    return db.get_or_404(OpenAlexJob, job_id)


def enqueue(job):
    db.session.add(job)
    db.session.commit()
    from .tasks import run
    try:
        run.delay(job.id)
    except Exception:
        current_app.logger.warning('OpenAlex dispatch pending recovery: %s', job.id)
    # This helper is also called by the maintenance blueprint. Resolve the
    # shared dispatcher explicitly instead of using the caller's blueprint.
    return redirect(url_for('argiloteca_openalex.job_detail', job_id=job.id), code=303)


@blueprint.get('/')
def index():
    error, available = None, []
    try:
        available = terms(root())
    except (ValueError, OSError) as exc:
        error = str(exc)
    return render_template('semantic-ui/argiloteca/admin_openalex.html',
        title=t('Importação OpenAlex', 'OpenAlex import'), available_terms=available,
        lots=lots(root()), jobs=OpenAlexJob.query.filter(OpenAlexJob.params['admin_archived'].as_boolean().isnot(True),~OpenAlexJob.kind.like('clean_%'), ~OpenAlexJob.kind.like('pan_%'), ~OpenAlexJob.kind.like('men_%'), ~OpenAlexJob.kind.like('oai_%')).options(defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(50).all(),
        setup_error=error)


@blueprint.post('/extract')
def extract():
    try:
        params = extraction_parameters(request.form, terms(root()))
        queue = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])
        heartbeat = queue / 'heartbeat.json'
        from .adapters import read_json
        import time
        if not heartbeat.exists() or time.time()-heartbeat.stat().st_mtime > 30:
            raise ValueError('O agente de extração do Mac está offline. Inicie-o conforme o guia local.')
        read_json(heartbeat, queue)
    except (OSError, ValueError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.index'), code=303)
    return enqueue(OpenAlexJob(kind='extract', actor=int(current_user.id), params=params))


@blueprint.post('/prepare')
def prepare_lot():
    try:
        name = request.form.get('lot', '')
        lot_path(root(), name)
        limit = int(request.form.get('limit', 0))
        if not 0 <= limit <= 10000 or not any(l['name'] == name and l['complete'] and l['count'] for l in lots(root())):
            raise ValueError('Selecione um lote concluído e um limite válido.')
    except (ValueError, OSError) as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.index'), code=303)
    return enqueue(OpenAlexJob(kind='prepare', actor=int(current_user.id), params={'lot': name, 'limit': limit}))


@blueprint.get('/jobs/<job_id>')
def job_detail(job_id):
    job = get_job(job_id)
    if job.kind == 'pop_orcid_preview':
        return redirect(url_for('argiloteca_population.job_detail',job_id=job.id),code=303)
    if job.kind.startswith('oai_'):
        return redirect(url_for('argiloteca_repositories.job_detail', job_id=job.id), code=303)
    if job.kind.startswith('men_'):
        return redirect(url_for('argiloteca_mendeley.job_detail', job_id=job.id), code=303)
    if job.kind.startswith('pan_'):
        return redirect(url_for('argiloteca_pangaea.job_detail', job_id=job.id), code=303)
    if job.kind.startswith('enrich_'):
        return redirect(url_for('.enrichment_detail',job_id=job.id),code=303)
    if job.kind in {'stats_scan','orcid_search','orcid_lookup','orcid_preview','orcid_apply'}:
        return redirect(url_for('.orcid_job',job_id=job.id),code=303)
    if job.kind in {'publish_scan', 'publish'}:
        return redirect(url_for('.publication_detail', job_id=job.id), code=303)
    if job.kind=='clean_bulk_preview':
        return redirect(url_for('argiloteca_maintenance.bulk_detail',job_id=job.id),code=303)
    if job.kind.startswith('clean_'):
        return redirect(url_for('argiloteca_maintenance.detail',job_id=job.id),code=303)
    if job.kind.startswith('manual_'):
        return redirect(url_for('.manual_detail',job_id=job.id),code=303)
    if job.kind.startswith('dedup_'):
        return redirect(url_for('.duplicates_detail',job_id=job.id),code=303)
    q, state = request.args.get('q', '').strip()[:200], request.args.get('status', '')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        abort(400)
    rows, total, page, pages = page_records(job.snapshot, q, state, page)
    counts = job.snapshot.get('summary', {}) if job.snapshot.get('record_store') else {status: sum(r['status'] == status for r in job.snapshot.get('records', [])) for status in ('apto', 'apto_com_alertas', 'bloqueado')}
    record_key = request.args.get('record')
    detail = next(iter_records(job.snapshot, [record_key]), None) if record_key else None
    display = job
    if job.snapshot.get('record_store'):
        # Keep the existing template/controls; only its current page is loaded.
        display = SimpleNamespace(**{key: getattr(job, key) for key in ('id','kind','state','actor','params','result','created','updated')}, snapshot={**job.snapshot, 'records': bool(job.snapshot['record_store']['count'])})
    published_ids = set()
    ids = {str(v.get('draft_id')) for row in rows if (v := job.result.get('items', {}).get(row['key'], {})).get('draft_id')}
    if ids:
        from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
        active_drafts = {rid for (rid,) in db.session.query(RDMDraftMetadata.json['id'].as_string()).filter(
            RDMDraftMetadata.json['id'].as_string().in_(ids))}
        published_ids = {rid for (rid,) in db.session.query(RDMRecordMetadata.json['id'].as_string()).filter(
            RDMRecordMetadata.deletion_status == 'P', RDMRecordMetadata.json['id'].as_string().in_(ids))} - active_drafts
    return render_template('semantic-ui/argiloteca/admin_openalex_job.html',
        title=t('Revisão e histórico OpenAlex', 'OpenAlex review and history'), job=display,
        rows=rows, total=total, page=page, pages=pages,
        q=q, status=state, counts=counts, detail=detail,
        outcomes=job.result.get('items', {}), published_ids=published_ids,
        busy=job.state in ('queued', 'running', 'waiting_host'))


@blueprint.post('/jobs/<job_id>/correct')
def correct(job_id):
    job = get_job(job_id)
    if job.kind != 'prepare' or job.state != 'review':
        abort(409)
    row = next(iter_records(job.snapshot, [request.form.get('record')]), None)
    if not row:
        abort(404)
    try:
        patch = json.loads(request.form.get('corrections', '{}'))
        if not isinstance(patch, dict) or not patch:
            raise ValueError('Informe um objeto JSON com os campos descritivos corrigidos.')
        corrections = deepcopy(job.snapshot.get('corrections', {}))
        for source in row['provenance']:
            key = source['origin']['key']
            corrections[key] = {**corrections.get(key, {}), **patch}
        # Validate field names without reprocessing the whole lot inside HTTP.
        allowed = {'creators', 'title', 'publication_date', 'resource_type', 'description', 'languages', 'rights', 'subjects', 'publisher', 'contributors', 'additional_titles', 'additional_descriptions', 'dates', 'version', 'sizes', 'formats', 'references', 'funding', 'locations'}
        if set(patch)-allowed:
            raise ValueError('Campo não permitido. Identidade e acesso não podem ser alterados nesta revisão.')
    except ValueError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('.job_detail', job_id=job_id, record=row['key']), code=303)
    return enqueue(OpenAlexJob(kind='prepare', actor=int(current_user.id), params={
        **job.params, 'corrections': corrections, 'previous_job': job.id}))


@blueprint.post('/jobs/<job_id>/import')
def import_selected(job_id):
    job = get_job(job_id)
    if job.kind != 'prepare' or job.state != 'review':
        abort(409)
    selected = sorted(set(request.form.getlist('selected')))
    if len(selected) > 100:
        abort(400, description=t('Selecione até 100 registros por importação.', 'Select up to 100 records per import.'))
    selected_rows = list(iter_records(job.snapshot, selected)) if selected else []
    eligible = {r['key'] for r in selected_rows if r['status'] != 'bloqueado'}
    if not selected or set(selected)-eligible or request.form.get('confirm') != 'yes':
        flash(t('Selecione registros aptos e confirme a importação e atualização dos existentes.', 'Select ready records and confirm import and updates to existing records.'), 'error')
        return redirect(url_for('.job_detail', job_id=job.id), code=303)
    communities = {}
    for row in selected_rows:
        targets = sorted(set(request.form.getlist('community:'+row['key'])))
        eligible_communities = {c['id'] for c in row.get('classification',{}).get('communities',[])}
        if set(targets)-eligible_communities:
            abort(409,description=t('Comunidade fora da classificação revisada.', 'Community outside the reviewed classification.'))
        communities[row['key']] = targets
    signature = digest({'source': job.id, 'selected': selected, 'communities':communities,
        'actor': current_user.id, 'policy': 'overwrite-and-classify-v3'})
    # An identity claim still guarantees idempotency if two HTTP requests race here.
    for prior in OpenAlexJob.query.filter_by(kind='import', actor=int(current_user.id)).options(defer(OpenAlexJob.snapshot), defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).limit(100):
        if prior.params.get('signature') == signature:
            return redirect(url_for('.job_detail', job_id=prior.id), code=303)
    snapshot = deepcopy({k:v for k,v in job.snapshot.items() if k not in ('records','record_store')})
    snapshot['records'] = selected_rows
    return enqueue(OpenAlexJob(kind='import', actor=int(current_user.id), snapshot=snapshot,
        params={'selected': selected, 'source_job': job.id, 'signature': signature,
                'existing_policy': 'overwrite','communities':communities}))


@blueprint.post('/jobs/<job_id>/resume')
def resume(job_id):
    job = get_job(job_id)
    if job.state != 'failed' or job.actor != int(current_user.id):
        abort(409)
    if job.kind == 'clean_apply':
        flash(t('Prepare outra prévia antes de repetir uma remoção.','Prepare another preview before repeating a removal.'),'error')
        return redirect(url_for('argiloteca_maintenance.index'),code=303)
    if job.kind == 'manual_apply':
        flash(t('Verifique novamente e prepare outra prévia antes de associar comunidades.', 'Scan again and prepare a new preview before associating communities.'),'error')
        return redirect(url_for('.manual_index'),code=303)
    if job.kind == 'dedup_merge':
        # A failed merge requires a fresh inventory/review, never stale replay.
        flash(t('Execute outra verificação e gere uma nova prévia antes de consolidar.',
                'Run another scan and save a new preview before consolidating.'),'error')
        return redirect(url_for('.duplicates_index'),code=303)
    if job.kind == 'extract':
        return enqueue(OpenAlexJob(kind='extract', actor=job.actor, params={**job.params, 'previous_job': job.id}))
    job.state = 'queued'
    job.result = {k:v for k,v in job.result.items() if k != 'error'}
    return enqueue(job)


@blueprint.get('/jobs/<job_id>/report.<format>')
def report(job_id, format):
    job = get_job(job_id)
    if job.kind in {'publish_scan', 'publish'}:
        return redirect(url_for('.publication_report', job_id=job.id, format=format), code=303)
    if format == 'json':
        header = {'id': job.id, 'kind': job.kind, 'state': job.state, 'actor': job.actor,
            'params': job.params, 'result': job.result,
            'created': job.created.isoformat(), 'updated': job.updated.isoformat()}
        snapshot = job.snapshot
        def json_report():
            yield json.dumps(header, ensure_ascii=False)[:-1]+',"snapshot":{'
            for key, value in snapshot.items():
                if key != 'records':
                    yield json.dumps(key)+':'+json.dumps(value, ensure_ascii=False)+','
            yield '"records":['
            separator = ''
            for row in iter_records(snapshot):
                yield separator+json.dumps(row, ensure_ascii=False)
                separator = ','
            yield ']}}'
        response = current_app.response_class(stream_with_context(json_report()), mimetype='application/json')
    elif format == 'csv':
        snapshot, outcomes = job.snapshot, job.result.get('items', {})
        def csv_report():
            stream = io.StringIO(); writer = csv.writer(stream)
            writer.writerow(['key', 'title', 'doi', 'openalex', 'status', 'result', 'draft_id', 'record_id', 'previous_revision'])
            yield '\ufeff'+stream.getvalue()
            for row in iter_records(snapshot):
                stream.seek(0); stream.truncate()
                outcome = outcomes.get(row['key'], {})
                values = [row['key'], row['payload'].get('metadata', {}).get('title', ''),
                    row['identity'].get('doi', ''), row['identity'].get('openalex_id', ''), row['status'], outcome.get('state', ''), outcome.get('draft_id', ''), outcome.get('record_id', ''), str(outcome.get('before_revision', ''))]
                writer.writerow(["'"+str(v) if str(v).startswith(('=', '+', '-', '@', '\t', '\r')) else v for v in values])
                yield stream.getvalue()
        response = current_app.response_class(stream_with_context(csv_report()), mimetype='text/csv')
    else:
        abort(404)
    response.headers['Content-Disposition'] = f'attachment; filename="openalex-{job.id}.{format}"'
    return response


@blueprint.get('/duplicates/')
def duplicates_index():
    jobs = OpenAlexJob.query.filter(OpenAlexJob.params['admin_archived'].as_boolean().isnot(True),OpenAlexJob.kind.in_(['dedup_scan','dedup_preview','dedup_merge'])).options(
        defer(OpenAlexJob.snapshot)).order_by(OpenAlexJob.created.desc()).limit(50).all()
    return render_template('semantic-ui/argiloteca/admin_openalex_duplicates.html',
        title=t('Duplicados DOI/OpenAlex','DOI/OpenAlex duplicates'),jobs=jobs,job=None,group=None,busy=False)


@blueprint.post('/duplicates/scan')
def duplicates_scan():
    return enqueue(OpenAlexJob(kind='dedup_scan',actor=int(current_user.id)))


@blueprint.get('/duplicates/jobs/<job_id>')
def duplicates_detail(job_id):
    job = get_job(job_id)
    if job.kind not in ('dedup_scan','dedup_preview','dedup_merge'):
        abort(404)
    groups = job.snapshot.get('groups',[])
    group = job.snapshot.get('group') or next((g for g in groups if g['id']==request.args.get('group')),None)
    return render_template('semantic-ui/argiloteca/admin_openalex_duplicates.html',
        title=t('Duplicados DOI/OpenAlex','DOI/OpenAlex duplicates'),jobs=[],job=job,group=group,
        busy=job.state in ('queued','running'))


@blueprint.post('/duplicates/jobs/<job_id>/preview')
def duplicates_preview(job_id):
    from .duplicates import plan_group, reference_blockers
    job = get_job(job_id)
    if job.kind not in ('dedup_scan','dedup_preview') or job.state!='review':
        abort(409)
    source = job.snapshot.get('group') or next((g for g in job.snapshot.get('groups',[]) if g['id']==request.form.get('group')),None)
    if not source:
        abort(404)
    try:
        choices = {}
        for conflict in source['conflicts'] if request.form.get('canonical')==source['canonical'] else []:
            submitted = request.form.get('choice:'+conflict['path'])
            if submitted is not None:
                index = int(submitted)
                if not 0<=index<len(conflict['values']):
                    raise ValueError('Escolha inválida.')
                choices[conflict['path']] = conflict['values'][index]
        group = reference_blockers(plan_group(source['records'],request.form.get('canonical'),choices))
        preview = OpenAlexJob(kind='dedup_preview',state='review',actor=int(current_user.id),
            params={'source_job':job.id,'test_only':bool(job.params.get('test_only'))},snapshot={'schema':1,'group':group},result={})
        db.session.add(preview);db.session.commit()
    except (ValueError,TypeError) as exc:
        flash(str(exc),'error')
        return redirect(url_for('.duplicates_detail',job_id=job.id,group=source['id']),code=303)
    return redirect(url_for('.duplicates_detail',job_id=preview.id),code=303)


@blueprint.post('/duplicates/jobs/<job_id>/consolidate')
def duplicates_consolidate(job_id):
    job = get_job(job_id)
    if job.kind=='dedup_preview' and job.state=='completed' and job.result.get('merge_job'):
        return redirect(url_for('.duplicates_detail',job_id=job.result['merge_job']),code=303)
    if job.kind!='dedup_preview' or job.state!='review':
        abort(409)
    group = job.snapshot['group']
    if group['blockers'] or request.form.get('confirm')!='yes' or request.form.get('plan_sha256')!=digest(group):
        abort(409,description=t('Revise a prévia e confirme uma proposta sem bloqueios.',
                               'Review and confirm a proposal without blockers.'))
    # Serialise double clicks before dispatch; a completed source preview is
    # also rejected later by exact fingerprints if submitted again.
    from sqlalchemy import text
    db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
    for prior in OpenAlexJob.query.filter_by(kind='dedup_merge').order_by(OpenAlexJob.created.desc()).limit(200):
        if prior.params.get('source_job')==job.id:
            return redirect(url_for('.duplicates_detail',job_id=prior.id),code=303)
    return enqueue(OpenAlexJob(kind='dedup_merge',actor=int(current_user.id),
        params={'source_job':job.id,'plan_sha256':digest(group),'test_only':bool(job.params.get('test_only'))},snapshot=deepcopy(job.snapshot)))


@blueprint.get('/duplicates/jobs/<job_id>/backup.zip')
def duplicates_backup(job_id):
    from .duplicates import backup_path, sha256_file
    job = get_job(job_id)
    if job.kind!='dedup_merge' or not job.result.get('backup'):
        abort(404)
    path = backup_path(job.id)
    if not path.is_file():
        abort(404)
    if sha256_file(path)!=job.result['backup']['sha256']:
        abort(409,description=t('Backup divergente. Consulte o administrador local.',
                               'Backup checksum mismatch. Contact the local administrator.'))
    return send_file(path,as_attachment=True,download_name='argiloteca-duplicados-'+job.id+'.zip',
                     mimetype='application/zip',conditional=False)


# Manual curation uses the same administrative access, CSRF, private responses
# and durable job journal as OpenAlex import and duplicate consolidation.
def manual_page(job=None):
    jobs=[j for j in OpenAlexJob.query.filter(OpenAlexJob.params['admin_archived'].as_boolean().isnot(True),OpenAlexJob.kind.in_(['manual_scan','manual_apply'])).options(
        defer(OpenAlexJob.snapshot)).order_by(OpenAlexJob.created.desc()).limit(200) if not j.params.get('test_only')][:50]
    if job is None:
        job=next((j for j in OpenAlexJob.query.filter(OpenAlexJob.params['admin_archived'].as_boolean().isnot(True)).filter_by(kind='manual_scan').filter(OpenAlexJob.state.in_(['queued','running','review'])).order_by(OpenAlexJob.created.desc()) if not j.params.get('test_only')),None)
    resolved={}
    for item in OpenAlexJob.query.filter_by(kind='manual_apply',state='completed').order_by(OpenAlexJob.created.desc()):
        decision=item.result.get('decision')
        if decision:resolved.setdefault((decision['parent_id'],decision['topic_sha256']),item.id)
    rows=job.snapshot.get('rows',[]) if job and job.kind=='manual_scan' else []
    q=request.args.get('q','').strip()[:200]
    filtered=[r for r in rows if not q or q.casefold() in (r['metadata'].get('title','')+' '+r['id']).casefold()]
    try:page=max(1,int(request.args.get('page',1)))
    except ValueError:abort(400)
    pages=max(1,(len(filtered)+19)//20);page=min(page,pages)
    row=next((r for r in rows if r['id']==request.args.get('record')),None)
    catalog=job.snapshot.get('plan',{}).get('catalog',{}) if job and job.kind in ('manual_preview','manual_apply') else job.snapshot.get('catalog',{}) if job else {}
    return render_template('semantic-ui/argiloteca/admin_openalex_manual.html',
        title=t('Registros sem classificação','Unclassified records'),job=job,jobs=jobs,
        rows=filtered[(page-1)*20:page*20],total=len(filtered),page=page,pages=pages,q=q,row=row,
        plan=job.snapshot.get('plan') if job else None,catalog=catalog,
        community_names={c['id']:c for c in catalog.values()},resolved=resolved,
        busy=bool(job and job.state in ('queued','running')))


@blueprint.get('/classification/')
def manual_index():
    return manual_page()


@blueprint.post('/classification/scan')
def manual_scan():
    return enqueue(OpenAlexJob(kind='manual_scan',actor=int(current_user.id)))


@blueprint.get('/classification/jobs/<job_id>')
def manual_detail(job_id):
    job=get_job(job_id)
    if job.kind not in ('manual_scan','manual_preview','manual_apply'):abort(404)
    return manual_page(job)


@blueprint.post('/classification/jobs/<job_id>/preview')
def manual_preview(job_id):
    from .manual_review import build_plan, snapshot_record
    from .service import actor_identity
    job=get_job(job_id)
    if job.kind!='manual_scan' or job.state!='review':abort(409)
    row=next((r for r in job.snapshot['rows'] if r['id']==request.form.get('record')),None)
    if not row:abort(404)
    try:
        from invenio_rdm_records.records.models import RDMRecordMetadata, RDMDraftMetadata
        import uuid
        model=db.session.get(RDMRecordMetadata if row['kind']=='published' else RDMDraftMetadata,uuid.UUID(row['uuid']))
        if model is None:raise ValueError('Registro indisponível. Verifique novamente.')
        identity=actor_identity(int(current_user.id))
        if snapshot_record(identity,(model,row['kind']))['fingerprint']!=row['fingerprint']:
            raise ValueError('O registro ou seus vínculos mudaram. Verifique novamente antes de revisar.')
        plan=build_plan(identity,row,request.form.getlist('community'),request.form.get('note','').strip(),request.form.get('intent')=='keep')
        preview=OpenAlexJob(kind='manual_preview',state='review',actor=int(current_user.id),
            params={'scan_job':job.id,'test_only':bool(job.params.get('test_only'))},snapshot={'plan':plan})
        db.session.add(preview);db.session.commit()
    except ValueError as exc:
        db.session.rollback();flash(str(exc),'error')
        return redirect(url_for('.manual_detail',job_id=job.id,record=row['id']),code=303)
    return redirect(url_for('.manual_detail',job_id=preview.id),code=303)


@blueprint.post('/classification/jobs/<job_id>/apply')
def manual_apply(job_id):
    from sqlalchemy import text
    job=get_job(job_id)
    if job.kind=='manual_preview' and job.state=='completed' and job.result.get('apply_job'):
        return redirect(url_for('.manual_detail',job_id=job.result['apply_job']),code=303)
    if job.kind!='manual_preview' or job.state!='review' or job.actor!=int(current_user.id):abort(409)
    if request.form.get('confirm')!='yes' or request.form.get('plan_sha256')!=digest(job.snapshot['plan']):
        abort(409,description=t('Confira os vínculos da prévia e confirme a associação.', 'Review the preview memberships and confirm the association.'))
    db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
    for prior in OpenAlexJob.query.filter_by(kind='manual_apply'):
        if prior.params.get('source_job')==job.id:
            return redirect(url_for('.manual_detail',job_id=prior.id),code=303)
    return enqueue(OpenAlexJob(kind='manual_apply',actor=int(current_user.id),snapshot=deepcopy(job.snapshot),
        params={'source_job':job.id,'scan_job':job.params['scan_job'],'plan_sha256':digest(job.snapshot['plan']),
                'test_only':bool(job.params.get('test_only'))}))


@blueprint.post('/classification/jobs/<job_id>/refresh-search')
def manual_refresh(job_id):
    from .manual_review import refresh_record
    job=get_job(job_id)
    if job.kind!='manual_apply' or job.state!='completed':abort(409)
    refresh_record(job.snapshot['plan'])
    job.result={**job.result,'search_refreshed':True};db.session.commit()
    return redirect(url_for('.manual_detail',job_id=job.id),code=303)
