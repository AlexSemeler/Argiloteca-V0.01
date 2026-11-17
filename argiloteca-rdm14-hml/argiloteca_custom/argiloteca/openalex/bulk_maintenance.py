"""Local, actor-bound bulk previews over the existing audited maintenance engine."""
from copy import deepcopy
import json
from flask import abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from invenio_db import db
from invenio_pidstore.errors import PIDDoesNotExistError
from .adapters import digest
from .models import OpenAlexJob
from .service import actor_identity, job_lock
from .views import t, get_job
from . import maintenance as clean

LIMIT = 100


def enabled():
    return bool(current_app.config.get('ARGILOTECA_ADMIN_ONTOLOGY_ENABLED'))


def serializer():
    return URLSafeTimedSerializer(current_app.secret_key, salt='argiloteca-local-bulk-v1')


def token(kind, target, **extra):
    return serializer().dumps(dict(kind=kind, target=str(target), actor=int(current_user.id), **extra))


def read_choices(values, actor):
    if not values or len(values) > LIMIT:
        raise ValueError(t('Selecione entre 1 e 100 itens desta página.', 'Select between 1 and 100 items on this page.'))
    result=[];seen=set()
    for value in values:
        if len(value)>4096:raise ValueError('Seleção inválida / Invalid selection')
        try: item=serializer().loads(value, max_age=3600)
        except (BadSignature, SignatureExpired):raise ValueError(t('A seleção expirou ou foi alterada. Recarregue a lista.', 'Selection expired or changed. Reload the list.')) from None
        if item.get('actor') != int(actor):raise ValueError('Seleção de outro responsável / Selection belongs to another actor')
        key=digest(item)
        if key not in seen:result.append(item);seen.add(key)
    return result


def specification(item, operation):
    kind=item['kind']
    if kind=='job' and operation in {'delete','archive'}:
        return dict(kind='job',target=item['target'],action='delete_job' if operation=='delete' else 'archive_job')
    if kind=='import_row':
        if operation=='exclude':return dict(kind='job',target=item['target'],action='exclude_candidates',selection=json.dumps([item['row_key']]))
        if operation=='delete':
            if not item.get('native_id'):raise ValueError(t('O item ainda não foi importado. Use Excluir desta revisão.','Item has not been imported yet. Use Delete from this review.'))
            return specification(dict(kind='record',target=item['native_id'],record_kind=item['record_kind']),operation)
    if kind=='record' and operation=='delete':
        record_kind=item.get('record_kind')
        if record_kind not in {'published','draft'}:raise ValueError('Tipo de registro inválido / Invalid record type')
        return dict(kind='record',target=item['target'],action='purge_published' if record_kind=='published' else 'delete_draft',record_kind=record_kind)
    if kind=='drx_link' and operation=='unlink':
        return dict(kind='record',target=item['target'],action='remove_drx',record_kind='published',selection=item['raw_id'])
    if kind=='orcid' and operation=='unlink':
        return dict(kind='record',target=item['target'],action='remove_orcid',record_kind=item['record_kind'],selection=json.dumps(item['occurrence'],sort_keys=True))
    raise ValueError(t('A operação não corresponde aos itens selecionados.', 'Operation does not match the selected items.'))


