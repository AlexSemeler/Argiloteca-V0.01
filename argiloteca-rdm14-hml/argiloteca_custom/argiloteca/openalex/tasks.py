"""Durable Celery jobs. Extraction runs in the Mac agent, never in HTTP requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

from celery import shared_task
from flask import current_app
from invenio_db import db

from .adapters import read_json
from .models import OpenAlexJob
from .service import actor_identity, import_job, job_lock


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def extraction(job):
    queue = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])
    response = queue / (job.id + '.result.json')
    if response.exists():
        job.result = read_json(response, queue)
        job.state = 'completed' if job.result.get('state') == 'completed' else 'failed'
        return
    request = queue / (job.id + '.request.json')
    if not request.exists():
        atomic_json(request, {'version': 1, 'id': job.id, 'params': job.params,
                              'created': job.created.isoformat()})
    if datetime.now(timezone.utc) - job.created.replace(tzinfo=timezone.utc) > timedelta(hours=1):
        raise ValueError('Tempo de coleta excedido. Consulte o agente local e os lotes preservados.')
    job.state = 'waiting_host'
    heartbeat = queue / 'heartbeat.json'
    job.result = {'message': 'Coleta aguardando ou em execução no Mac.',
                  'host': read_json(heartbeat, queue) if heartbeat.exists() else {'state': 'offline'}}


@shared_task(ignore_result=True, soft_time_limit=1700, time_limit=1800)
def run(job_id):
    with job_lock(job_id) as locked:
        if not locked:
            return
        job = db.session.get(OpenAlexJob, job_id)
        if not job or job.state in {'completed', 'review', 'failed'}:
            return
        try:
            actor_identity(job.actor)
            root = current_app.config['ARGILOTECA_OPENALEX_ROOT']
            job.state = 'running'
            db.session.commit()
            if job.kind == 'pop_orcid_preview':
                if not current_app.config.get('ARGILOTECA_POPULATION_ENABLED'):
                    raise ValueError('Povoamento integrado desabilitado neste ambiente.')
                from ..population.orcid import prepare as prepare_population_orcid
                prepare_population_orcid(job)
                db.session.commit()
                return
            if job.kind.startswith('oai_'):
                if not current_app.config.get('ARGILOTECA_REPOSITORIES_ENABLED'):
                    raise ValueError('Módulo Repositórios OAI desabilitado neste ambiente.')
                from ..repositories.workflow import run as run_repositories
                run_repositories(job)
                return
            if job.kind.startswith('men_'):
                if not current_app.config.get('ARGILOTECA_MENDELEY_ENABLED'):
                    raise ValueError('Módulo Mendeley Data desabilitado neste ambiente.')
                from ..mendeley.workflow import run as run_mendeley
                run_mendeley(job)
                return
            if job.kind.startswith('pan_'):
                from ..pangaea.workflow import run as run_pangaea
                run_pangaea(job)
                return
            if job.kind == 'enrich_collect':
                from .enrichment import collect_chunk
                delay=collect_chunk(job)
                if delay:
                    run.apply_async(args=[job.id],countdown=delay)
                return
            elif job.kind in {'enrich_apply','enrich_restore'}:
                from .enrichment import apply,restore
                (apply if job.kind=='enrich_apply' else restore)(job)
                return
            elif job.kind == 'extract':
                extraction(job)
            elif job.kind == 'stats_scan':
                from .analytics import prepare
                with job_lock('openalex-statistics-preparation') as preparing:
                    if not preparing:
                        job.state = 'queued'
                        db.session.commit()
                        return
                    prepare(job)
                    if job.params.get('enrich_after'):
                        child=OpenAlexJob(kind='enrich_collect',actor=job.actor,params={'analysis':job.id,'example':False})
                        db.session.add(child);db.session.flush()
                        job.result={**job.result,'enrichment_job':child.id}
                        # Parent and child commit together. The SQL outbox recovers
                        # a queued collection even if dispatch is interrupted.
            elif job.kind in {'orcid_search', 'orcid_lookup'}:
                from .orcid import search, lookup
                (search if job.kind == 'orcid_search' else lookup)(job)
            elif job.kind == 'orcid_preview':
                from .orcid import prepare_plan
                analysis = db.session.get(OpenAlexJob, job.params['analysis'])
                job.snapshot = prepare_plan(analysis, job.params['keys'], job.params['orcid'], job.params['evidence'], job.actor)
                job.state = 'review'
            elif job.kind == 'orcid_apply':
                from .orcid import apply
                apply(job)
                return
            elif job.kind == 'prepare':
                from .maintenance import pending_lot_maintenance
                if pending_lot_maintenance(job.params['lot']):
                    raise ValueError('Há manutenção confirmada deste lote. Aguarde antes de preparar.')
                from .preview import build
                # Several distinct preview jobs must not multiply the worker's
                # scientific runtime/inventory memory on the same host.
                with job_lock('openalex-preview-preparation') as preparing:
                    if not preparing:
                        job.state = 'queued'
                        job.result = {'message': 'Aguardando a preparação de outra prévia.'}
                        db.session.commit()
                        return
                    job.snapshot = build(job, root)
                job.state = 'review'
                job.result = {'message': 'Revisão preparada; selecione os registros para importar.'}
            elif job.kind == 'import':
                import_job(job, root)
                return
            elif job.kind == 'publish_scan':
                from .publication import prepare
                with job_lock('openalex-publication-preview') as preparing:
                    if not preparing:
                        job.state = 'queued'
                        db.session.commit()
                        return
                    prepare(job)
            elif job.kind == 'publish':
                from .publication import run_chunk
                if run_chunk(job):
                    try:
                        run.apply_async(args=[job.id], countdown=2)
                    except Exception:
                        current_app.logger.warning('OpenAlex publication pending recovery: %s', job.id)
                return
            elif job.kind == 'clean_apply':
                from .maintenance import run_job
                run_job(job)
                return
            elif job.kind == 'manual_scan':
                from .manual_review import scan_job
                scan_job(job)
            elif job.kind == 'manual_apply':
                from .manual_review import apply_job
                apply_job(job)
                return
            elif job.kind == 'dedup_scan':
                from .duplicates import scan_job
                scan_job(job)
            elif job.kind == 'dedup_merge':
                from .duplicates import consolidate_job
                consolidate_job(job)
                return
            else:
                raise ValueError('Tipo de tarefa desconhecido.')
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            if job.kind.startswith('enrich_'):
                current_app.logger.error('OpenAlex enrichment failed: %s (%s)',job_id,type(exc).__name__)
            else:
                current_app.logger.exception('OpenAlex job failed: %s', job_id)
            job = db.session.get(OpenAlexJob, job_id)
            if job.kind in ('dedup_merge','manual_apply','clean_apply','publish','pan_publish','men_publish','oai_publish','orcid_apply','enrich_apply','enrich_restore') and job.state=='completed':
                # SQL may have committed before an index hook failed. Never
                # present this as an uncommitted operation that can be replayed.
                current_app.logger.error('Consolidation committed; inspect index hooks: %s',job_id)
                if job.kind=='clean_apply':
                    job.result={**(job.result or {}),'index_warning':True}
                    db.session.commit()
                return
            job.state = 'failed'
            result = deepcopy(job.result or {})
            # Generic unexpected exceptions never leak configuration or credentials.
            result['error'] = str(exc)[:2000] if isinstance(exc, ValueError) else 'Falha de processamento. Consulte o log do worker e retome a tarefa.'
            if job.kind in {'stats_scan','orcid_search','orcid_lookup','orcid_preview','orcid_apply'}:
                result['error_en'] = getattr(exc,'message_en','Processing failed. Review the author and preview, or inspect the worker log before trying again.')
            if job.kind in ('dedup_merge','clean_apply'):
                from .duplicates import backup_path, sha256_file
                path = (Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'maintenance-backups'/(job.id+'.zip')) if job.kind=='clean_apply' and job.snapshot['plan']['kind']=='lot' else backup_path(job.id)
                # A committed checkpoint pins the original verified checksum.
                # Never bless a changed ZIP while reporting a cleanup failure.
                if path.is_file() and not result.get('backup'):
                    result['backup'] = {'filename':path.name,'sha256':sha256_file(path),'bytes':path.stat().st_size}
            job.result = result
            db.session.commit()


@shared_task(ignore_result=True)
def recover():
    """Database outbox recovery also covers failures between DB commit and enqueue."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    for (job_id,) in db.session.query(OpenAlexJob.id).filter(db.or_(OpenAlexJob.state.in_(['queued', 'waiting_host']),
            db.and_(OpenAlexJob.state == 'running', OpenAlexJob.updated < cutoff),
            db.and_(OpenAlexJob.kind=='enrich_collect',OpenAlexJob.state=='waiting_api',
                OpenAlexJob.result['retry_at'].as_float()<=datetime.now(timezone.utc).timestamp()))).limit(100):
        run.delay(job_id)
