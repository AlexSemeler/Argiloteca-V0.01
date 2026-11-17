"""Atomic incremental replacement of public record chunks; immutable other corpora."""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime,timezone
from pathlib import Path


def now():return datetime.now(timezone.utc).isoformat()


def atomic_json(path,value):
    fd,name=tempfile.mkstemp(prefix='.'+path.name,dir=path.parent)
    try:
        with os.fdopen(fd,'w') as stream:
            # This sidecar contains public operational status only. The writer
            # and read-only query service run under different container UIDs.
            os.fchmod(stream.fileno(),0o644)
            json.dump(value,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def chunks(text,width=1000,overlap=100):
    text=re.sub(r'[ \t]+',' ',text).strip();start=0
    while start<len(text):
        end=min(start+width,len(text))
        if end<len(text):
            boundary=text.rfind(' ',start+width//2,end)
            if boundary>start:end=boundary
        yield text[start:end]
        if end==len(text):break
        start=max(start+1,end-overlap)


def static_digest(conn):
    h=hashlib.sha256()
    for row in conn.execute("SELECT * FROM docs WHERE json_extract(metadata,'$.tipo_fonte')!='registro_invenio' ORDER BY id"):
        h.update(json.dumps(tuple(row),ensure_ascii=False).encode())
    return h.hexdigest()


def synchronize(index,provider,*,maximum=10000,deadline=240):
    index=Path(index);status_file=index.with_suffix('.sync-status.json')
    if not index.is_file() or index.is_symlink():raise ValueError('Existing valid index required')
    started=time.monotonic();attempt=now();temp=None;conn=None;previous={}
    if status_file.exists():previous=json.loads(status_file.read_text())
    with index.with_suffix('.sync.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'state':'busy','started_at':attempt}
        try:
            rows={};total_bytes=0
            # Consume the complete snapshot successfully before touching an index.
            for row in provider():
                if time.monotonic()-started>deadline:raise TimeoutError('Public metadata export deadline')
                rid=row.get('record_id')
                if (not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',rid)
                    or rid in rows or row.get('access')!='public' or row.get('source_type')!='registro_invenio'
                    or not isinstance(row.get('text'),str) or not row.get('updated')
                    or hashlib.sha256(row['text'].encode()).hexdigest()!=row.get('sha256')):
                    raise ValueError('Invalid public snapshot')
                total_bytes+=len(row['text'].encode())
                if len(rows)>=maximum or total_bytes>250_000_000:raise ValueError('Snapshot limit')
                rows[rid]=row
            fd,temp=tempfile.mkstemp(prefix='.knowledge-sync-',suffix='.sqlite3',dir=index.parent);os.close(fd)
            conn=sqlite3.connect(temp)
            with sqlite3.connect(index.resolve().as_uri()+'?mode=ro',uri=True) as old:old.backup(conn)
            original_digest=static_digest(conn)
            manifest=json.loads(conn.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
            existing={};document_ids={};catalog_profiles={}
            for identifier,rid,updated,sha in conn.execute("SELECT id,json_extract(metadata,'$.record_id'),json_extract(metadata,'$.updated'),json_extract(metadata,'$.sha256') FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='registro_invenio'"):
                if rid in existing and existing[rid]!=(updated,sha):raise ValueError('Inconsistent current index')
                existing[rid]=(updated,sha)
                document_ids.setdefault(rid,[]).append(identifier)
            for rid,profile in conn.execute("SELECT json_extract(metadata,'$.record_id'),json_extract(metadata,'$.catalog_profile') FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='registro_invenio'"):
                if profile:catalog_profiles[rid]=json.loads(profile)
            changed={rid for rid,row in rows.items() if existing.get(rid)!=(row['updated'],row['sha256']) or catalog_profiles.get(rid)!=row.get('catalog_profile')}
            removed=set(existing)-set(rows)
            pending={identifier for rid in changed|removed for identifier in document_ids.get(rid,[])}
            if pending:
                # FTS id is UNINDEXED: deleting by id repeatedly scans the entire
                # corpus. Resolve actual FTS rowids once; do not assume they
                # equal docs rowids after previous incremental replacements.
                search_rows={}
                for rowid,identifier in conn.execute('SELECT rowid,id FROM search'):
                    if identifier in pending:
                        if identifier in search_rows:raise ValueError('Duplicate search document')
                        search_rows[identifier]=rowid
                if set(search_rows)!=pending:raise ValueError('Missing search document')
                conn.executemany('DELETE FROM search WHERE rowid=?',[(search_rows[i],) for i in sorted(pending)])
                conn.executemany('DELETE FROM docs WHERE id=?',[(i,) for i in sorted(pending)])
            for rid in sorted(changed):
                row=rows[rid]
                for n,text in enumerate(chunks(row['text'])):
                    meta={'tipo_fonte':'registro_invenio','record_id':rid,'updated':row['updated'],'sha256':row['sha256'],
                          'url':row.get('url'),'source_relative_path':'records/'+rid+'.json','access':'public','snapshot':True}
                    if row.get('catalog_profile'):meta['catalog_profile']=row['catalog_profile']
                    identifier=f'record:{rid}:c{n}'
                    conn.execute('INSERT INTO docs VALUES(?,?,?,?)',(identifier,row['title'],text,json.dumps(meta,ensure_ascii=False)))
                    conn.execute('INSERT INTO search VALUES(?,?,?)',(identifier,row['title'],text))
            if static_digest(conn)!=original_digest:raise ValueError('Non-record evidence changed')
            counts=dict(conn.execute("SELECT json_extract(metadata,'$.tipo_fonte'),count(*) FROM docs GROUP BY 1"))
            success={'state':'ok','started_at':attempt,'last_success_at':now(),
                     'duration_seconds':round(time.monotonic()-started,3),'public_records':len(rows),
                     'added':len(set(rows)-set(existing)),'updated':len(changed&set(existing)),
                     'removed':len(removed),'unchanged':len(rows)-len(changed),
                     'attachment_policy':'disabled; approved PDF corpus retained separately',
                     'static_corpus_sha256':original_digest,'errors':0}
            manifest.update(counts=counts,synchronization=success)
            conn.execute("UPDATE manifest SET value=? WHERE key='corpus'",(json.dumps(manifest,ensure_ascii=False),))
            conn.commit()
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('Index integrity')
            conn.close();conn=None
            with open(temp,'rb') as stream:os.fsync(stream.fileno())
            os.chmod(temp,0o644);os.replace(temp,index);temp=None
            try:atomic_json(status_file,success)
            except OSError:success['status_file_warning']='Manifest retains successful synchronization status.'
            return success
        except BaseException as exc:
            failure={'state':'error','started_at':attempt,'duration_seconds':round(time.monotonic()-started,3),
                     'last_success_at':previous.get('last_success_at'),'errors':1,'error_type':type(exc).__name__,
                     'message':'Synchronization failed; previous valid index retained.'}
            atomic_json(status_file,failure)
            raise
        finally:
            if conn is not None:conn.close()
            if temp is not None:Path(temp).unlink(missing_ok=True)