def grouped_specs(choices, operation):
    if operation=='delete_raw':
        if any(item['kind'] not in {'drx_raw','drx_link'} for item in choices):raise ValueError('Seleção RAW inválida / Invalid RAW selection')
        ids=sorted({item['target'] if item['kind']=='drx_raw' else item['raw_id'] for item in choices})
        return [dict(kind='raw',target='selected-raws',action='delete_raw',selection=json.dumps(ids))]
    specs=[];seen={}
    expanded=[]
    for item in choices:
        if item['kind']=='drx_raw' and operation=='unlink':
            from ..scientific.drx_links import DRXRecordLink
            links=DRXRecordLink.query.filter_by(raw_id=item['target']).filter(DRXRecordLink.state!='removed').all()
            if not links:raise ValueError(t('Um RAW selecionado não tem vínculo ativo. Abra Registros e dados DRX para escolher os vínculos existentes.','A selected RAW has no active link. Open Records and DRX data to select existing links.'))
            expanded.extend(dict(kind='drx_link',target=link.record_id,raw_id=link.raw_id) for link in links)
        else:expanded.append(item)
    if len(expanded)>LIMIT:raise ValueError(t('A seleção envolve mais de 100 vínculos. Divida a operação.','The selection involves more than 100 links. Split the operation.'))
    for item in expanded:
        spec=specification(item,operation)
        key=(spec['kind'],spec['target'],spec['action'],spec.get('record_kind',''))
        if key in seen:
            prior=specs[seen[key]]
            if spec['action']=='remove_orcid':
                occurrences=json.loads(prior['selection'])
                choice=json.loads(spec['selection'])
                if choice not in occurrences:occurrences.append(choice)
                prior['selection']=json.dumps(occurrences,sort_keys=True)
            elif spec['action']=='exclude_candidates':
                keys=json.loads(prior['selection']);keys+=json.loads(spec['selection']);prior['selection']=json.dumps(sorted(set(keys)))
            elif spec['action']=='remove_drx':
                if spec['selection'] not in prior['raw_ids']:prior['raw_ids'].append(spec['selection'])
            continue
        if spec['action']=='remove_orcid':spec['selection']=json.dumps([json.loads(spec['selection'])],sort_keys=True)
        if spec['action']=='remove_drx':spec['raw_ids']=[spec['selection']]
        seen[key]=len(specs);specs.append(spec)
    for spec in specs:
        if 'raw_ids' in spec:
            spec['action']='remove_drx_many';spec['selection']=json.dumps(sorted(spec.pop('raw_ids')))
    return specs


def author_token(row):
    if not row.get('rid') or not row.get('orcid') or row.get('kind') not in {'published','draft'}:return ''
    return token('orcid',row['rid'],record_kind=row['kind'],occurrence={'slot':row['slot'],'creator_sha256':digest(json.loads(row['creator']))})


def raw_token(row):
    return token('drx_raw',row['id'])


def effect(plan):
    translations={
      'delete_raw':'Delete the selected anonymous RAW binaries and their copies in the DRX module after backup verification. Remove all active associations of these files. Preserve records, historical results, private originals and backups.',
      'purge_published':'Permanently delete this published version, metadata, revisions and exclusive files after backup verification. This interface cannot restore it. Backups, audit and reserved identifiers remain. Shared files and external DOIs are preserved.',
      'delete_draft':'Permanently delete this draft and its exclusive files after backup verification. Any existing publication remains.',
      'delete_job':'Permanently delete this history task and its snapshot. Imported records, original source files and identity claims remain.',
      'archive_job':'Hide this task from current lists. Its history, provenance and imported records remain; it can be restored.',
      'exclude_candidates':'Exclude selected rows from this review and future import selections through it. Preserve original files, existing imported records and backed-up history.',
      'remove_orcid':'Remove only the ORCID identifier from the selected authorship occurrences. Preserve the authors, other identifiers and publications.',
      'remove_drx_many':'Remove only selected DRX associations from this record. Preserve RAW files, curves, analyses and the record.'}
    return t(plan['effect'].split(' / ')[0],translations.get(plan['action'],plan['effect']))


