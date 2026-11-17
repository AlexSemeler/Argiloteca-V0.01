"""Native administrator boundary for knowledge ingestion and review."""
import json
import hashlib
import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from celery import shared_task
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_file, url_for
from flask_babel import get_locale
from flask_login import current_user
from flask_wtf.csrf import generate_csrf, validate_csrf
from wtforms.validators import ValidationError
from billiard.exceptions import SoftTimeLimitExceeded

from . import batch_sync
from .knowledge import Library, pdf_limits, MAX_PAGES, EXTRACT_BATCH_PAGES

bp=Blueprint('argiloteca_knowledge',__name__,url_prefix='/administration/argiloclay')


def library():
    index=os.getenv('ARGILOCLAY_SYNC_INDEX')
    if not index: abort(503)
    root=os.getenv('ARGILOCLAY_LIBRARY_ROOT',str(Path(current_app.instance_path)/'argiloclay-library'))
    return Library(root,index)


def t(pt,en): return pt if get_locale().language=='pt' else en


@bp.before_request
def protect():
    from ..scientific.restricted_review import can_review
    if not can_review(): abort(403)
    if request.method=='POST':
        if request.content_length and request.content_length>52*1024*1024: abort(413)
        try: validate_csrf(request.form.get('csrf_token'))
        except ValidationError: abort(400,description=t('Sessão expirada. Recarregue a página.','Session expired. Reload the page.'))


@bp.after_request
def private(response):
    response.headers['Cache-Control']='private, no-store';response.headers['X-Robots-Tag']='noindex, nofollow'
    return response


@bp.context_processor
def context():
    labels={'idle':('Aguardando primeira atualização','Awaiting first refresh'),'running':('Em processamento','Processing'),
            'restart_required':('Checkpoint desatualizado · reinicie a coleta','Outdated checkpoint · restart collection'),
            'paused':('Pausada','Paused'),'failed':('Interrompida: pode retomar','Interrupted: resumable'),
            'ok':('Atualizado','Up to date'),'queued':('Na fila','Queued'),'extracting':('Extraindo páginas','Extracting pages'),
            'review':('Aguardando revisão','Awaiting review'),'approved':('Aprovado: indexação pendente','Approved: indexing pending'),
            'indexed':('Indexado','Indexed'),'withdrawn':('Retirado das respostas','Withdrawn from answers')}
    labels.update({'extraction_batch':('Lote de páginas extraído','Page batch extracted'),'extract_resume':('Retomada da extração','Extraction resumed'),'upload':('Envio de PDF','PDF upload'),'extracted':('Extração concluída','Extraction completed'),
                   'approve_pages':('Aprovação de páginas','Page approval'),'withdraw':('Retirada de fonte','Source withdrawal'),
                   'restore_for_review':('Restauração para revisão','Restoration for review'),'correct_page':('Correção do texto extraído','Extracted text correction'),
                   'index_requested':('Indexação solicitada','Indexing requested'),'index_approved':('Indexação das fontes aprovadas','Approved source indexing'),'recover_index':('Recuperação do índice','Index recovery'),
                   'sync_start':('Atualização do acervo','Repository refresh'),'sync_resume':('Retomada da atualização','Refresh resumed'),
                   'sync_restart':('Reinício da atualização','Refresh restarted'),'access_change':('Alteração de acesso','Access changed')})
    def extraction_error(raw):
        try:detail=json.loads(raw);code=detail.get('code')
        except (ValueError,TypeError,AttributeError):detail={};code='extraction_failed'
        messages={
            'page_limit':('O documento tem {total_pages} páginas. O limite é {limit}.','The document has {total_pages} pages. The limit is {limit}.'),
            'page_count_unavailable':('Não foi possível identificar o número de páginas do PDF.','Could not determine the PDF page count.'),
            'original_changed':('O arquivo difere do original recebido. Confira ou envie uma nova versão.','The file differs from the uploaded original. Check it or upload a new version.'),
            'page_byte_limit':('Uma página excedeu o limite de texto extraído. Confira o original.','A page exceeded the extracted text limit. Check the original.'),
            'page_text_limit':('Uma página excedeu o limite de texto. Confira o original.','A page exceeded the text limit. Check the original.'),
            'parser_timeout':('A leitura de uma página excedeu o tempo disponível. As páginas concluídas foram preservadas.','A page exceeded the reading time limit. Completed pages were preserved.'),
            'parser_failed':('O leitor de PDF não conseguiu processar uma página. Confira se o arquivo exige senha ou apresenta problemas.','The PDF reader could not process a page. Check whether the file needs a password or has issues.'),
            'worker_interrupted':('O processamento foi interrompido. A retomada preserva as páginas concluídas.','Processing was interrupted. Resuming preserves completed pages.'),
            'extraction_failed':('Não foi possível concluir a extração. Retome o processamento das páginas pendentes.','Could not complete extraction. Resume processing the remaining pages.')}
        message=t(*messages.get(code,messages['extraction_failed']))
        if code=='page_limit':
            message=message.format(total_pages=detail.get('total_pages','—'),limit=detail.get('limit',MAX_PAGES))
        return message
    return {'kt':t,'csrf_token':generate_csrf,'knowledge_extraction_error':extraction_error,'knowledge_max_pages':MAX_PAGES,'knowledge_batch_pages':EXTRACT_BATCH_PAGES,'knowledge_label':lambda value:t(*labels.get(value,(value,value)))}


