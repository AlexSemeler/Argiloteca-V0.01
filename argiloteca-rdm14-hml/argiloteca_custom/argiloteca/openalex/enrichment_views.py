"""CSRF/admin-protected analytical review and recovery on the native blueprint."""
from datetime import datetime, timezone
import json
import re
import sqlite3
from flask import abort,flash,redirect,render_template,request,send_file,url_for
from flask_login import current_user
from invenio_db import db
from . import enrichment as e
from .adapters import digest
from .models import OpenAlexJob
from .service import job_lock
from .views import blueprint,enqueue,get_job,t


def target(job):return redirect(url_for('.enrichment_detail',job_id=job.id),code=303)


@blueprint.get('/enrichment/')
def enrichment_index():
    from .analytics_views import current_analysis
    jobs=OpenAlexJob.query.filter(OpenAlexJob.kind.in_(['enrich_collect','enrich_apply','enrich_restore'])).order_by(OpenAlexJob.created.desc()).limit(30).all()
    active=e.head();coverage=None
    if active:
        e.checked_version(active)
        with e.store(active) as c:coverage=c.execute('SELECT count(*) FROM accepted').fetchone()[0]
    return render_template('semantic-ui/argiloteca/admin_openalex_enrichment.html',title=t('Atualizar dados do Acervo','Update collection data'),jobs=jobs,analysis=current_analysis(),job=None,active=active,coverage=coverage)


@blueprint.post('/enrichment/refresh-acervo')
def enrichment_refresh_acervo():
    """Refresh the native inventory before collecting a new complete preview."""
    with job_lock('enrichment-enqueue') as locked:
        if not locked:abort(409)
        busy=OpenAlexJob.query.filter(OpenAlexJob.kind.in_(['enrich_collect','enrich_apply','enrich_restore']),OpenAlexJob.state.in_(['queued','running','waiting_api'])).first()
        if busy:return target(busy)
        scan=OpenAlexJob.query.filter_by(kind='stats_scan').filter(OpenAlexJob.state.in_(['queued','running']),OpenAlexJob.params['enrich_after'].as_boolean()==True).first()
        if scan:return redirect(url_for('.orcid_job',job_id=scan.id),code=303)
        return enqueue(OpenAlexJob(kind='stats_scan',actor=int(current_user.id),params={'enrich_after':True}))


@blueprint.post('/enrichment/collect')
def enrichment_collect():
    from .analytics_views import current_analysis
    analysis=current_analysis()
    if not analysis:abort(409)
    with job_lock('enrichment-enqueue') as locked:
        if not locked:abort(409)
        busy=OpenAlexJob.query.filter_by(kind='enrich_collect').filter(OpenAlexJob.state.in_(['queued','running','waiting_api'])).first()
        if busy:return target(busy)
        return enqueue(OpenAlexJob(kind='enrich_collect',actor=int(current_user.id),params={'analysis':analysis.id,'example':request.form.get('scope')=='example'}))