def register(blueprint):
    @blueprint.app_context_processor
    def bulk_context():
        return dict(bulk_enabled=enabled(),bulk_token=token,bulk_author_token=author_token,bulk_raw_token=raw_token,bulk_effect=effect,bulk_csrf=generate_csrf,bulk_t=t)

    @blueprint.post('/bulk/preview')
    def bulk_preview():
        if not enabled():abort(404)
        try:
            values=[request.form['single']] if request.form.get('single') else request.form.getlist('bulk_selected')
            choices=read_choices(values,current_user.id)
            reason=request.form.get('reason',''); operation=request.form.get('operation','')
            if not 5<=len(reason.strip())<=500:raise ValueError(t('Informe uma justificativa de 5 a 500 caracteres.', 'Enter a reason between 5 and 500 characters.'))
            entries=[]
            for spec in grouped_specs(choices,operation):
                try:
                    plan=clean.plan(actor_identity(current_user.id),current_user.id,reason=reason,**spec)
                    entries.append(dict(plan=plan,error=''))
                except (ValueError, PIDDoesNotExistError) as exc:
                    db.session.rollback();entries.append(dict(plan=None,error=str(exc),target=spec['target']))
            parent=OpenAlexJob(kind='clean_bulk_preview',state='review',actor=int(current_user.id),params={'operation':operation},snapshot={})
            db.session.add(parent);db.session.flush()
            for entry in entries:
                if entry['plan']:
                    child=OpenAlexJob(kind='clean_preview',state='review',actor=int(current_user.id),params={'bulk_parent':parent.id},snapshot={'plan':entry['plan']})
                    db.session.add(child);db.session.flush();entry['preview_id']=child.id
            parent.snapshot={'entries':deepcopy(entries)};db.session.commit()
            return redirect(url_for('.bulk_detail',job_id=parent.id,ln=t('pt','en')),code=303)
        except ValueError as exc:
            db.session.rollback();flash(str(exc),'error');return render_template('semantic-ui/argiloteca/admin_bulk_error.html',title=t('Revisar seleção','Review selection'),error=str(exc)),422

    @blueprint.get('/bulk/<job_id>')
    def bulk_detail(job_id):
        if not enabled():abort(404)
        parent=get_job(job_id)
        if parent.kind!='clean_bulk_preview':abort(404)
        entries=parent.snapshot['entries']
        results={row.params['source_job']:row for row in OpenAlexJob.query.filter_by(kind='clean_apply').filter(OpenAlexJob.params['bulk_parent'].as_string()==parent.id)}
        eligible=[entry for entry in entries if entry.get('plan') and not entry['plan']['blockers']]
        return render_template('semantic-ui/argiloteca/admin_bulk_preview.html',title=t('Prévia da seleção','Selection preview'),job=parent,entries=entries,results=results,
            eligible=eligible,permanent=any(entry['plan']['permanent'] for entry in eligible),plan_sha256=digest(parent.snapshot))

    @blueprint.post('/bulk/<job_id>/apply')
    def bulk_apply(job_id):
        if not enabled():abort(404)
        parent=get_job(job_id)
        if parent.kind!='clean_bulk_preview' or parent.actor!=int(current_user.id):abort(403)
        if request.form.get('confirm')!='yes' or request.form.get('plan_sha256')!=digest(parent.snapshot):abort(409)
        eligible=[entry for entry in parent.snapshot['entries'] if entry.get('plan') and not entry['plan']['blockers']]
        if not eligible:abort(409)
        if any(entry['plan']['permanent'] for entry in eligible) and request.form.get('permanent_confirmation','').strip()!='EXCLUIR':abort(409)
        with job_lock(parent.id) as locked:
            if not locked:abort(409)
            db.session.refresh(parent)
            if parent.state=='completed':return redirect(url_for('.bulk_detail',job_id=parent.id,ln=t('pt','en')),code=303)
            if parent.state!='review' or digest(parent.snapshot)!=request.form['plan_sha256']:abort(409)
            jobs=[]
            for entry in eligible:
                source=get_job(entry['preview_id'])
                if source.actor!=parent.actor or source.kind!='clean_preview' or source.state!='review' or source.params.get('bulk_parent')!=parent.id or digest(source.snapshot['plan'])!=digest(entry['plan']):abort(409)
                child=OpenAlexJob(kind='clean_apply',actor=parent.actor,params={'source_job':source.id,'plan_sha256':digest(entry['plan']),'bulk_parent':parent.id},snapshot={'plan':deepcopy(entry['plan'])})
                db.session.add(child);jobs.append(child)
            parent.state='completed';db.session.add(parent);db.session.commit()
        from .tasks import run
        for job in jobs:
            try:run.delay(job.id)
            except Exception:current_app.logger.warning('Bulk maintenance pending journal recovery: %s',job.id)
        return redirect(url_for('.bulk_detail',job_id=parent.id,ln=t('pt','en')),code=303)
