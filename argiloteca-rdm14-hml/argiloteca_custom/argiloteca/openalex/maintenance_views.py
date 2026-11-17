"""Administrative maintenance UI; previews do not mutate collection data."""
from copy import deepcopy
from pathlib import Path
from flask import Blueprint,abort,render_template,request,redirect,url_for,flash,send_file,current_app
from flask_login import current_user
from sqlalchemy.orm import defer
from invenio_db import db
from invenio_rdm_records.records.models import RDMRecordMetadata,RDMDraftMetadata
from .models import OpenAlexJob
from .views import protect,private,context,t,enqueue,get_job
from .adapters import digest,lots
from .service import actor_identity,job_lock
from . import maintenance as clean

blueprint=Blueprint('argiloteca_maintenance',__name__,url_prefix='/administration/maintenance')
blueprint.before_request(protect);blueprint.after_request(private);blueprint.context_processor(context)


def record_rows(q,kind,state,page):
    rows=[];total=0
    for cls,k in ((RDMRecordMetadata,'published'),(RDMDraftMetadata,'draft')):
        if kind and kind!=k:continue
        query=cls.query.filter(cls.json.isnot(None))
        if k=='published' and state!='all':query=query.filter(cls.deletion_status==('D' if state=='withdrawn' else 'P'))
        if k=='draft' and state=='withdrawn':continue
        if k=='draft':
            query=query.outerjoin(RDMRecordMetadata,cls.id==RDMRecordMetadata.id).filter(db.or_(RDMRecordMetadata.id.is_(None),RDMRecordMetadata.deletion_status=='P'))
        if q:
            literal=q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            query=query.filter(db.or_(cls.json['metadata']['title'].as_string().ilike('%'+literal+'%',escape='\\'),cls.json['id'].as_string()==q))
        total+=query.count()
        for r in query.order_by(cls.updated.desc()).limit(page*20):
            rows.append({'id':r.json['id'],'title':r.json.get('metadata',{}).get('title',''),
                'kind':k,'status':r.deletion_status.value if k=='published' else 'draft','updated':r.updated})
    rows.sort(key=lambda r:r['updated'],reverse=True)
    return rows[(page-1)*20:page*20],total


@blueprint.get('/')
def index():
    tab=request.args.get('tab','records');q=request.args.get('q','').strip()[:200]
    if tab not in {'records','jobs','lots','history'}:abort(400)
    page=max(1,request.args.get('page',1,type=int));rows=[];total=0
    kind=request.args.get('record_kind','');state=request.args.get('state','active')
    if kind not in {'','published','draft'} or state not in {'active','withdrawn','all'}:abort(400)
    selected=None;error=None
    if tab=='records':
        rows,total=record_rows(q,kind,state,page)
        if request.args.get('record'):
            if kind not in {'published','draft'}:abort(400)
            selected=clean.record_state(actor_identity(current_user.id),request.args['record'],kind)
            from ..scientific.connections import FIELD
            from ..scientific.catalog_views import coordinate_targets
            selected['connections']=selected['raw'].get('custom_fields',{}).get(FIELD,[])
            selected['coordinates']=coordinate_targets(selected['raw'].get('custom_fields',{}))
            selected['communities']=[]
            from invenio_communities.proxies import current_communities
            for cid in selected['data'].get('parent',{}).get('communities',{}).get('ids',[]):
                community=current_communities.service.read(actor_identity(current_user.id),cid).to_dict()
                selected['communities'].append({'id':cid,'title':community['metadata']['title']})
    elif tab=='jobs':
        query=OpenAlexJob.query.filter(~OpenAlexJob.kind.like('clean_%'))
        if q:query=query.filter(OpenAlexJob.id.startswith(q))
        archived=request.args.get('archived')=='yes'
        query=query.filter(OpenAlexJob.params['admin_archived'].as_boolean().is_(True)) if archived else clean.visible_jobs(query)
        total=query.count();rows=query.options(defer(OpenAlexJob.snapshot),defer(OpenAlexJob.result)).order_by(OpenAlexJob.created.desc()).offset((page-1)*20).limit(20).all()
    elif tab=='lots':
        root=Path(current_app.config['ARGILOTECA_OPENALEX_ROOT'])
        rows=[dict(r,archived=False) for r in lots(root)]
        trash=root/'.admin-trash'
        if trash.is_dir() and not trash.is_symlink():
            rows += [{'name':r.name,'count':None,'complete':False,'archived':True} for r in sorted(trash.glob('v59_*'),reverse=True) if r.is_dir() and not r.is_symlink()]
        rows=[r for r in rows if not q or q.casefold() in r['name'].casefold()];total=len(rows);rows=rows[(page-1)*20:page*20]
    else:
        query=OpenAlexJob.query.filter_by(kind='clean_apply')
        if q:query=query.filter(OpenAlexJob.id.startswith(q))
        total=query.count()
        rows=query.with_entities(OpenAlexJob.id,OpenAlexJob.actor,OpenAlexJob.created,OpenAlexJob.state,OpenAlexJob.result,
            OpenAlexJob.snapshot['plan']['action'].as_string().label('action'),
            OpenAlexJob.snapshot['plan']['title'].as_string().label('title'),
            OpenAlexJob.snapshot['plan']['target'].as_string().label('target')).order_by(OpenAlexJob.created.desc()).offset((page-1)*20).limit(20).all()
    return render_template('semantic-ui/argiloteca/admin_maintenance.html',title=t('Remover e arquivar','Remove and archive'),
        tab=tab,q=q,page=page,total=total,rows=rows,selected=selected,record_kind=kind,state=state,error=error)


