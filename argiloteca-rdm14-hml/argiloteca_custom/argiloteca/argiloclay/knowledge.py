"""Curated, versioned PDF library; bibliographic records are never modified."""
import hashlib
import fcntl
import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from .batch_sync import backup, sha, writer_lock, database
from .index_sync import atomic_json, chunks, now

MAX_BYTES = 50 * 1024 * 1024
MAX_PAGES = 1000
EXTRACT_BATCH_PAGES = 25
EXTRACT_BATCH_SECONDS = 45


class ExtractionError(ValueError):
    def __init__(self, code, **details):
        self.code=code;self.details=details
        super().__init__(code)


def pdf_limits():
    """Bound native parsers/OCR independently of the application worker."""
    import resource
    resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(16*1024*1024,16*1024*1024))
    resource.setrlimit(resource.RLIMIT_CPU,(60,65))


class Library:
    def __init__(self, root, index):
        self.root = Path(root); self.index = Path(index)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.files = self.root / 'files'; self.files.mkdir(exist_ok=True)
        self.db = self.root / 'library.sqlite3'
        with self.connect() as c:
            c.executescript('''
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,active_version INTEGER,created TEXT);
                CREATE TABLE IF NOT EXISTS versions(doc TEXT,version INTEGER,sha TEXT UNIQUE,metadata TEXT,state TEXT,created TEXT,error TEXT,PRIMARY KEY(doc,version));
                CREATE TABLE IF NOT EXISTS pages(doc TEXT,version INTEGER,page INTEGER,text TEXT,method TEXT,warnings TEXT,approved INTEGER DEFAULT 0,numeric_review INTEGER DEFAULT 0,reviewer TEXT,reviewed_at TEXT,PRIMARY KEY(doc,version,page));
                CREATE TABLE IF NOT EXISTS extraction_jobs(doc TEXT,version INTEGER,total_pages INTEGER,ocr INTEGER,updated_at TEXT,PRIMARY KEY(doc,version));
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT,actor TEXT,action TEXT,doc TEXT,details TEXT);
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.db, timeout=10); c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback(); raise
        finally:
            c.close()

    def audit(self, c, actor, action, doc=None, details=None):
        c.execute('INSERT INTO audit(at,actor,action,doc,details) VALUES(?,?,?,?,?)',
                  (now(), str(actor), action, doc, json.dumps(details or {}, ensure_ascii=False)))

    def path(self, doc, version):
        if not re.fullmatch(r'[a-f0-9]{32}', str(doc)) or not str(version).isdigit():
            raise ValueError('Invalid document')
        return self.files / doc / (str(int(version)) + '.pdf')

    def upload(self, stream, metadata, actor, replace=None):
        fields = ('title','authors','year','language','doi','url','subjects','minerals','groups','record_id','origin','rights','access')
        meta = {k: str(metadata.get(k, '')).strip()[:3000] for k in fields}
        meta['doi']=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',meta['doi'],flags=re.I).strip().lower()
        if not meta['title'] or not meta['rights'] or not meta['origin'] or meta['access'] not in ('public','restricted'):
            raise ValueError('Title, origin, rights and access are required')
        if meta['url'] and (urlsplit(meta['url']).scheme not in ('https','http') or not urlsplit(meta['url']).netloc or urlsplit(meta['url']).username):
            raise ValueError('Invalid source URL')
        if meta['record_id'] and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', meta['record_id']):
            raise ValueError('Invalid native record identifier')
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix='.upload'); digest = hashlib.sha256(); size = 0
        try:
            with os.fdopen(fd,'wb') as out:
                while True:
                    data = stream.read(1024 * 1024)
                    if not data: break
                    size += len(data)
                    if size > MAX_BYTES: raise ValueError('PDF exceeds 50 MiB')
                    digest.update(data); out.write(data)
                out.flush(); os.fsync(out.fileno())
            with open(tmp,'rb') as source:
                if not source.read(1024).lstrip().startswith(b'%PDF-'): raise ValueError('Invalid PDF signature')
            with self.connect() as c:
                existing = c.execute('SELECT doc,version FROM versions WHERE sha=?',(digest.hexdigest(),)).fetchone()
                if existing: return dict(existing, duplicate=True)
                doc = replace or uuid.uuid4().hex
                if replace and not c.execute('SELECT 1 FROM documents WHERE id=?',(replace,)).fetchone(): raise ValueError('Document not found')
                version = c.execute('SELECT coalesce(max(version),0)+1 FROM versions WHERE doc=?',(doc,)).fetchone()[0]
                dest = self.path(doc,version); dest.parent.mkdir(exist_ok=True)
                os.replace(tmp,dest); os.chmod(dest,0o600)
                c.execute('INSERT INTO documents VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET active_version=excluded.active_version',(doc,version,now()))
                c.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?)',(doc,version,digest.hexdigest(),json.dumps(meta,ensure_ascii=False),'queued',now(),None))
                self.audit(c,actor,'upload',doc,{'version':version,'sha256':digest.hexdigest()})
            self.publish_access()
            return {'doc':doc,'version':version,'duplicate':False}
        finally:
            Path(tmp).unlink(missing_ok=True)

    def get(self, doc, version=None):
        with self.connect() as c:
            if version is None:
                row = c.execute('SELECT active_version FROM documents WHERE id=?',(doc,)).fetchone()
                if not row: raise KeyError(doc)
                version = row[0]
            row = c.execute('SELECT * FROM versions WHERE doc=? AND version=?',(doc,int(version))).fetchone()
            if not row: raise KeyError(doc)
            data = dict(row); data['metadata'] = json.loads(data['metadata'])
            data['pages'] = [dict(p) for p in c.execute('SELECT * FROM pages WHERE doc=? AND version=? ORDER BY page',(doc,int(version)))]
            job=c.execute('SELECT total_pages,ocr,updated_at FROM extraction_jobs WHERE doc=? AND version=?',(doc,int(version))).fetchone()
            data['extraction']=dict(job) if job else {}
            data['extracted_pages']=len(data['pages'])
            data['versions'] = [dict(r) for r in c.execute('SELECT version,state,created FROM versions WHERE doc=? ORDER BY version DESC',(doc,))]
            return data

    def listing(self, page=1, q=''):
        with self.connect() as c:
            where = " WHERE (?='' OR lower(v.metadata) LIKE ?)"
            params = (q.lower(),'%'+q.lower()+'%')
            total = c.execute('SELECT count(*) FROM documents d JOIN versions v ON v.doc=d.id AND v.version=d.active_version'+where,params).fetchone()[0]
            rows = []
            for r in c.execute('SELECT v.* FROM documents d JOIN versions v ON v.doc=d.id AND v.version=d.active_version'+where+' ORDER BY v.created DESC LIMIT 20 OFFSET ?',(*params,(page-1)*20)):
                row = dict(r); row['metadata']=json.loads(row['metadata']); rows.append(row)
            return rows,total

    def extract(self, doc, version, ocr=False):
        self.path(doc,version)  # validate before constructing a lock filename
        with (self.root/(doc+'-extract.lock')).open('a') as lock:
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError: return {'state':'busy'}
            return self._extract(doc,version,ocr)

    def _extract(self, doc, version, ocr=False):
        path=self.path(doc,version);started=time.monotonic();processed=0;page=None
        with self.connect() as c:
            item=dict(c.execute('SELECT state,sha FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone())
        with self.connect() as c:
            if c.execute('SELECT state FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone()[0] not in ('queued','failed','extracting'):
                return {'state':item['state']}
            c.execute("UPDATE versions SET state='extracting',error=NULL WHERE doc=? AND version=?",(doc,version))
        try:
            if sha(path)!=item['sha']:raise ExtractionError('original_changed')
            info=subprocess.run(['pdfinfo',str(path)],capture_output=True,text=True,timeout=20,check=True,preexec_fn=pdf_limits).stdout
            found=re.search(r'^Pages:\s+(\d+)',info,re.M)
            if not found:raise ExtractionError('page_count_unavailable')
            count=int(found[1])
            with self.connect() as c:
                c.execute('INSERT INTO extraction_jobs VALUES(?,?,?,?,?) ON CONFLICT(doc,version) DO UPDATE SET total_pages=excluded.total_pages,ocr=excluded.ocr,updated_at=excluded.updated_at',(doc,version,count,int(ocr),now()))
            if not 1<=count<=MAX_PAGES: raise ExtractionError('page_limit',total_pages=count,limit=MAX_PAGES)
            for page in range(1,count+1):
                if processed>=EXTRACT_BATCH_PAGES or time.monotonic()-started>=EXTRACT_BATCH_SECONDS:break
                with self.connect() as c:
                    state=c.execute('SELECT state FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone()[0]
                    if state!='extracting':return {'state':state}
                    if c.execute('SELECT 1 FROM pages WHERE doc=? AND version=? AND page=?',(doc,version,page)).fetchone(): continue
                with tempfile.TemporaryDirectory(dir=self.root) as folder:
                    textfile=Path(folder)/'page.txt'
                    subprocess.run(['pdftotext','-f',str(page),'-l',str(page),'-layout','-enc','UTF-8',str(path),str(textfile)],capture_output=True,timeout=30,check=True,preexec_fn=pdf_limits)
                    if textfile.stat().st_size>400000:raise ExtractionError('page_byte_limit',page=page)
                    text=textfile.read_text(); method='poppler'; warnings=['scientific_visual_review_required']
                    if len(text.strip())<80 and ocr:
                        image=Path(folder)/'page'
                        subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-scale-to','2000','-png',str(path),str(image)],capture_output=True,timeout=40,check=True,preexec_fn=pdf_limits)
                        output=Path(folder)/'ocr'
                        subprocess.run(['tesseract',str(image)+'.png',str(output),'-l','por+eng'],capture_output=True,timeout=60,check=True,preexec_fn=pdf_limits,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
                        if output.with_suffix('.txt').stat().st_size>400000:raise ExtractionError('page_byte_limit',page=page)
                        text=output.with_suffix('.txt').read_text(); method='tesseract_por_eng'; warnings.append('ocr_review_required')
                    if len(text.strip())<80: warnings.append('little_or_no_text')
                    if '\ufffd' in text or '\x00' in text: warnings.append('suspect_characters')
                    if len(text)>100_000: raise ExtractionError('page_text_limit',page=page)
                    with self.connect() as c:
                        c.execute('INSERT OR IGNORE INTO pages(doc,version,page,text,method,warnings) VALUES(?,?,?,?,?,?)',(doc,version,page,text,method,json.dumps(warnings)))
                    processed+=1
            with self.connect() as c:
                done=c.execute('SELECT count(*) FROM pages WHERE doc=? AND version=?',(doc,version)).fetchone()[0]
                state='review' if done==count else 'extracting'
                c.execute("UPDATE versions SET state=? WHERE doc=? AND version=? AND state='extracting'",(state,doc,version))
                c.execute('UPDATE extraction_jobs SET updated_at=? WHERE doc=? AND version=?',(now(),doc,version))
                current=c.execute('SELECT state FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone()[0]
                self.audit(c,'worker','extracted' if current=='review' else 'extraction_batch',doc,{'version':version,'pages':done,'total_pages':count,'batch_pages':processed})
            return {'state':current,'pages':done,'total_pages':count,'batch_pages':processed}
        except Exception as exc:
            if isinstance(exc,ExtractionError):error={'code':exc.code,**exc.details}
            elif isinstance(exc,subprocess.TimeoutExpired):error={'code':'parser_timeout','page':page}
            elif isinstance(exc,subprocess.CalledProcessError):error={'code':'parser_failed','page':page}
            else:error={'code':'worker_interrupted' if type(exc).__name__=='SoftTimeLimitExceeded' else 'extraction_failed','page':page}
            with self.connect() as c:
                c.execute("UPDATE versions SET state='failed',error=? WHERE doc=? AND version=? AND state='extracting'",(json.dumps(error),doc,version))
            raise

    def review(self, doc, version, pages, actor, *, numeric=False):
        if not numeric: raise ValueError('Scientific and numeric review confirmation required')
        if sha(self.path(doc,version))!=self.get(doc,version)['sha']:
            raise ValueError('Original PDF hash mismatch')
        with writer_lock(self.index), self.connect() as c:
            row=c.execute('SELECT v.state,v.metadata,d.active_version FROM versions v JOIN documents d ON d.id=v.doc WHERE v.doc=? AND v.version=?',(doc,version)).fetchone()
            if not row or row[0] not in ('review','approved','indexed') or row[2]!=version: raise ValueError('Current extracted version required')
            selected=sorted(set(int(p) for p in pages))
            if not selected: raise ValueError('Select reviewed pages')
            for page in selected:
                p=c.execute('SELECT text FROM pages WHERE doc=? AND version=? AND page=?',(doc,version,page)).fetchone()
                if not p or len(p[0].strip())<80: raise ValueError('Page has no usable text')
            for page in selected:
                c.execute('UPDATE pages SET approved=1,numeric_review=1,reviewer=?,reviewed_at=? WHERE doc=? AND version=? AND page=?',(str(actor),now(),doc,version,page))
            c.execute("UPDATE versions SET state='approved' WHERE doc=? AND version=?",(doc,version))
            self.audit(c,actor,'approve_pages',doc,{'version':version,'pages':selected})
        self.publish_access()

    def withdraw(self, doc, version, actor):
        # Revocation is effective at the gateway before rebuilding the index.
        with self.connect() as c:
            c.execute("UPDATE versions SET state='withdrawn' WHERE doc=? AND version=?",(doc,version))
            self.audit(c,actor,'withdraw',doc,{'version':version})
        self.publish_access()

    def restore_document(self, doc, version, actor):
        with self.connect() as c:
            if not c.execute('SELECT 1 FROM versions WHERE doc=? AND version=?',(doc,version)).fetchone(): raise KeyError(doc)
            c.execute('UPDATE documents SET active_version=? WHERE id=?',(version,doc))
            c.execute("UPDATE versions SET state='review' WHERE doc=? AND version=?",(doc,version))
            c.execute('UPDATE pages SET approved=0,numeric_review=0 WHERE doc=? AND version=?',(doc,version))
            self.audit(c,actor,'restore_for_review',doc,{'version':version})
        self.publish_access()

    def publish_access(self):
        allowed={}
        with self.connect() as c:
            for row in c.execute("SELECT v.doc,v.version,v.sha,v.metadata FROM versions v JOIN documents d ON d.id=v.doc AND d.active_version=v.version WHERE v.state IN ('approved','indexed')"):
                meta=json.loads(row['metadata'])
                if meta['access']!='public': continue
                pages={str(p['page']):hashlib.sha256(p['text'].encode()).hexdigest() for p in c.execute('SELECT page,text FROM pages WHERE doc=? AND version=? AND approved=1 AND numeric_review=1',(row['doc'],row['version']))}
                if pages: allowed[row['doc']]={'version':row['version'],'sha256':row['sha'],'pages':pages}
        atomic_json(self.index.with_suffix('.access.json'),{'schema_version':1,'updated_at':now(),'allowed':allowed})

    def source_allowed(self, source, check_excerpt=True):
        try:
            item=self.get(source['library_id'],source['library_version'])
            if item['metadata'].get('record_id'):
                from .service import public_record
                if not public_record(item['metadata']['record_id']): return False
            with self.connect() as c:
                current=c.execute('SELECT active_version FROM documents WHERE id=?',(source['library_id'],)).fetchone()[0]
            if current!=item['version'] or item['state'] not in ('approved','indexed') or item['metadata']['access']!='public' or item['sha']!=source.get('sha256'): return False
            page=next(p for p in item['pages'] if p['page']==source['page'])
            canonical=re.sub(r'[ \t]+',' ',page['text']).strip()
            return bool(page['approved'] and page['numeric_review'] and hashlib.sha256(page['text'].encode()).hexdigest()==source.get('page_sha256') and (not check_excerpt or source.get('excerpt') in canonical))
        except (OSError,KeyError,ValueError,StopIteration,sqlite3.Error): return False

    def index_approved(self, actor):
        with writer_lock(self.index):
            saved=backup(self.index,'before-library')
            staging=self.index.with_suffix('.library.sqlite3'); staging.unlink(missing_ok=True)
            with database(self.index) as old,database(staging) as c:
                old.backup(c)
                # Only managed literature is replaced. Legacy approved corpus is preserved.
                ids=c.execute("SELECT id FROM docs WHERE json_extract(metadata,'$.library_id') IS NOT NULL").fetchall()
                mapping=dict((identifier,rowid) for rowid,identifier in c.execute('SELECT rowid,id FROM search'))
                for (identifier,) in ids:
                    if identifier not in mapping: raise ValueError('Inconsistent search index')
                    c.execute('DELETE FROM search WHERE rowid=?',(mapping[identifier],));c.execute('DELETE FROM docs WHERE id=?',(identifier,))
                with self.connect() as library:
                    for row in library.execute("SELECT v.* FROM versions v JOIN documents d ON d.id=v.doc AND d.active_version=v.version WHERE v.state IN ('approved','indexed')"):
                        meta=json.loads(row['metadata'])
                        if meta['access']!='public': continue
                        if sha(self.path(row['doc'],row['version']))!=row['sha']:
                            raise ValueError('Original PDF hash mismatch')
                        for page in library.execute('SELECT * FROM pages WHERE doc=? AND version=? AND approved=1 AND numeric_review=1',(row['doc'],row['version'])):
                            for n,text in enumerate(chunks(page['text'])):
                                identifier=f"library:{row['doc']}:v{row['version']}:p{page['page']}:c{n}"
                                provenance={'tipo_fonte':'literatura_pdf','library_id':row['doc'],'library_version':row['version'],'page':page['page'],
                                    'sha256':row['sha'],'page_sha256':hashlib.sha256(page['text'].encode()).hexdigest(),
                                    'record_id':None,'related_record_id':meta['record_id'] or None,'source_relative_path':identifier,
                                    'numeric_validation':'reviewed','access':'public','rights':meta['rights'],'doi':meta['doi'],
                                    'source_url':meta['url'],'authors':meta['authors'],'year':meta['year'],'reviewed_at':page['reviewed_at'],
                                    'collected_at':row['created'],'methodology_version':'argiloclay-curation-v1',
                                    'evidence_kind':'scientific_literature','term_ids':re.findall(r'[A-Za-z0-9_-]+',meta['minerals'].lower()),
                                    'contains_header':page['page']==1 and n==0}
                                c.execute('INSERT INTO docs VALUES(?,?,?,?)',(identifier,meta['title'],text,json.dumps(provenance,ensure_ascii=False)))
                                c.execute('INSERT INTO search VALUES(?,?,?)',(identifier,meta['title'],text))
                manifest=json.loads(c.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0]);manifest['library_updated_at']=now()
                manifest['counts']=dict(c.execute("SELECT json_extract(metadata,'$.tipo_fonte'),count(*) FROM docs GROUP BY 1"))
                c.execute("UPDATE manifest SET value=? WHERE key='corpus'",(json.dumps(manifest),));c.commit()
                if c.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise ValueError('Index integrity')
            os.chmod(staging,0o644)
            with open(staging,'rb') as stream: os.fsync(stream.fileno())
            os.replace(staging,self.index)
            with self.connect() as c:
                c.execute("UPDATE versions SET state='indexed' WHERE state='approved' AND json_extract(metadata,'$.access')='public'")
                self.audit(c,actor,'index_approved',details={'backup':saved,'index_sha256':sha(self.index)})
            self.publish_access()
            return saved

    def restore_index(self, name, expected_sha, actor):
        if not re.fullmatch(r'[a-z-]+-[a-f0-9]{32}\.sqlite3',name): raise ValueError('Invalid backup')
        source=self.index.parent/'versions'/name
        with writer_lock(self.index):
            if sha(source)!=expected_sha: raise ValueError('Backup hash mismatch')
            backup(self.index,'before-recovery')
            target=self.index.with_suffix('.recovery.sqlite3')
            with database(source) as old,database(target) as new:
                old.backup(new)
                if new.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise ValueError('Backup integrity')
            os.chmod(target,0o644);os.replace(target,self.index)
            with self.connect() as c: self.audit(c,actor,'recover_index',details={'backup':name,'sha256':expected_sha})
            # Current revocations remain authoritative after a recovery.
            self.publish_access()
