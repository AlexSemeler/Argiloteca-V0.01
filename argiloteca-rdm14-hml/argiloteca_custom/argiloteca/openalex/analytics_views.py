"""Admin statistics and native author ORCID review, on the protected blueprint."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
import csv
import io
import json
import re
from urllib.parse import urlencode

from flask import abort,current_app,flash,redirect,render_template,request,send_file,url_for
from flask_login import current_user
from invenio_db import db
from sqlalchemy.orm import defer

from .adapters import digest
from .analytics import connect,name_key,statistics
from .models import OpenAlexJob
from .orcid import normalize_orcid,backup_path
from .duplicates import sha256_file
from .service import job_lock
from .views import blueprint,enqueue,get_job,t

KINDS={'stats_scan','orcid_search','orcid_lookup','orcid_preview','orcid_apply'}


@contextmanager
def view_store(analysis):
    try:
        with connect(analysis) as connection:
            yield connection
    except (ValueError,sqlite3.Error):
        abort(409,description=t('Retrato indisponível. Atualize as estatísticas e autores.','Snapshot unavailable. Refresh statistics and authors.'))


def current_analysis():
    aid=request.values.get('analysis','')
    if aid:
        job=get_job(aid)
        if job.kind!='stats_scan' or job.state!='completed':abort(409)
        return job
    return OpenAlexJob.query.filter_by(kind='stats_scan',state='completed').order_by(OpenAlexJob.created.desc()).first()


def pagination():
    try:return max(1,int(request.args.get('page',1)))
    except ValueError:abort(400)


def filters():
    result={'source_type':request.args.get('source_type','')[:80],'subject':request.args.get('subject','').strip()[:150]}
    for key in ('primary_topic','subfield','field','domain'):
        value=request.args.get(key,'')
        pattern=r'https://openalex.org/T\d+' if key=='primary_topic' else r'https://openalex.org/'+key+r's/\d+'
        if value and not re.fullmatch(pattern,value):abort(400)
        result[key]=value
    version=request.args.get('enrichment','current')
    if version not in ('current','none') and not re.fullmatch(r'(?:preview:)?[a-f0-9]{32}',version):abort(400)
    result['enrichment']=version
    for key in ('year_from','year_to'):
        try:result[key]=int(request.args[key]) if request.args.get(key) else None
        except ValueError:abort(400)
        if result[key] is not None and not 1<=result[key]<=9999:abort(400)
    if result['year_from'] and result['year_to'] and result['year_from']>result['year_to']:abort(400)
    return result


@blueprint.get('/statistics/')
def statistics_index():
    if current_app.config.get('ARGILOTECA_POPULATION_ENABLED') and request.args.get('scope') != 'openalex':
        return redirect(url_for('argiloteca_population.index'),code=303)
    analysis=current_analysis();data=None
    if analysis:
        with view_store(analysis) as c:data=statistics(c,**filters())
    busy=OpenAlexJob.query.filter_by(kind='stats_scan').filter(OpenAlexJob.state.in_(['running','queued'])).order_by(OpenAlexJob.created.desc()).first()
    return render_template('semantic-ui/argiloteca/admin_openalex_statistics.html',title=t('Estatísticas OpenAlex','OpenAlex statistics'),
        analysis=analysis,data=data,filters=filters(),busy_job=busy,export_filters={**filters(),'enrichment':(data['enrichment_version'] or 'none') if data else 'none'},filter_link=lambda changes:url_for('.statistics_index',analysis=analysis.id,scope='openalex',**{**filters(),**changes,'enrichment':data['enrichment_version'] or 'none'}))


@blueprint.post('/statistics/refresh')
def statistics_refresh():
    with job_lock('statistics-enqueue') as locked:
        if not locked:abort(409)
        prior=OpenAlexJob.query.filter_by(kind='stats_scan').filter(OpenAlexJob.state.in_(['queued','running'])).first()
        if prior:return redirect(url_for('.orcid_job',job_id=prior.id),code=303)
        return enqueue(OpenAlexJob(kind='stats_scan',actor=int(current_user.id)))


@blueprint.get('/authors/')
def authors_index():
    if current_app.config.get('ARGILOTECA_POPULATION_ENABLED'):
        return redirect(url_for('argiloteca_population.authors',**request.args.to_dict()),code=303)
    analysis=current_analysis();rows=[];page=pagination();total=0;pages=1
    q=request.args.get('q','').strip()[:150];status=request.args.get('status','')
    if analysis:
        with view_store(analysis) as c:
            c.create_function('fold',1,name_key)
            where='WHERE fold(o.name) LIKE ?';params=['%'+name_key(q)+'%']
            having={'suggested':'HAVING suggestions>0','missing':'HAVING linked<occurrences'}.get(status,'')
            sql='''SELECT o.gid,min(o.name) name,count(*) occurrences,count(DISTINCT o.rid) records,
                sum(o.existing_orcid!='') linked,sum(EXISTS(SELECT 1 FROM candidates c WHERE c.occurrence=o.key)) suggestions
                FROM occurrences o '''+where+' GROUP BY o.gid '+having
            total=c.execute('SELECT count(*) FROM ('+sql+')',params).fetchone()[0]
            pages=max(1,(total+19)//20);page=min(page,pages)
            rows=[dict(r) for r in c.execute(sql+' ORDER BY suggestions DESC,records DESC,name LIMIT 20 OFFSET ?',[*params,(page-1)*20])]
    return render_template('semantic-ui/argiloteca/admin_openalex_authors.html',title=t('Autores e ORCID','Authors and ORCID'),
        analysis=analysis,rows=rows,page=page,pages=pages,total=total,q=q,status=status,detail=None)


@blueprint.get('/authors/<gid>')
def author_detail(gid):
    if not re.fullmatch('[0-9a-f]{32}',gid):abort(404)
    analysis=current_analysis()
    if not analysis:abort(404)
    page=pagination();search_job=None
    with view_store(analysis) as c:
        total=c.execute('SELECT count(*) FROM occurrences WHERE gid=?',(gid,)).fetchone()[0]
        if not total:abort(404)
        pages=max(1,(total+19)//20);page=min(page,pages)
        rows=[dict(r) for r in c.execute('SELECT * FROM occurrences WHERE gid=? ORDER BY rid,kind,slot LIMIT 20 OFFSET ?',(gid,(page-1)*20))]
        for row in rows:
            row['suggestions']=[json.loads(x[0]) for x in c.execute('SELECT body FROM candidates WHERE occurrence=? ORDER BY orcid',(row['key'],))]
        options={candidate['orcid']:candidate for row in rows for candidate in row['suggestions']}
    if request.args.get('search_job'):
        search_job=get_job(request.args['search_job'])
        if search_job.kind not in {'orcid_search','orcid_lookup'} or search_job.params.get('gid')!=gid or search_job.params.get('analysis')!=analysis.id:abort(404)
        if search_job.state=='review':
            options={x['orcid']:x for x in search_job.snapshot.get('candidates',[])}
    example=json.loads(rows[0]['creator'])['person_or_org']
    return render_template('semantic-ui/argiloteca/admin_openalex_authors.html',title=t('Revisar ORCID do autor','Review author ORCID'),
        analysis=analysis,rows=rows,page=page,pages=pages,total=total,detail=gid,options=options,search_job=search_job,
        example=example,registry_url='https://orcid.org/orcid-search/search?'+urlencode({'searchQuery':rows[0]['name']}))


@blueprint.post('/authors/<gid>/search')
def author_search(gid):
    analysis=current_analysis()
    if not analysis:abort(409)
    with view_store(analysis) as c:
        if not c.execute('SELECT 1 FROM occurrences WHERE gid=?',(gid,)).fetchone():abort(404)
    params={'analysis':analysis.id,'gid':gid}
    if request.form.get('orcid'):
        value=normalize_orcid(request.form['orcid'])
        if not value:abort(400,description=t('ORCID inválido, incluindo o dígito verificador.','Invalid ORCID, including checksum.'))
        params['orcid']=value;kind='orcid_lookup'
    else:
        for field in ('given','family','institution','doi'):
            value=request.form.get(field,'').strip()
            if len(value)>250 or any(ord(x)<32 for x in value):abort(400)
            params[field]=value
        if not params['given'] and not params['family']:abort(400)
        kind='orcid_search'
    return enqueue(OpenAlexJob(kind=kind,actor=int(current_user.id),params=params))


@blueprint.post('/authors/<gid>/preview')
def author_preview(gid):
    analysis=current_analysis();orcid=normalize_orcid(request.form.get('orcid'));keys=request.form.getlist('selected')
    if not analysis or not orcid or not keys or len(keys)>100 or len(set(keys))!=len(keys):abort(400)
    evidence_job=request.form.get('evidence_job','');evidence={'source':'Fonte coletada no mesmo registro','orcid':orcid,'occurrences':{}}
    with view_store(analysis) as c:
        for key in keys:
            row=c.execute('SELECT gid FROM occurrences WHERE key=?',(key,)).fetchone()
            if not row or row['gid']!=gid:abort(409)
            if not evidence_job:
                evidence['occurrences'][key]=[dict(x) for x in c.execute('SELECT source,body FROM candidates WHERE occurrence=? AND orcid=?',(key,orcid))]
            if not evidence_job and not c.execute('SELECT 1 FROM candidates WHERE occurrence=? AND orcid=?',(key,orcid)).fetchone():
                flash(t('O ORCID escolhido não foi coletado para uma das ocorrências. Consulte o registro ORCID e revise a associação.','The selected ORCID was not collected for one of the occurrences. Look up its ORCID record and review the association.'),'error')
                return redirect(url_for('.author_detail',gid=gid,analysis=analysis.id),code=303)
    if evidence_job:
        source=get_job(evidence_job)
        if source.kind not in {'orcid_search','orcid_lookup'} or source.state!='review' or source.actor!=int(current_user.id) or source.params.get('gid')!=gid or source.params.get('analysis')!=analysis.id:abort(409)
        candidate=next((x for x in source.snapshot.get('candidates',[]) if x['orcid']==orcid),None)
        if not candidate:abort(409)
        evidence={'source':'ORCID','job':source.id,'candidate':deepcopy(candidate),'fetched_at':source.snapshot['fetched_at']}
    return enqueue(OpenAlexJob(kind='orcid_preview',actor=int(current_user.id),params={'analysis':analysis.id,'gid':gid,'keys':keys,'orcid':orcid,'evidence':evidence}))


@blueprint.get('/authors/jobs/<job_id>')
def orcid_job(job_id):
    job=get_job(job_id)
    if job.kind not in KINDS:abort(404)
    if job.params.get('population_key') and job.kind in {'orcid_search','orcid_lookup'} and job.state in {'review','failed'}:
        return redirect(url_for('argiloteca_population.author',key=job.params['population_key'],analysis=job.params['analysis'],search_job=job.id),code=303)
    if job.kind=='stats_scan' and job.state=='completed':return redirect(url_for('.statistics_index',analysis=job.id))
    if job.kind in {'orcid_search','orcid_lookup'} and job.state=='review':
        return redirect(url_for('.author_detail',gid=job.params['gid'],analysis=job.params['analysis'],search_job=job.id))
    return render_template('semantic-ui/argiloteca/admin_openalex_orcid_job.html',title=t('Revisão de ORCID','ORCID review'),job=job,busy=job.state in {'queued','running'})


@blueprint.post('/authors/jobs/<job_id>/apply')
def orcid_apply(job_id):
    source=get_job(job_id)
    if source.kind!='orcid_preview' or source.actor!=int(current_user.id):abort(403)
    if request.form.get('confirm')!='yes' or request.form.get('plan_sha256')!=digest(source.snapshot):abort(409)
    note=request.form.get('review_note','').strip()
    if len(note)>2000 or any(ord(c)<32 and c not in '\n\r\t' for c in note):abort(400)
    review={'confirmed':True,'actor':int(current_user.id),'at':datetime.now(timezone.utc).isoformat(),'note':note}
    with job_lock('orcid-apply-'+source.id) as locked:
        if not locked:abort(409)
        prior=OpenAlexJob.query.filter_by(kind='orcid_apply').filter(OpenAlexJob.params['preview_job'].as_string()==source.id).first()
        if prior:return redirect(url_for('.orcid_job',job_id=prior.id),code=303)
        if source.state!='review':abort(409)
        return enqueue(OpenAlexJob(kind='orcid_apply',actor=int(current_user.id),snapshot=deepcopy(source.snapshot),
            params={'preview_job':source.id,'plan_sha256':digest(source.snapshot),'review':review}))


@blueprint.get('/authors/jobs/<job_id>/backup')
def orcid_backup(job_id):
    job=get_job(job_id);saved=job.result.get('backup');path=backup_path(job.id)
    if job.kind!='orcid_apply' or not saved:abort(404)
    if not path.is_file() or path.is_symlink() or sha256_file(path)!=saved['sha256']:abort(409)
    return send_file(path,as_attachment=True,mimetype='application/zip',download_name='orcid-backup-'+job.id+'.zip')


@blueprint.post('/authors/jobs/<job_id>/refresh-index')
def orcid_refresh_index(job_id):
    job=get_job(job_id)
    if job.kind!='orcid_apply' or job.state!='completed':abort(409)
    from .orcid import refresh
    refresh(job)
    return redirect(url_for('.orcid_job',job_id=job.id),code=303)


@blueprint.get('/statistics/export.csv')
def statistics_export():
    analysis=current_analysis()
    if not analysis:abort(404)
    with view_store(analysis) as c:
        data=statistics(c,**filters())
    stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['analysis',analysis.id,'enrichment',data['enrichment_version'] or 'none']);writer.writerow(['dimension','label','count','missing','denominator','share_percent'])
    for kind,rows in data.items():
        if not isinstance(rows,list):continue
        for row in rows:
            label=str(row['label']) if row.get('label') is not None else t('Não informado','Not provided')
            if label.startswith(('=','+','-','@','\t','\r')):label="'"+label
            writer.writerow([kind,label,row['n'],row.get('missing',''),row.get('denominator',''),row.get('share','')])
    response=current_app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv')
    response.headers['Content-Disposition']='attachment; filename=openalex-rankings.csv'
    return response


@blueprint.get('/statistics/metrics.csv')
def enrichment_metrics_export():
    analysis=current_analysis()
    if not analysis:abort(404)
    stream=io.StringIO();writer=csv.writer(stream)
    with view_store(analysis) as c:
        data=statistics(c,**filters())
        writer.writerow(['analysis',analysis.id,'enrichment',data['enrichment_version'] or 'none'])
        writer.writerow(['rid','title','doi','openalex','primary_topic','subfield','field','domain','fwci','citation_normalized_percentile','top_1_percent','top_10_percent','cited_by_count','counts_by_year','updated_date','collected_at','method','source_url','primary_topic_id','primary_topic_score','topics'])
        for row in c.execute('SELECT * FROM measures ORDER BY rid'):
            p=json.loads(row['payload']) if row['payload'] else {}
            topic=p.get('primary_topic') or {};pct=p.get('citation_normalized_percentile') or {}
            values=[row['rid'],row['title'],row['doi'],p.get('id') or row['oa_id'],topic.get('display_name'),*((topic.get(k) or {}).get('display_name') for k in ('subfield','field','domain')),p.get('fwci'),pct.get('value'),pct.get('is_in_top_1_percent'),pct.get('is_in_top_10_percent'),p.get('cited_by_count'),json.dumps(p['counts_by_year']) if p.get('counts_by_year') is not None else None,p.get('updated_date'),p.get('collected_at'),p.get('method'),p.get('source'),topic.get('id'),topic.get('score'),json.dumps(p['topics'],ensure_ascii=False) if p.get('topics') is not None else None]
            writer.writerow([("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v) for v in values])
    response=current_app.response_class('\ufeff'+stream.getvalue(),mimetype='text/csv')
    response.headers['Content-Disposition']='attachment; filename=openalex-reviewed-metrics.csv'
    return response
