"""Explicit download jobs and administrator-only private PDF retrieval."""
from copy import deepcopy
from pathlib import Path
import re
from flask import abort, current_app, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from ..openalex.adapters import digest
from ..openalex.models import OpenAlexJob
from ..openalex.preview import iter_records
from .client import sha
from .workflow import root, verify_snapshot
from .views import blueprint, enqueue, get_job, t


@blueprint.post('/jobs/<job_id>/pdfs')
def pdf_selected(job_id):
    source=get_job(job_id)
    if source.kind!='oai_prepare' or source.state!='review': abort(409)
    selected=sorted(set(request.form.getlist('pdf_selected')))
    if request.form.get('confirm')!='yes' or not 1<=len(selected)<=20: abort(400)
    rows=list(iter_records(source.snapshot,selected))
    if {r['key'] for r in rows}!=set(selected): abort(409)
    verify_snapshot(root(),{**source.snapshot,'records':rows})
    snapshot=deepcopy({k:v for k,v in source.snapshot.items() if k not in ('records','record_store')});snapshot['records']=rows
    # Repeating a submission is idempotent, but an explicit new attempt may
    # retry access/network failures without changing the previous report.
    from ..openalex.service import job_lock
    signature=digest({'source':source.id,'selected':selected,'actor':int(current_user.id),'attempt':request.form.get('attempt','')[:32]})
    with job_lock('repositories-pdf-'+signature) as locked:
        if not locked: abort(409)
        prior=OpenAlexJob.query.filter_by(kind='oai_pdf',actor=int(current_user.id)).filter(OpenAlexJob.params['signature'].as_string()==signature).first()
        if prior: return redirect(url_for('.pdf_detail',job_id=prior.id),code=303)
        return enqueue(OpenAlexJob(kind='oai_pdf',actor=int(current_user.id),snapshot=snapshot,
            params={'selected':selected,'source_job':source.id,'signature':signature}))


@blueprint.get('/pdfs/jobs/<job_id>')
def pdf_detail(job_id):
    job=get_job(job_id)
    if job.kind!='oai_pdf': abort(404)
    return render_template('semantic-ui/argiloteca/admin_repositories_pdfs.html',
        title=t('PDFs dos repositórios','Repository PDFs'),job=job,busy=job.state in {'queued','running','waiting_host'})


@blueprint.post('/pdfs/jobs/<job_id>/retry')
def pdf_retry(job_id):
    job=get_job(job_id)
    if job.kind!='oai_pdf' or job.state not in {'completed','failed'} or job.actor!=int(current_user.id): abort(409)
    # New job, same audited selection; completed files are content-addressed and
    # never overwritten. Each attempt has its own manifest and report.
    return enqueue(OpenAlexJob(kind='oai_pdf',actor=int(current_user.id),snapshot=deepcopy(job.snapshot),params={**job.params,'previous_job':job.id}))


@blueprint.get('/pdfs/jobs/<job_id>/files/<checksum>')
def pdf_download(job_id,checksum):
    job=get_job(job_id)
    if job.kind!='oai_pdf' or not re.fullmatch(r'[a-f0-9]{64}',checksum): abort(404)
    file=next((f for item in job.result.get('pdfs',{}).get('items',{}).values() for f in item.get('files',[]) if f['sha256']==checksum),None)
    if not file: abort(404)
    path=root()/'pdfs'/'blobs'/(checksum+'.pdf')
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=file['bytes'] or sha(path)!=checksum: abort(409)
    return send_file(path,as_attachment=True,mimetype='application/pdf',download_name='repositorio-'+checksum[:16]+'.pdf',max_age=0)


@blueprint.get('/pdfs/')
def pdf_index():
    from sqlalchemy.orm import defer
    jobs=OpenAlexJob.query.filter_by(kind='oai_pdf').options(defer(OpenAlexJob.snapshot)).order_by(OpenAlexJob.created.desc()).limit(50).all()
    return render_template('semantic-ui/argiloteca/admin_repositories_pdfs.html',title=t('PDFs dos repositórios','Repository PDFs'),job=None,jobs=jobs,busy=False)