@bp.url_defaults
def locale(endpoint,values): values.setdefault('ln',get_locale().language)


@bp.get('/')
def index():
    lib=library()
    try: page=max(1,min(10000,int(request.args.get('page',1))))
    except ValueError: abort(400)
    q=request.args.get('q','')[:100];rows,total=lib.listing(page,q)
    status=batch_sync.state(lib.index)
    with lib.connect() as c:
        audits=[dict(row) for row in c.execute('SELECT at,actor,action,doc FROM audit ORDER BY id DESC LIMIT 25')]
    jobfile=lib.index.with_suffix('.library-status.json')
    index_status=json.loads(jobfile.read_text()) if jobfile.exists() else {'state':'idle'}
    backups=[]
    directory=lib.index.parent/'versions'
    if directory.exists():
        backups=[{'name':p.name,'sha256':batch_sync.sha(p)} for p in sorted(directory.glob('*.sqlite3'),key=lambda p:p.stat().st_mtime,reverse=True)[:10]]
    return render_template('semantic-ui/argiloteca/admin_knowledge.html',rows=rows,total=total,page=page,pages=max(1,(total+19)//20),q=q,status=status,backups=backups,audits=audits,index_status=index_status)


@bp.post('/sync')
def sync():
    from .tasks import sync_public_records
    lib=library();action=request.form.get('action')
    if action not in ('start','resume','restart'): abort(400)
    try:
        value=batch_sync.start(lib.index,str(current_user.get_id()),int(request.form.get('batch_size',100)),restart=action=='restart')
        if value.get('state')=='restart_required':
            flash(t('O índice foi alterado desde este checkpoint. Use “Reiniciar coleta preservando o índice”; o trabalho anterior será arquivado com backup.','The index changed since this checkpoint. Use “Restart collection preserving index”; previous work will be archived with a backup.'),'warning')
            return redirect(url_for('.index',_anchor='admin-feedback'))
        sync_public_records.delay(value['run_id'])
        with lib.connect() as c: lib.audit(c,current_user.get_id(),'sync_'+action)
        flash(t('Atualização agendada. Os checkpoints permitem retomar o processamento.','Refresh queued. Checkpoints allow processing to resume.'),'success')
    except (ValueError,BlockingIOError): flash(t('Atualização ocupada ou parâmetros inválidos. Atualize o estado.','Refresh busy or invalid parameters. Refresh the status.'),'warning')
    return redirect(url_for('.index',_anchor='admin-feedback'))


@shared_task(ignore_result=True,soft_time_limit=210,time_limit=230,autoretry_for=(SoftTimeLimitExceeded,),retry_backoff=5,retry_kwargs={'max_retries':20})
def extract_document(doc,version,ocr=False):
    lib=library()
    # Page checkpoints persist. Next delivery resumes only missing pages.
    try:
        result=lib.extract(doc,version,ocr)
        if result and result.get('state')=='extracting':
            extract_document.apply_async(args=[doc,version,ocr],countdown=1)
        return result
    except Exception:
        current_app.logger.warning('ArgiloClay PDF extraction failed for %s v%s',doc,version)
        raise


@shared_task(ignore_result=True,soft_time_limit=210,time_limit=230,autoretry_for=(BlockingIOError,),retry_backoff=5,retry_kwargs={'max_retries':8})
def index_documents(actor):
    lib=library();path=lib.index.with_suffix('.library-status.json')
    value={'state':'running','actor':actor,'started_at':batch_sync.now()}
    batch_sync.atomic_json(path,value)
    try:
        saved=lib.index_approved(actor)
        value.update(state='ok',backup=saved,completed_at=batch_sync.now())
        batch_sync.atomic_json(path,value)
        return value
    except Exception as exc:
        value.update(state='queued' if isinstance(exc,BlockingIOError) else 'failed',error_type=type(exc).__name__)
        batch_sync.atomic_json(path,value)
        raise


@bp.post('/upload')
def upload():
    file=request.files.get('pdf')
    if not file: abort(400)
    lib=library();replace=request.form.get('replace') or None
    rid=request.form.get('record_id','').strip()
    if rid:
        from .service import public_record
        if not public_record(rid): abort(400,description=t('O vínculo exige um registro publicado e público.','The link requires a public published record.'))
    try:
        result=lib.upload(file.stream,request.form,current_user.get_id(),replace)
        if not result['duplicate']: extract_document.delay(result['doc'],result['version'],request.form.get('ocr')=='yes')
        flash(t('Arquivo já cadastrado; duplicação evitada.','File already registered; duplicate prevented.') if result['duplicate'] else t('PDF recebido. A extração está na fila e requer revisão.','PDF received. Extraction is queued and requires review.'),'success')
        return redirect(url_for('.detail',doc=result['doc'],version=result['version']))
    except ValueError as exc:
        flash(t('Envio recusado. Confira o PDF, os campos obrigatórios e o limite de 50 MiB.','Upload rejected. Check the PDF, required fields and 50 MiB limit.'),'error')
        return redirect(url_for('.index',_anchor='admin-feedback'))


@bp.get('/documents/<doc>')
def detail(doc):
    lib=library()
    try:
        item=lib.get(doc,request.args.get('version'));page=max(1,int(request.args.get('page',1)))
    except (KeyError,ValueError): abort(404)
    selected=next((p for p in item['pages'] if p['page']==page),None)
    with lib.connect() as c:
        active_version=c.execute('SELECT active_version FROM documents WHERE id=?',(doc,)).fetchone()[0]
        similar=[dict(r) for r in c.execute("SELECT doc,version FROM versions WHERE doc!=? AND (lower(json_extract(metadata,'$.title'))=lower(?) OR (?!='' AND lower(json_extract(metadata,'$.doi'))=lower(?))) LIMIT 10",(doc,item['metadata']['title'],item['metadata']['doi'],item['metadata']['doi']))]
    reviewable=[p for p in item['pages'] if len(p['text'].strip())>=80]
    blocked=[p for p in item['pages'] if len(p['text'].strip())<80]
    approved=sum(bool(p['approved'] and p['numeric_review']) for p in item['pages'])
    can_review=item['version']==active_version and item['state'] in ('review','approved','indexed')
    can_index=can_review and item['metadata']['access']=='public' and approved>0 and item['state'] in ('approved','indexed')
    jobfile=lib.index.with_suffix('.library-status.json')
    index_status=json.loads(jobfile.read_text()) if jobfile.exists() else {'state':'idle'}
    index_receipt={'pages':0,'passages':0,'completed_at':None}
    if can_index:
        expected={p['page']:hashlib.sha256(p['text'].encode()).hexdigest() for p in item['pages'] if p['approved'] and p['numeric_review']}
        with batch_sync.database(lib.index) as c:
            rows=c.execute("SELECT json_extract(metadata,'$.page'),json_extract(metadata,'$.page_sha256'),count(*) FROM docs WHERE json_extract(metadata,'$.library_id')=? AND json_extract(metadata,'$.library_version')=? AND json_extract(metadata,'$.sha256')=? GROUP BY 1,2",(doc,item['version'],item['sha'])).fetchall()
        matching=[row for row in rows if expected.get(row[0])==row[1]]
        index_receipt.update(pages=len({row[0] for row in matching}),passages=sum(row[2] for row in matching))
        if matching:index_receipt['completed_at']=index_status.get('completed_at')
    return render_template('semantic-ui/argiloteca/admin_knowledge_detail.html',item=item,selected=selected,similar=similar,reviewable=reviewable,blocked=blocked,approved_pages=approved,can_review=can_review,can_index=can_index,index_status=index_status,index_receipt=index_receipt)


@bp.post('/documents/<doc>/action')
def document_action(doc):
    lib=library()
    try:
        version=int(request.form['version']);action=request.form.get('action');actor=current_user.get_id()
        if action=='approve':
            if request.form.get('confirm_review')!='yes': raise ValueError('Review required')
            pages=request.form.getlist('pages')
            if request.form.get('scope')=='usable':
                # Recompute on the server. Blank/short pages remain unapproved.
                pages=[p['page'] for p in lib.get(doc,version)['pages'] if len(p['text'].strip())>=80]
            lib.review(doc,version,pages,actor,numeric=request.form.get('confirm_numeric')=='yes')
        elif action=='withdraw':
            if request.form.get('confirm_withdraw')!='yes': raise ValueError('Confirmation required')
            lib.withdraw(doc,version,actor)
        elif action=='restore': lib.restore_document(doc,version,actor)
        elif action=='access':
            access=request.form.get('access')
            if access not in ('public','restricted'): raise ValueError('Invalid access')
            with lib.connect() as c:
                row=c.execute('SELECT metadata FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone()
                if not row: raise KeyError(doc)
                meta=json.loads(row[0]);previous=meta['access'];meta['access']=access
                c.execute("UPDATE versions SET metadata=?,state='review' WHERE doc=? AND version=?",(json.dumps(meta),doc,version))
                c.execute('UPDATE pages SET approved=0,numeric_review=0 WHERE doc=? AND version=?',(doc,version))
                lib.audit(c,actor,'access_change',doc,{'version':version,'previous':previous,'proposed':access})
            lib.publish_access()
        elif action=='extract':
            extract_document.delay(doc,version,request.form.get('ocr')=='yes')
            with lib.connect() as c:lib.audit(c,actor,'extract_resume',doc,{'version':version,'ocr':request.form.get('ocr')=='yes'})
        else: abort(400)
        if action=='approve':
            title=lib.get(doc,version)['metadata']['title'][:250]
            message=t('Páginas revisadas aprovadas. Documento: “{title}” · {count} páginas. Use “Indexar páginas aprovadas no ArgiloClay” para disponibilizar o conteúdo.','Reviewed pages approved. Document: “{title}” · {count} pages. Use “Index approved pages in ArgiloClay” to make the content available.').format(title=title,count=len(set(int(p) for p in pages)))
        else:message=t('Ação registrada. Confira a situação antes de indexar.','Action recorded. Check the status before indexing.')
        flash(message,'success')
    except (ValueError,KeyError,BlockingIOError):
        flash(t('Não foi possível concluir. Confira a versão, as páginas selecionadas e as confirmações.','Could not complete. Check the version, selected pages and confirmations.'),'error')
        return redirect(url_for('.detail',doc=doc,_anchor='admin-feedback'))
    return redirect(url_for('.detail',doc=doc,version=version,page=request.form.get('pages',1),_anchor='admin-feedback'))


@bp.post('/documents/<doc>/index')
def index_document(doc):
    if request.form.get('confirm')!='yes': abort(400)
    lib=library()
    try:
        version=int(request.form['version']);item=lib.get(doc,version)
        with lib.connect() as c:
            active=c.execute('SELECT active_version FROM documents WHERE id=?',(doc,)).fetchone()[0]
            pages=[p['page'] for p in item['pages'] if p['approved'] and p['numeric_review']]
            if active!=version or item['state'] not in ('approved','indexed') or item['metadata']['access']!='public' or not pages:
                abort(409,description=t('Aprove páginas da versão pública atual antes de indexar.','Approve pages of the current public version before indexing.'))
            lib.audit(c,current_user.get_id(),'index_requested',doc,{'version':version,'pages':pages,'scope':'approved_public_library'})
        # Reuse the atomic library rebuild and its backup/recovery mechanism.
        index_documents.delay(str(current_user.get_id()))
    except (ValueError,KeyError): abort(400)
    flash(t('Indexação agendada com backup automático. Documento: “{title}” · {count} páginas aprovadas. Atualize o andamento para conferir a conclusão.','Indexing queued with automatic backup. Document: “{title}” · {count} approved pages. Refresh progress to check completion.').format(title=item['metadata']['title'][:250],count=len(pages)),'success')
    return redirect(url_for('.detail',doc=doc,version=version,_anchor='admin-feedback'))


@bp.post('/documents/<doc>/correct')
def correct_page(doc):
    lib=library()
    try:
        version=int(request.form['version']);page=int(request.form['page']);text=request.form['text']
        if len(text)>100000: abort(413)
        with lib.connect() as c:
            state=c.execute('SELECT state FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone()
            if not state or state[0] not in ('review','approved','indexed'):abort(409,description=t('Aguarde a conclusão da extração antes de corrigir páginas.','Wait for extraction to finish before correcting pages.'))
            row=c.execute('SELECT text FROM pages WHERE doc=? AND version=? AND page=?',(doc,version,page)).fetchone()
            if not row: abort(404)
            # Store the previous extraction in the immutable audit trail.
            lib.audit(c,current_user.get_id(),'correct_page',doc,{'version':version,'page':page,'previous_text':row[0],'new_text':text})
            c.execute('UPDATE pages SET text=?,approved=0,numeric_review=0,reviewer=NULL,reviewed_at=NULL WHERE doc=? AND version=? AND page=?',(text,doc,version,page))
            c.execute("UPDATE versions SET state='review' WHERE doc=? AND version=?",(doc,version))
        lib.publish_access()
        flash(t('Correção salva. Confira novamente e aprove a página antes de indexar.','Correction saved. Check again and approve the page before indexing.'),'success')
    except (ValueError,KeyError): abort(400)
    return redirect(url_for('.detail',doc=doc,version=version,page=page,_anchor='admin-feedback'))


@bp.post('/index')
def index_reviewed():
    if request.form.get('confirm')!='yes': abort(400)
    index_documents.delay(str(current_user.get_id()))
    flash(t('Indexação das páginas aprovadas agendada, com backup automático.','Approved page indexing queued with automatic backup.'),'success')
    return redirect(url_for('.index',_anchor='admin-feedback'))


@bp.post('/recover')
def recover():
    if request.form.get('confirm')!='yes': abort(400)
    try:
        library().restore_index(request.form['name'],request.form['sha256'],current_user.get_id())
        flash(t('Índice anterior recuperado. As restrições atuais continuam em vigor.','Previous index recovered. Current access restrictions remain in effect.'),'success')
    except (KeyError,ValueError,BlockingIOError): abort(409)
    return redirect(url_for('.index',_anchor='admin-feedback'))


@bp.get('/documents/<doc>/original/<int:version>')
def original(doc,version):
    lib=library()
    try: lib.get(doc,version)
    except KeyError: abort(404)
    response=send_file(lib.path(doc,version),mimetype='application/pdf',as_attachment=True,download_name='source.pdf')
    response.headers['X-Content-Type-Options']='nosniff';return response


def page_image(lib,doc,version,page):
    if batch_sync.sha(lib.path(doc,version))!=lib.get(doc,version)['sha']:
        abort(409)
    with tempfile.TemporaryDirectory(dir=lib.root) as folder:
        dest=Path(folder)/'page'
        subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-scale-to','1200','-png',str(lib.path(doc,version)),str(dest)],capture_output=True,timeout=40,check=True,preexec_fn=pdf_limits)
        import io
        return send_file(io.BytesIO(dest.with_suffix('.png').read_bytes()),mimetype='image/png')


@bp.get('/documents/<doc>/image/<int:version>/<int:page>')
def image(doc,version,page):
    lib=library()
    try: item=lib.get(doc,version)
    except KeyError: abort(404)
    if not any(p['page']==page for p in item['pages']): abort(404)
    return page_image(lib,doc,version,page)


from .openalex_pdfs import register as register_openalex_pdfs
register_openalex_pdfs(bp)


def register(app):
    app.register_blueprint(bp)
    @app.get('/argiloclay/library/<doc>/<int:version>/<int:page>')
    def argiloclay_library_source(doc,version,page):
        lib=library()
        try:
            item=lib.get(doc,version)
            selected=next(p for p in item['pages'] if p['page']==page)
            source={'library_id':doc,'library_version':version,'sha256':item['sha'],'page':page,'page_sha256':__import__('hashlib').sha256(selected['text'].encode()).hexdigest(),'excerpt':selected['text']}
            if not lib.source_allowed(source,check_excerpt=False): abort(404)
        except (KeyError,StopIteration): abort(404)
        response=page_image(lib,doc,version,page);response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
