"""Reviewed OpenAlex analytical overlays. Never writes native record tables.

Each collection is a checkpointed private SQLite plan. Applied versions are
immutable SQLite copies; a single SQL pointer activates them transactionally.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
import zipfile

from flask import current_app
from invenio_db import db
from sqlalchemy import text, bindparam

from .adapters import digest, read_json, release
from .analytics import connect as analysis_connect, doi_of, work_ids
from .models import OpenAlexJob, OpenAlexAnalyticHead
from .service import job_lock

METHOD = 'argiloteca-openalex-enrichment/1.0; OpenAlex API; Topics October 2026'
FIELDS = ('id','doi','display_name','primary_topic','topics','fwci',
          'citation_normalized_percentile','cited_by_count','counts_by_year','updated_date')
METRICS = ('primary_topic','topics','fwci','citation_normalized_percentile','cited_by_count','counts_by_year')


def now():
    return datetime.now(timezone.utc).isoformat()


def path_for(jid, suffix='.sqlite'):
    if not re.fullmatch('[a-f0-9]{32}', jid):
        raise ValueError('Identificador inválido / Invalid identifier.')
    folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'enrichment'
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder/(jid+suffix)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


@contextmanager
def store(jid, write=False):
    path = path_for(jid)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Retrato indisponível / Snapshot unavailable.')
    c = sqlite3.connect(str(path) if write else path.as_uri()+'?mode=ro', uri=not write)
    c.row_factory = sqlite3.Row
    try:
        yield c
        if write: c.commit()
    finally: c.close()


def head():
    item = db.session.get(OpenAlexAnalyticHead, 1)
    return item.version if item else None


def checked_version(jid):
    if not jid: return None
    job = db.session.get(OpenAlexJob, jid)
    path = path_for(jid)
    if not job or job.kind!='enrich_apply' or job.state!='completed' or path.is_symlink() or not path.is_file():
        raise ValueError('Versão analítica indisponível / Analytical version unavailable.')
    # Full integrity verification is mandatory on write/restore; reads use the
    # private immutable version pinned by the journal.
    return job


def old_payload(c, uid):
    if c is None: return None
    row = c.execute('SELECT payload FROM accepted WHERE uid=?',(uid,)).fetchone()
    return json.loads(row[0]) if row else None


def native(uid, lock=False):
    return db.session.execute(text('SELECT json,deletion_status FROM rdm_records_metadata WHERE id=:uid'+(' FOR SHARE' if lock else '')),{'uid':uuid.UUID(uid)}).first()


def native_hash(data):
    return digest(data)


def initialize(job):
    analysis = db.session.get(OpenAlexJob, job.params['analysis'])
    if not analysis or analysis.kind!='stats_scan' or analysis.state!='completed':
        raise ValueError('Atualize as estatísticas / Refresh statistics.')
    target = path_for(job.id)
    if target.exists():
        if not job.snapshot:
            with store(job.id) as existing:
                row=existing.execute('SELECT body FROM manifest').fetchone()
                job.snapshot=json.loads(row[0]);job.result=progress(existing)
            db.session.commit()
        return
    fd, temporary = tempfile.mkstemp(prefix='.collect-',dir=target.parent)
    os.close(fd)
    c = sqlite3.connect(temporary)
    previous = head()
    prior = sqlite3.connect(path_for(previous).as_uri()+'?mode=ro',uri=True) if previous else None
    try:
        c.executescript('''CREATE TABLE plan(uid TEXT PRIMARY KEY,rid TEXT UNIQUE,title TEXT,oa_id TEXT,doi TEXT,
          native_hash TEXT,old TEXT,proposed TEXT,status TEXT,reason TEXT,candidates TEXT);
          CREATE INDEX status_idx ON plan(status);''')
        with analysis_connect(analysis) as source:
            # Only the frozen published scope; fetch native bodies in bounded pages.
            cursor = source.execute('SELECT rid,title,oa_id,doi FROM works ORDER BY rid'+(' LIMIT 100' if job.params.get('example') else ''))
            while rows := cursor.fetchmany(100):
                native_rows = db.session.execute(text("SELECT id::text,json FROM rdm_records_metadata WHERE deletion_status='P' AND json->>'id' IN :ids").bindparams(bindparam('ids',expanding=True)),{'ids':[r['rid'] for r in rows]}).all()
                by_rid = {d['id']:(uid,d) for uid,d in native_rows}
                for row in rows:
                    found = by_rid.get(row['rid'])
                    if not found: continue
                    uid,data = found
                    ids = work_ids(data)
                    status = 'pending' if len(ids)<=1 else 'blocked'
                    old = old_payload(prior,uid)
                    c.execute('INSERT INTO plan VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uid,row['rid'],row['title'],next(iter(ids)) if len(ids)==1 else '',doi_of(data),native_hash(data),json.dumps(old),None,status,'Multiple native OpenAlex IDs' if status=='blocked' else '', '[]'))
        snapshot={'analysis':analysis.id,'previous':previous,'method':METHOD,'created_at':now(),'scope':'published','batch_size':100}
        c.execute('CREATE TABLE manifest(body TEXT)');c.execute('INSERT INTO manifest VALUES(?)',(json.dumps(snapshot),))
        c.commit();c.close();os.chmod(temporary,0o600);os.replace(temporary,target)
    except BaseException:
        c.close();Path(temporary).unlink(missing_ok=True);raise
    finally:
        if prior: prior.close()
    job.snapshot=snapshot
    job.result={'total':0,'processed':0,'ready':0,'blocked':0}
    db.session.commit()


class RetryLater(Exception):
    def __init__(self, seconds): self.seconds=max(2,min(int(seconds),86400))


def fetch(filter_value):
    """Fixed HTTPS origin, bearer credential, bounded body, sanitized errors."""
    import requests
    install,_ = release(current_app.config['ARGILOTECA_OPENALEX_ROOT'],'extractor')
    credential = read_json(install/'credenciais/openalex.json',install)
    secret = credential.get('api_key','')
    headers={'Accept':'application/json','User-Agent':'Argiloteca-OpenAlex-Enrichment/1.0'}
    if secret: headers['Authorization']='Bearer '+secret
    try:
        with requests.Session() as session:
            response=session.get('https://api.openalex.org/works',params={'filter':filter_value,'per_page':100,'select':','.join(FIELDS)},headers=headers,timeout=(10,40),stream=True,allow_redirects=False)
            with response:
                if response.status_code==429 or response.status_code>=500:
                    delay=response.headers.get('Retry-After','30')
                    if response.status_code==429 and response.headers.get('X-RateLimit-Remaining')=='0': delay=response.headers.get('X-RateLimit-Reset',delay)
                    try: delay=int(delay)
                    except ValueError:
                        try:
                            from email.utils import parsedate_to_datetime
                            delay=max(2,int(parsedate_to_datetime(delay).timestamp()-time.time()))
                        except (TypeError,ValueError,OverflowError): delay=60
                    raise RetryLater(delay)
                if response.status_code!=200:
                    raise ValueError('OpenAlex HTTP '+str(response.status_code)+'. Verifique a configuração local / Check local configuration.')
                body=bytearray()
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body)>16*1024*1024: raise ValueError('Resposta OpenAlex excedeu o limite / Response size exceeded.')
                data=json.loads(body)
                if not isinstance(data.get('results'),list) or len(data['results'])>100: raise ValueError('Resposta OpenAlex inválida / Invalid OpenAlex response.')
                if (data.get('meta') or {}).get('count',0)>100:
                    # Never silently accept a truncated DOI match set.
                    raise ValueError('Correspondências excedem 100; reduza o lote / Too many matches; reduce scope.')
                return data['results']
    except (requests.RequestException,json.JSONDecodeError):
        raise RetryLater(30) from None


def number(value, maximum=None, integer=False):
    if value is None: return None
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<0 or (maximum is not None and value>maximum) or (integer and int(value)!=value):
        raise ValueError('Métrica inválida na fonte / Invalid source metric.')
    return value


def topic(value):
    if value is None: return None
    if not isinstance(value,dict) or not re.fullmatch(r'https://openalex.org/T\d+',str(value.get('id'))):
        raise ValueError('Topic inválido / Invalid Topic.')
    result={'id':value['id'],'display_name':str(value.get('display_name') or '')[:1000],'score':number(value.get('score'),1)}
    for level in ('subfield','field','domain'):
        x=value.get(level)
        if x is None: result[level]=None;continue
        if not isinstance(x,dict) or not re.fullmatch(r'https://openalex.org/'+level+r's/\d+',str(x.get('id'))): raise ValueError('Hierarquia inválida / Invalid hierarchy.')
        result[level]={'id':x['id'],'display_name':str(x.get('display_name') or '')[:1000]}
    return result


def payload(work):
    oid=str(work.get('id',''))
    if not re.fullmatch(r'https://openalex.org/W\d+',oid): raise ValueError('ID OpenAlex inválido / Invalid OpenAlex ID.')
    pct=work.get('citation_normalized_percentile')
    if pct is not None:
        if not isinstance(pct,dict): raise ValueError('Percentil inválido / Invalid percentile.')
        pct={'value':number(pct.get('value'),1),**{k:pct.get(k) for k in ('is_in_top_1_percent','is_in_top_10_percent')}}
        if any(pct[k] is not None and not isinstance(pct[k],bool) for k in ('is_in_top_1_percent','is_in_top_10_percent')): raise ValueError('Percentil inválido / Invalid percentile.')
    topics=work.get('topics')
    if topics is not None and (not isinstance(topics,list) or len(topics)>100): raise ValueError('Topics inválidos / Invalid Topics.')
    counts=work.get('counts_by_year')
    if counts is not None:
        if not isinstance(counts,list) or len(counts)>100: raise ValueError('Histórico inválido / Invalid history.')
        counts=[{'year':number(x.get('year'),9999,True),'cited_by_count':number(x.get('cited_by_count'),integer=True)} for x in counts]
    return {'id':oid,'doi':doi_of({'pids':{'doi':{'identifier':work.get('doi')}}}),
        'primary_topic':topic(work.get('primary_topic')),'topics':None if topics is None else [topic(t) for t in topics],
        'fwci':number(work.get('fwci')),'citation_normalized_percentile':pct,
        'cited_by_count':number(work.get('cited_by_count'),integer=True),'counts_by_year':counts,
        'updated_date':str(work.get('updated_date') or '')[:80] or None,'collected_at':now(),
        'source':'https://api.openalex.org/works','method':METHOD}


def resolve(row, works, fallback=False):
    """Exact identifiers only. DOI conflicts and reassigned IDs require review."""
    if fallback:
        candidates=[w for w in works if doi_of({'pids':{'doi':{'identifier':w.get('doi')}}})==row['doi']]
    else: candidates=[w for w in works if w.get('id','').rsplit('/',1)[-1]==row['oa_id']]
    if not candidates: return ('missing','No exact identifier match',None,[])
    compact=[{'id':w.get('id'),'doi':w.get('doi'),'title':str(w.get('display_name') or '')[:1000],'payload':payload(w)} for w in candidates]
    if len(candidates)!=1: return ('blocked','Multiple DOI matches; review required',None,compact)
    p=payload(candidates[0])
    if row['doi'] and p['doi'] and row['doi']!=p['doi']:
        return ('blocked','Native DOI differs from OpenAlex DOI',p,compact)
    if fallback and row['oa_id'] and p['id'].rsplit('/',1)[-1]!=row['oa_id']:
        return ('blocked','DOI matches a different OpenAlex ID',p,compact)
    return ('ready','Exact normalized DOI' if fallback else 'Exact native OpenAlex ID; DOI checked',p,compact)


def progress(c):
    counts=dict(c.execute('SELECT status,count(*) FROM plan GROUP BY status').fetchall())
    total=sum(counts.values())
    return {'total':total,'processed':total-counts.get('pending',0),'ready':counts.get('ready',0),
        'blocked':counts.get('blocked',0),'missing':counts.get('missing',0),'errors':counts.get('error',0)}


def collect_chunk(job):
    with job_lock('openalex-enrichment-collection') as locked:
        if not locked:
            job.state='queued';db.session.commit();return 5
        initialize(job)
        with store(job.id,True) as c:
            rows=c.execute("SELECT * FROM plan WHERE status='pending' ORDER BY rid LIMIT 100").fetchall()
            if not rows:
                job.result=progress(c);job.snapshot={**job.snapshot,'sha256':sha(path_for(job.id)),'completed_at':now()};job.state='review';db.session.commit();return 0
            if time.time()<job.result.get('retry_at',0):
                job.state='waiting_api';db.session.commit();return 0
            try:
                ids=sorted({r['oa_id'] for r in rows if r['oa_id']})
                works=fetch('openalex:'+'|'.join(ids)) if ids else []
                unresolved=[r for r in rows if r['doi'] and not any(w.get('id','').rsplit('/',1)[-1]==r['oa_id'] for w in works)]
                dois=sorted({r['doi'] for r in unresolved if re.fullmatch(r'10\.\d{4,9}/[^|,\s]+',r['doi'])})
                alternate=fetch('doi:'+'|'.join(dois)) if dois else []
            except RetryLater as retry:
                attempts=job.result.get('retries',0)+1
                delay=max(retry.seconds,min(300,2**attempts))
                job.result={**progress(c),'retries':attempts,'retry_at':time.time()+delay}
                job.state='waiting_api' if attempts<=5 else 'failed';db.session.commit()
                return 0
            for row in rows:
                try: status,reason,proposed,candidates=resolve(row,alternate if row in unresolved else works,row in unresolved)
                except (ValueError,TypeError,AttributeError): status,reason,proposed,candidates='error','Invalid source payload',None,[]
                c.execute('UPDATE plan SET status=?,reason=?,proposed=?,candidates=? WHERE uid=?',(status,reason,json.dumps(proposed),json.dumps(candidates),row['uid']))
            c.commit()  # Durable per-100 checkpoint before scheduling another chunk.
            job.result=progress(c);job.state='queued'
            db.session.commit();return 2


def validate_plan(source):
    if not source or source.kind!='enrich_collect' or source.state!='review' or sha(path_for(source.id))!=source.snapshot.get('sha256'):
        raise ValueError('Prévia alterada ou indisponível / Preview changed or unavailable.')


def create_backup(job, previous, source):
    validate_plan(source)
    target=path_for(job.id,'.zip')
    manifest={'version':1,'method':METHOD,'actor':job.actor,'created_at':now(),'previous':previous,
        'preview':source.id,'preview_sha256':sha(path_for(source.id)),'selection':job.params['selection'],
        'review':job.params['review'],'collection':source.snapshot}
    if previous:
        version=checked_version(previous)
        if sha(path_for(previous))!=version.result['sha256']: raise ValueError('Versão anterior alterada / Previous version changed.')
        manifest['previous_sha256']=version.result['sha256']
    fd,tmp=tempfile.mkstemp(prefix='.backup-',dir=target.parent);os.close(fd)
    try:
        with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            z.write(path_for(source.id),'preview.sqlite')
            if previous:z.write(path_for(previous),'previous.sqlite')
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() or json.loads(z.read('manifest.json'))!=manifest: raise ValueError('Backup inválido / Invalid backup.')
            # Verify bytes inside the backup against the pinned snapshots.
            for name,expected in [('preview.sqlite',manifest['preview_sha256']),*([('previous.sqlite',manifest['previous_sha256'])] if previous else [])]:
                h=hashlib.sha256()
                with z.open(name) as f:
                    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
                if h.hexdigest()!=expected:raise ValueError('Backup inválido / Invalid backup.')
        os.chmod(tmp,0o600);os.replace(tmp,target)
    finally:Path(tmp).unlink(missing_ok=True)
    return {'filename':target.name,'sha256':sha(target),'bytes':target.stat().st_size,'manifest':manifest}


def apply(job):
    with job_lock('openalex-enrichment-activation') as locked:
        if not locked: raise ValueError('Aplicação em andamento / Application running.')
        source=db.session.get(OpenAlexJob,job.params['preview'])
        validate_plan(source)
        pointer=db.session.query(OpenAlexAnalyticHead).filter_by(id=1).with_for_update().one()
        previous=pointer.version
        oldc=sqlite3.connect(path_for(previous).as_uri()+'?mode=ro',uri=True) if previous else None
        temp=None;c=None
        try:
            with store(source.id) as plan:
                selection=job.params['selection']
                if selection=='all':cursor=plan.execute("SELECT * FROM plan WHERE status='ready' ORDER BY rid")
                else:cursor=plan.execute('SELECT * FROM plan WHERE uid IN ('+','.join('?' for _ in selection)+') ORDER BY rid',selection)
                fd,temp=tempfile.mkstemp(prefix='.version-',dir=path_for(job.id).parent);os.close(fd)
                c=sqlite3.connect(temp)
                c.execute('CREATE TABLE accepted(uid TEXT PRIMARY KEY,rid TEXT UNIQUE,oa_id TEXT,doi TEXT,payload TEXT,payload_hash TEXT)')
                # Identity checks must remain indexed as the accepted collection
                # grows; scanning JSON for every work otherwise becomes quadratic.
                c.execute("CREATE INDEX accepted_source_id ON accepted(json_extract(payload,'$.id'))")
                c.execute("CREATE INDEX accepted_source_doi ON accepted(json_extract(payload,'$.doi'))")
                c.execute('CREATE TABLE validated(uid TEXT PRIMARY KEY,native_hash TEXT)')
                if oldc:
                    c.executemany('INSERT INTO accepted VALUES(?,?,?,?,?,?)',oldc.execute('SELECT * FROM accepted'))
                changed=0;unchanged=0;failures=[];selected=0
                for row in cursor:
                    selected+=1
                    if row['status']!='ready': raise ValueError('Seleção contém item bloqueado / Selection contains blocked item.')
                    p=json.loads(row['proposed']);existing=old_payload(oldc,row['uid'])
                    if existing==p: unchanged+=1;continue
                    live=native(row['uid'])
                    if not live or live[1]!='P' or native_hash(live[0])!=row['native_hash'] or existing!=json.loads(row['old']):
                        failures.append({'rid':row['rid'],'reason':'Record or previous analytical values changed; collect a new preview'});continue
                    # Unique native UUID, RID, DOI/OpenAlex mapping: never create or
                    # merge native works when source identifiers converge.
                    conflict=c.execute("SELECT uid FROM accepted WHERE uid!=? AND (json_extract(payload,'$.id')=? OR (json_extract(payload,'$.doi')!=? AND json_extract(payload,'$.doi')=?))",(row['uid'],p['id'],'',p['doi'])).fetchone()
                    if conflict:
                        failures.append({'rid':row['rid'],'reason':'Analytical identity already linked to another native record'});continue
                    c.execute('INSERT INTO accepted VALUES(?,?,?,?,?,?) ON CONFLICT(uid) DO UPDATE SET rid=excluded.rid,oa_id=excluded.oa_id,doi=excluded.doi,payload=excluded.payload,payload_hash=excluded.payload_hash',
                        (row['uid'],row['rid'],'https://openalex.org/'+row['oa_id'] if row['oa_id'] else p['id'],row['doi'] or p['doi'],json.dumps(p),digest(p)))
                    c.execute('INSERT INTO validated VALUES(?,?)',(row['uid'],row['native_hash']));changed+=1
                if not selected:raise ValueError('Nenhum item selecionado / No selected items.')
                c.commit();c.close()
            backup=create_backup(job,previous,source)
            job.result={'backup':backup,'previous':previous,'phase':'backup_verified'};db.session.commit()
            pointer=db.session.query(OpenAlexAnalyticHead).filter_by(id=1).with_for_update().one()
            if pointer.version!=previous:raise ValueError('A versão ativa mudou / Active version changed.')
            check=sqlite3.connect(temp)
            try:
                for uid,expected in check.execute('SELECT uid,native_hash FROM validated'):
                    live=native(uid,lock=True)
                    if not live or live[1]!='P' or native_hash(live[0])!=expected:raise ValueError('Registro mudou durante a revisão / Record changed during review.')
            finally:check.close()
            os.chmod(temp,0o600);os.replace(temp,path_for(job.id));temp=None
            pointer.version=job.id
            job.state='completed';job.result={'changed':changed,'unchanged':unchanged,'selected':selected,'failures':failures,'backup':backup,'previous':previous,'sha256':sha(path_for(job.id)),'applied_at':now(),'method':METHOD}
            db.session.commit()
        finally:
            if oldc:oldc.close()
            if c:c.close()
            if temp:Path(temp).unlink(missing_ok=True)


def restore(job):
    with job_lock('openalex-enrichment-activation') as locked:
        if not locked:raise ValueError('Aplicação em andamento / Application running.')
        source=db.session.get(OpenAlexJob,job.params['version'])
        pointer=db.session.query(OpenAlexAnalyticHead).filter_by(id=1).with_for_update().one()
        if not source or source.kind!='enrich_apply' or source.state!='completed' or pointer.version!=source.id:
            raise ValueError('A versão ativa mudou / Active version changed.')
        backup=source.result['backup'];file=path_for(source.id,'.zip')
        if file.is_symlink() or sha(file)!=backup['sha256']:raise ValueError('Backup alterado / Backup changed.')
        previous=source.result.get('previous')
        with zipfile.ZipFile(file) as z:
            if z.testzip() or json.loads(z.read('manifest.json'))!=backup['manifest']:raise ValueError('Backup inválido / Invalid backup.')
            if previous:
                expected=backup['manifest']['previous_sha256']
                prior=db.session.get(OpenAlexJob,previous)
                if not prior or prior.kind!='enrich_apply' or prior.state!='completed' or prior.result['sha256']!=expected:raise ValueError('Histórico divergente / Conflicting history.')
                # Recovery also restores a missing previous version from the verified backup.
                fd,temp=tempfile.mkstemp(prefix='.restore-',dir=file.parent);os.close(fd)
                try:
                    with z.open('previous.sqlite') as r,open(temp,'wb') as w:shutil.copyfileobj(r,w,1024*1024)
                    if sha(Path(temp))!=expected:raise ValueError('Backup inválido / Invalid backup.')
                    os.chmod(temp,0o600);os.replace(temp,path_for(previous))
                finally:Path(temp).unlink(missing_ok=True)
        pointer.version=previous;job.state='completed'
        job.result={'restored':previous,'from':source.id,'at':now(),'actor':job.actor,'backup':backup['sha256']}
        db.session.commit()


def attach(c, version="current"):
    """Attach approved overlay only, with one-to-one native RID + identity join."""
    for statement in ('DROP VIEW IF EXISTS temp.measures','DROP TABLE IF EXISTS temp.selection','DROP VIEW IF EXISTS temp.approved','DROP VIEW IF EXISTS temp.works','DROP TABLE IF EXISTS temp.no_accepted','DROP TABLE IF EXISTS temp.preview_accepted'):
        c.execute(statement)
    version=head() if version=="current" else (None if version=="none" else version)
    if version and version.startswith('preview:'):
        preview=db.session.get(OpenAlexJob,version.removeprefix('preview:'));validate_plan(preview)
        c.execute('CREATE TEMP TABLE preview_accepted(uid,rid,oa_id,doi,payload,payload_hash)')
        with store(preview.id) as plan:
            for row in plan.execute("SELECT * FROM plan WHERE status='ready'"):
                p=json.loads(row['proposed'])
                c.execute('INSERT INTO preview_accepted VALUES(?,?,?,?,?,?)',(row['uid'],row['rid'],'https://openalex.org/'+row['oa_id'] if row['oa_id'] else p['id'],row['doi'] or p['doi'],row['proposed'],digest(p)))
        source='preview_accepted'
    elif version:
        checked_version(version)
        path=path_for(version);alias='enriched_'+version
        if not any(row[1]==alias for row in c.execute('PRAGMA database_list')):
            c.execute('ATTACH DATABASE ? AS '+alias,(path.as_uri()+'?mode=ro',))
        source=alias+'.accepted'
    else:
        c.execute('CREATE TEMP TABLE no_accepted(uid,rid,oa_id,doi,payload,payload_hash)');source='no_accepted'
    c.execute('CREATE TEMP VIEW approved AS SELECT a.* FROM '+source+" a JOIN main.works w ON w.rid=a.rid AND (w.oa_id=replace(a.oa_id,'https://openalex.org/','') OR (w.oa_id IS NULL AND w.doi=a.doi))")
    c.execute("""CREATE TEMP VIEW works AS SELECT w.rid,w.title,w.year,w.type,w.oa_id,w.doi,w.source_id,w.source,w.source_type,w.issn,
        CASE WHEN a.uid IS NOT NULL THEN json_extract(a.payload,'$.cited_by_count') ELSE w.citations END citations,
        CASE WHEN a.uid IS NOT NULL THEN json_extract(a.payload,'$.collected_at') ELSE w.collected END collected
        FROM main.works w LEFT JOIN approved a ON a.rid=w.rid""")
    return version


def analytical_statistics(c, clause, params, version):
    """One filtered population for counts, coverage, exact values and CSV."""
    c.execute('CREATE TEMP TABLE selection AS SELECT w.* FROM works w'+clause,params)
    c.execute('CREATE TEMP VIEW measures AS SELECT s.rid,s.title,s.oa_id,s.doi,a.payload FROM selection s LEFT JOIN approved a ON s.rid=a.rid')
    total=c.execute('SELECT count(*) FROM selection').fetchone()[0]
    result={'enrichment_version':version,'enrichment_method':METHOD,'coverage':[],'hierarchy_options':{}}
    for level in ('primary_topic','subfield','field','domain'):
        path='$.primary_topic' if level=='primary_topic' else '$.primary_topic.'+level
        result[level]=[dict(r) for r in c.execute('SELECT json_extract(payload,?) id,min(json_extract(payload,?)) label,count(*) n FROM measures WHERE json_extract(payload,?) IS NOT NULL GROUP BY id ORDER BY n DESC,label LIMIT 15',(path+'.id',path+'.display_name',path+'.id'))]
        result['hierarchy_options'][level]=[dict(r) for r in c.execute('SELECT json_extract(payload,?) id,min(json_extract(payload,?)) label FROM approved WHERE json_extract(payload,?) IS NOT NULL GROUP BY id ORDER BY label',(path+'.id',path+'.display_name',path+'.id'))]
    result['additional_topics']=[dict(r) for r in c.execute("SELECT json_extract(t.value,'$.id') id,min(json_extract(t.value,'$.display_name')) label,count(DISTINCT m.rid) n FROM measures m,json_each(m.payload,'$.topics') t WHERE json_extract(m.payload,'$.primary_topic.id') IS NULL OR json_extract(t.value,'$.id')!=json_extract(m.payload,'$.primary_topic.id') GROUP BY json_extract(t.value,'$.id') ORDER BY n DESC,label LIMIT 15")]
    for key,path in [('reviewed','$'),('primary_topic','$.primary_topic.id'),('topics','$.topics'),('subfield','$.primary_topic.subfield.id'),('field','$.primary_topic.field.id'),('domain','$.primary_topic.domain.id'),('fwci','$.fwci'),('percentile','$.citation_normalized_percentile.value'),('top1','$.citation_normalized_percentile.is_in_top_1_percent'),('top10','$.citation_normalized_percentile.is_in_top_10_percent'),('citations','$.cited_by_count'),('annual_citations','$.counts_by_year')]:
        n=c.execute('SELECT count(*) FROM measures WHERE json_extract(payload,?) IS NOT NULL',(path,)).fetchone()[0]
        result['coverage'].append({'id':key,'label':key,'n':n,'missing':total-n,'denominator':total})
    result['fwci']=[dict(r) for r in c.execute("""SELECT CASE WHEN f<0.5 THEN '0–<0.5' WHEN f<1 THEN '0.5–<1' WHEN f<1.5 THEN '1–<1.5' WHEN f<2 THEN '1.5–<2' WHEN f<3 THEN '2–<3' WHEN f<5 THEN '3–<5' WHEN f<10 THEN '5–<10' ELSE '≥10' END label,
      CASE WHEN f<0.5 THEN 0.25 WHEN f<1 THEN 0.75 WHEN f<1.5 THEN 1.25 WHEN f<2 THEN 1.75 WHEN f<3 THEN 2.5 WHEN f<5 THEN 4 WHEN f<10 THEN 7.5 ELSE 10.5 END x,count(*) n FROM (SELECT json_extract(payload,'$.fwci') f FROM measures) WHERE f IS NOT NULL GROUP BY x ORDER BY x""")]
    result['percentiles']=[dict(r) for r in c.execute("""SELECT CASE WHEN p<0.5 THEN '<50' WHEN p<0.9 THEN '50–<90' WHEN p<0.99 THEN '90–<99' ELSE '99–100' END label,count(*) n FROM (SELECT json_extract(payload,'$.citation_normalized_percentile.value') p FROM measures) WHERE p IS NOT NULL GROUP BY label ORDER BY label""")]
    result['top_groups']=[]
    for key in ('is_in_top_1_percent','is_in_top_10_percent'):
        path='$.citation_normalized_percentile.'+key
        row=c.execute('SELECT count(CASE WHEN json_extract(payload,?)=1 THEN 1 END) n,count(json_extract(payload,?)) denominator FROM measures',(path,path)).fetchone()
        result['top_groups'].append({'label':key,'n':row['n'],'denominator':row['denominator'],'share':100*row['n']/row['denominator'] if row['denominator'] else None})
    result['enrichment_dates']=dict(c.execute("SELECT min(json_extract(payload,'$.collected_at')) first_collection,max(json_extract(payload,'$.collected_at')) last_collection,max(json_extract(payload,'$.updated_date')) latest_source_update FROM measures").fetchone())
    return result