@blueprint.get('/enrichment/jobs/<job_id>')
def enrichment_detail(job_id):
    job=get_job(job_id)
    if not job.kind.startswith('enrich_'):abort(404)
    rows=[];total=0;pages=1
    try:page=max(1,int(request.args.get('page',1)))
    except ValueError:abort(400)
    status=request.args.get('status','')
    if status not in ('','ready','blocked','missing','error','pending'):abort(400)
    if job.kind=='enrich_collect' and e.path_for(job.id).is_file():
        try:
            with e.store(job.id) as c:
                clause=' WHERE status=?' if status else '';params=[status] if status else []
                total=c.execute('SELECT count(*) FROM plan'+clause,params).fetchone()[0]
                pages=max(1,(total+19)//20);page=min(page,pages)
                rows=[dict(r) for r in c.execute('SELECT * FROM plan'+clause+' ORDER BY rid LIMIT 20 OFFSET ?',[*params,(page-1)*20])]
                for row in rows:
                    for key in ('old','proposed','candidates'):row[key]=json.loads(row[key]) if row[key] else None
        except (ValueError,sqlite3.Error):abort(409)
    if rows:
        from .analytics import connect as base_connect
        base=db.session.get(OpenAlexJob,job.snapshot.get('analysis'))
        if base:
            with base_connect(base) as c:
                for row in rows:
                    row['display_old']=row['old']
                    if row['old'] is None:
                        original=c.execute('SELECT citations FROM works WHERE rid=?',(row['rid'],)).fetchone()
                        raw=c.execute('SELECT body FROM raw_work WHERE oa_id=?',(row['oa_id'],)).fetchone()
                        row['display_old']={k:json.loads(raw[0]).get(k) for k in e.METRICS} if raw else {}
                        if original:row['display_old']['cited_by_count']=original[0]
    return render_template('semantic-ui/argiloteca/admin_openalex_enrichment.html',title=t('Revisar Topics e métricas','Review Topics and metrics'),job=job,rows=rows,total=total,pages=pages,page=page,status=status,
        active=e.head(),plan_hash=job.snapshot.get('sha256',''),metrics=e.METRICS,busy=job.state in ('queued','running','waiting_api'))


@blueprint.post('/enrichment/jobs/<job_id>/resume')
def enrichment_resume(job_id):
    job=get_job(job_id)
    if job.kind!='enrich_collect' or job.state!='failed':abort(409)
    job.state='queued';job.result={**job.result,'retries':0,'retry_at':0};db.session.commit()
    from .tasks import run
    run.delay(job.id)
    return target(job)


@blueprint.post('/enrichment/jobs/<job_id>/apply')
def enrichment_apply(job_id):
    source=get_job(job_id)
    if request.form.get('confirm')!='APLICAR' or request.form.get('plan_sha256')!=source.snapshot.get('sha256'):abort(409)
    try:e.validate_plan(source)
    except ValueError:abort(409)
    selection='all' if request.form.get('all_ready')=='yes' else sorted(set(request.form.getlist('selected')))
    if selection!='all' and (not selection or len(selection)>100 or any(not re.fullmatch(r'[a-f0-9-]{36}',x) for x in selection)):abort(400)
    review={'actor':int(current_user.id),'at':datetime.now(timezone.utc).isoformat(),'confirmation':'APLICAR','preview_sha256':source.snapshot['sha256']}
    token=digest({'preview':source.id,'selection':selection})
    with job_lock('enrichment-apply-'+source.id) as locked:
        if not locked:abort(409)
        prior=OpenAlexJob.query.filter_by(kind='enrich_apply').filter(OpenAlexJob.params['token'].as_string()==token,OpenAlexJob.state.in_(['queued','running','completed'])).order_by(OpenAlexJob.created.desc()).first()
        if prior and (prior.state!='completed' or e.head()==prior.id):return target(prior)
        return enqueue(OpenAlexJob(kind='enrich_apply',actor=int(current_user.id),params={'preview':source.id,'selection':selection,'review':review,'token':token}))


@blueprint.get('/enrichment/jobs/<job_id>/backup')
def enrichment_backup(job_id):
    job=get_job(job_id);saved=job.result.get('backup');path=e.path_for(job.id,'.zip')
    if job.kind!='enrich_apply' or not saved:abort(404)
    if path.is_symlink() or not path.is_file() or e.sha(path)!=saved['sha256']:abort(409)
    return send_file(path,as_attachment=True,mimetype='application/zip',download_name='openalex-analytical-backup-'+job.id+'.zip')


@blueprint.post('/enrichment/jobs/<job_id>/restore')
def enrichment_restore(job_id):
    source=get_job(job_id)
    if source.kind!='enrich_apply' or source.state!='completed' or e.head()!=source.id or request.form.get('confirm')!='RESTAURAR':abort(409)
    return enqueue(OpenAlexJob(kind='enrich_restore',actor=int(current_user.id),params={'version':source.id,'confirmation':'RESTAURAR','at':datetime.now(timezone.utc).isoformat()}))


@blueprint.post('/enrichment/jobs/<job_id>/review')
def enrichment_review(job_id):
    """Manual identity decisions fork a plan, never mutate a sealed preview."""
    import os
    import shutil
    source=get_job(job_id)
    try:e.validate_plan(source)
    except ValueError:abort(409)
    if request.form.get('plan_sha256')!=source.snapshot['sha256'] or request.form.get('confirm')!='REVISADO':abort(409)
    uid=request.form.get('uid','');candidate=request.form.get('candidate','');note=request.form.get('note','').strip()
    if not 10<=len(note)<=2000:abort(400)
    with e.store(source.id) as c:
        row=c.execute('SELECT * FROM plan WHERE uid=?',(uid,)).fetchone()
        if not row or row['status']!='blocked':abort(409)
        chosen=next((x for x in json.loads(row['candidates']) if x['id']==candidate),None)
        if not chosen:abort(400)
        live=e.native(uid)
        if not live or live[1]!='P' or e.native_hash(live[0])!=row['native_hash']:abort(409)
    fork=OpenAlexJob(kind='enrich_collect',state='review',actor=int(current_user.id),params={**source.params,'parent':source.id},snapshot={**source.snapshot,'identity_review':{'actor':int(current_user.id),'at':e.now(),'uid':uid,'candidate':candidate,'note':note,'parent':source.id}})
    db.session.add(fork);db.session.flush()
    shutil.copyfile(e.path_for(source.id),e.path_for(fork.id));os.chmod(e.path_for(fork.id),0o600)
    with e.store(fork.id,True) as c:
        c.execute("UPDATE plan SET status='ready',reason=?,proposed=? WHERE uid=?",('Manual identifier review: '+note,json.dumps(chosen['payload']),uid))
        fork.result=e.progress(c)
    fork.snapshot={**fork.snapshot,'sha256':e.sha(e.path_for(fork.id))}
    db.session.commit();return target(fork)