@blueprint.post('/preview')
def preview():
    try:
        p=clean.plan(actor_identity(current_user.id),current_user.id,request.form.get('kind'),request.form.get('target',''),request.form.get('action'),
            record_kind=request.form.get('record_kind',''),selection=request.form.get('selection',''),reason=request.form.get('reason',''),archived=request.form.get('archived')=='yes')
    except ValueError as exc:
        db.session.rollback();flash(str(exc),'error');return redirect(url_for('.index',tab=request.form.get('tab','records')),code=303)
    job=OpenAlexJob(kind='clean_preview',state='review',actor=int(current_user.id),snapshot={'plan':p},params={'test_only':False})
    db.session.add(job);db.session.commit();return redirect(url_for('.detail',job_id=job.id),code=303)


@blueprint.get('/jobs/<job_id>')
def detail(job_id):
    job=get_job(job_id)
    if job.kind not in {'clean_preview','clean_apply'}:abort(404)
    return render_template('semantic-ui/argiloteca/admin_maintenance_job.html',title=t('Prévia e resultado da remoção','Removal preview and result'),job=job,
        plan=job.snapshot['plan'],busy=job.state in clean.ACTIVE)


@blueprint.post('/jobs/<job_id>/apply')
def apply(job_id):
    source=get_job(job_id)
    if source.kind!='clean_preview' or source.actor!=int(current_user.id):abort(403)
    p=source.snapshot['plan']
    if request.form.get('confirm')!='yes' or request.form.get('plan_sha256')!=digest(p):abort(409)
    if p['permanent'] and request.form.get('permanent_confirmation','').strip()!='EXCLUIR':abort(409)
    if p['blockers']:abort(409)
    with job_lock(source.id) as locked:
        if not locked:abort(409)
        prior=OpenAlexJob.query.filter_by(kind='clean_apply').filter(OpenAlexJob.params['source_job'].as_string()==source.id).first()
        if prior:return redirect(url_for('.detail',job_id=prior.id),code=303)
        if source.state!='review':abort(409)
        job=OpenAlexJob(kind='clean_apply',actor=int(current_user.id),params={'source_job':source.id,'plan_sha256':digest(p)},snapshot={'plan':deepcopy(p)})
        return enqueue(job)


@blueprint.get('/jobs/<job_id>/backup')
def backup(job_id):
    job=get_job(job_id)
    if job.kind!='clean_apply' or not job.result.get('backup'):abort(404)
    if job.snapshot['plan']['kind']=='lot':path=Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'maintenance-backups'/(job.id+'.zip')
    else:
        from .duplicates import backup_path
        path=backup_path(job.id)
    from .duplicates import sha256_file
    if path.is_symlink() or not path.is_file() or sha256_file(path)!=job.result['backup']['sha256']:abort(409)
    return send_file(path,mimetype='application/zip',as_attachment=True,download_name='argiloteca-backup-'+job.id+'.zip',max_age=0)


@blueprint.post('/jobs/<job_id>/finish-purge')
def finish_purge(job_id):
    job=get_job(job_id)
    if job.kind!='clean_apply' or job.actor!=int(current_user.id):abort(403)
    if job.state!='failed' or not (job.result.get('purge',{}).get('phase')=='cleanup' or job.result.get('raw_deletion',{}).get('phase')=='cleanup'):abort(409)
    with job_lock(job.id) as locked:
        if not locked:abort(409)
        job.result={k:v for k,v in job.result.items() if k!='error'};job.state='queued'
        return enqueue(job)


@blueprint.app_template_filter('zip_labels')
def zip_labels(values,labels):return list(zip(values,labels))


@blueprint.context_processor
def maintenance_context():
    labels={
      'purge_published':('Excluir publicação definitivamente','Permanently delete publication'),
      'delete_draft':('Excluir rascunho definitivamente','Permanently delete draft'),
      'withdraw_record':('Retirar publicação','Withdraw publication'),'restore_record':('Restaurar publicação','Restore publication'),
      'remove_community':('Remover da comunidade','Remove community membership'),
      'remove_connection':('Remover conexão científica','Remove scientific connection'),
      'delete_raw':('Excluir arquivos RAW','Delete RAW files'),
      'remove_drx_many':('Remover vínculos DRX selecionados','Remove selected DRX links'),
      'remove_orcid':('Remover vínculo ORCID','Remove ORCID association'),
      'remove_drx':('Remover associação DRX','Remove DRX association'),
      'clear_coordinates':('Remover coordenadas selecionadas','Remove selected coordinates'),
      'exclude_candidates':('Excluir linhas desta revisão','Delete rows from this review'),
      'archive_job':('Arquivar tarefa do histórico','Archive history task'),'restore_job':('Restaurar tarefa no histórico','Restore history task'),
      'delete_job':('Excluir tarefa definitivamente','Permanently delete task'),
      'archive_lot':('Arquivar lote no Mac','Archive batch on Mac'),'restore_lot':('Restaurar lote no Mac','Restore batch on Mac'),
      'delete_lot':('Excluir lote definitivamente','Permanently delete batch')}
    return {'clean_label':lambda key:t(*labels.get(key,(key,key)))}


from .bulk_maintenance import register as register_bulk_maintenance
register_bulk_maintenance(blueprint)
