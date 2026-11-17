"""Private, disk-backed bibliometrics and existing creator occurrences."""
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata

from flask import current_app
from invenio_db import db
from sqlalchemy import text

from .adapters import digest, lot_path, lots
from .models import OpenAlexJob
from .preview import raw_items, file_hash


def name_key(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ' '.join(re.findall(r'[^\W_]+', ''.join(c for c in value if not unicodedata.combining(c))))


def creator_name(creator):
    person = creator.get('person_or_org', {})
    return ' '.join(filter(None, (person.get('given_name'), person.get('family_name')))) or person.get('name', '')


def creator_group(creator):
    # A discovery group is not a person authority: applying always selects
    # concrete native creator slots, never propagates an identity by name.
    return digest({'name': name_key(creator_name(creator)), 'type': creator.get('person_or_org', {}).get('type')})[:32]


def path_for(job_id):
    if not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Identificador de análise inválido.')
    folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'analytics'
    folder.mkdir(mode=0o700, exist_ok=True, parents=True)
    return folder / (job_id + '.sqlite')


@contextmanager
def connect(job):
    path = path_for(job.id)
    if job.kind != 'stats_scan' or job.state != 'completed' or not path.is_file() or path.is_symlink():
        raise ValueError('Análise indisponível. Atualize as estatísticas.')
    # Immutable private file was hashed at creation. Do not hash a multi-MB
    # store on every page; integrity is checked before building a write plan.
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def work_ids(data):
    ids = set()
    for item in data.get('metadata', {}).get('identifiers', []):
        value = str(item.get('identifier', '')).strip()
        if re.fullmatch(r'https?://openalex.org/(?:works/)?W\d+', value, re.I) or re.fullmatch(r'W\d+', value, re.I):
            ids.add(value.rsplit('/', 1)[-1].upper())
    for key in ('openalex',):
        value = data.get('pids', {}).get(key, {}).get('identifier', '')
        if value: ids.add(str(value).rsplit('/', 1)[-1].upper())
    return ids


def doi_of(data):
    value = data.get('pids', {}).get('doi', {}).get('identifier')
    if not value:
        value = next((x.get('identifier') for x in data.get('metadata', {}).get('identifiers', []) if x.get('scheme') == 'doi'), '')
    return re.sub(r'^(?:https?://(?:dx\.)?doi.org/|doi:\s*)', '', str(value or '').strip(), flags=re.I).lower().strip()


def approved_work_ids(accepted, uid, data):
    """Use an approved analytical identity without changing native metadata.

    Legacy publications may expose only a DOI. Require the immutable overlay's
    native UUID, RID and DOI together; never infer an identity from author names.
    """
    ids = work_ids(data)
    if ids or accepted is None:
        return ids
    doi = doi_of(data)
    if not doi:
        return set()
    row = accepted.execute('SELECT oa_id,doi FROM accepted WHERE uid=? AND rid=?',
                           (str(uid), data.get('id'))).fetchone()
    if not row or row[1] != doi or not re.fullmatch(r'(?:https://openalex.org/)?W\d+', str(row[0])):
        return set()
    return {row[0].rsplit('/', 1)[-1]}


def prepare(job):
    """Build privately then atomically expose one immutable analysis snapshot."""
    from .orcid import normalize_orcid
    destination = path_for(job.id)
    fd, temporary = tempfile.mkstemp(prefix='.stats-', dir=destination.parent)
    os.close(fd)
    c = sqlite3.connect(temporary)
    accepted = None
    try:
        from .enrichment import head, checked_version, path_for as version_path
        active = head()
        if active:
            checked_version(active)
            accepted = sqlite3.connect(version_path(active).as_uri()+'?mode=ro', uri=True)
        c.executescript('''
          CREATE TABLE works(rid TEXT PRIMARY KEY, title TEXT, year INTEGER, type TEXT, oa_id TEXT UNIQUE, doi TEXT,
            source_id TEXT, source TEXT, source_type TEXT, issn TEXT, citations INTEGER, collected TEXT);
          CREATE INDEX work_oa ON works(oa_id);
          CREATE UNIQUE INDEX work_doi ON works(doi) WHERE doi!='';
          CREATE TABLE tags(rid TEXT, kind TEXT, id TEXT, label TEXT, UNIQUE(rid,kind,id));
          CREATE TABLE authorship(rid TEXT, aid TEXT, name TEXT, orcid TEXT, UNIQUE(rid,aid));
          CREATE TABLE occurrences(key TEXT PRIMARY KEY,gid TEXT,rid TEXT,kind TEXT,slot INTEGER,name TEXT,title TEXT,
            creator TEXT,uuid TEXT,existing_orcid TEXT,oa_id TEXT,doi TEXT,UNIQUE(uuid,kind,slot));
          CREATE INDEX occurrence_group ON occurrences(gid);
          CREATE INDEX occurrence_oa ON occurrences(oa_id);
          CREATE TABLE candidates(occurrence TEXT,orcid TEXT,source TEXT,body TEXT,UNIQUE(occurrence,orcid,source));
          CREATE TABLE raw_work(oa_id TEXT PRIMARY KEY,body TEXT,lot TEXT);
        ''')
        published_ids = set(); duplicates = 0
        retired = set()
        publication_uuids = set()
        # Only active native publications. Drafts never inflate work statistics.
        for uid, data, state in db.session.execute(text('SELECT id::text,json,deletion_status FROM rdm_records_metadata').execution_options(stream_results=True, yield_per=100)).yield_per(100):
            if state != 'P': retired.add(uid); continue
            if not data: continue
            publication_uuids.add(uid)
            ids = approved_work_ids(accepted, uid, data)
            if len(ids) == 1:
                oa_id = next(iter(ids)); md = data.get('metadata', {})
                date = str(md.get('publication_date', ''))
                year = int(date[:4]) if re.match(r'^\d{4}', date) else None
                inserted=c.execute('INSERT OR IGNORE INTO works(rid,title,year,type,oa_id,doi) VALUES(?,?,?,?,?,?)',
                    (data['id'], md.get('title', ''), year, md.get('resource_type', {}).get('id', ''), oa_id, doi_of(data))).rowcount
                if not inserted: duplicates += 1
                published_ids.add(oa_id)
            add_occurrences(c, uid, data, 'published', approved_ids=ids)
        for uid, data in db.session.execute(text('SELECT id::text,json FROM rdm_drafts_metadata WHERE json IS NOT NULL').execution_options(stream_results=True, yield_per=100)).yield_per(100):
            if uid in retired: continue
            # Edits remain visible for author review, distinctly labelled.
            add_occurrences(c, uid, data, 'draft', approved_ids=approved_work_ids(accepted, uid, data))
        root = current_app.config['ARGILOTECA_OPENALEX_ROOT']
        sources = []
        allowed={Path(value).name for (value,) in db.session.execute(text("SELECT DISTINCT snapshot->>'source' FROM argiloteca_openalex_job WHERE kind='import' AND state='completed'")) if value}
        needed = {r[0] for r in c.execute('SELECT DISTINCT oa_id FROM occurrences WHERE oa_id IS NOT NULL')} | published_ids
        # Newest complete local copy wins; each work is counted only once.
        for lot in lots(root):
            if not lot['complete'] or lot['name'] not in allowed: continue
            path = lot_path(root, lot['name']) / 'openalex_raw.json'
            if not path.is_file() or path.is_symlink(): continue
            count = 0
            for _, wrapper in raw_items(path):
                raw = wrapper.get('source_metadata_raw') or wrapper
                oid = str(raw.get('id') or wrapper.get('id', '')).rstrip('/').rsplit('/', 1)[-1].upper()
                if oid not in needed: continue
                # Only the bibliography/identity needed by the panel is retained.
                compact = {k:raw.get(k) for k in ('id','authorships','concepts','keywords','topics','primary_topic','cited_by_count','primary_location','publication_year')}
                if c.execute('INSERT OR IGNORE INTO raw_work VALUES(?,?,?)', (oid,json.dumps(compact,ensure_ascii=False),lot['name'])).rowcount: count += 1
            if count: sources.append({'lot':lot['name'],'works':count,'sha256':file_hash(path)})
        for oid, body, lot in c.execute('SELECT oa_id,body,lot FROM raw_work'):
            raw = json.loads(body); source = (raw.get('primary_location') or {}).get('source') or {}
            c.execute('UPDATE works SET source_id=?,source=?,source_type=?,issn=?,citations=?,collected=?,year=? WHERE oa_id=?',
                (source.get('id'), source.get('display_name'),source.get('type'),source.get('issn_l'),raw.get('cited_by_count'),lot,raw.get('publication_year'),oid))
            records = [r[0] for r in c.execute('SELECT rid FROM works WHERE oa_id=?',(oid,))]
            for kind, entries in (('subject',raw.get('concepts') or []),('keyword',raw.get('keywords') or []),('topic',raw.get('topics') or [])):
                for term in entries:
                    for rid in records: c.execute('INSERT OR IGNORE INTO tags VALUES(?,?,?,?)',(rid,kind,str(term.get('id') or term.get('display_name')),term.get('display_name','')))
            native = list(c.execute('SELECT key,creator FROM occurrences WHERE oa_id=?',(oid,)))
            auths = raw.get('authorships') or []
            for author in auths:
                person = author.get('author') or {}; aid = person.get('id')
                if aid and aid.rsplit('/',1)[-1] not in {'A9999999999','A5317838346'}:
                    for rid in records: c.execute('INSERT OR IGNORE INTO authorship VALUES(?,?,?,?)',(rid,aid,person.get('display_name',''),person.get('orcid')))
                for inst in author.get('institutions') or []:
                    for rid in records:
                        c.execute('INSERT OR IGNORE INTO tags VALUES(?,?,?,?)',(rid,'institution',str(inst.get('id') or inst.get('display_name')),inst.get('display_name','')))
                        if inst.get('country_code'): c.execute('INSERT OR IGNORE INTO tags VALUES(?,?,?,?)',(rid,'country',inst['country_code'],inst['country_code']))
            for key, creator_json in native:
                creator = json.loads(creator_json); key_name = name_key(creator_name(creator))
                matches = [a for a in auths if key_name in {name_key((a.get('author') or {}).get('display_name')),name_key(a.get('raw_author_name'))}]
                for a in matches:
                    person = a.get('author') or {}
                    observed = sorted({v for value in [person.get('orcid'),a.get('raw_orcid'),*(person.get('observed_orcids') or [])] if (v:=normalize_orcid(value))})
                    for orcid in observed:
                        evidence = {'orcid':orcid,'name':person.get('display_name') or a.get('raw_author_name'),
                            'author_id':person.get('id'),'institutions':[i.get('display_name') for i in a.get('institutions',[])],
                            'work_id':oid,'lot':lot,'multiple_orcids':len(observed)>1,'multiple_authors':len(matches)>1,
                            'method':'OpenAlex: nome no mesmo trabalho; revisar identidade'}
                        c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?)',(key,orcid,'OpenAlex',json.dumps(evidence,ensure_ascii=False)))
        population = None
        if current_app.config.get('ARGILOTECA_POPULATION_ENABLED'):
            from ..population.snapshot import extend
            population = extend(c, job)
        c.commit()
        summary = dict(c.execute('SELECT "published_openalex",count(*) FROM works').fetchall())
        summary.update(dict(c.execute('SELECT "creator_occurrences",count(*) FROM occurrences').fetchall()))
        summary.update({'author_name_groups':c.execute('SELECT count(DISTINCT gid) FROM occurrences').fetchone()[0],
            'occurrences_with_candidates':c.execute('SELECT count(DISTINCT occurrence) FROM candidates').fetchone()[0],
            'sources':sources,'duplicate_identities_excluded':duplicates,'prepared_at':datetime.now(timezone.utc).isoformat()})
        c.close();os.chmod(temporary,0o600);os.replace(temporary,destination)
        job.snapshot={'schema':1,'sha256':file_hash(destination), **({'population':population} if population else {})};job.result=summary;job.state='completed'
    finally:
        c.close()
        if accepted is not None: accepted.close()
        if os.path.exists(temporary): os.unlink(temporary)


def add_occurrences(c, uid, data, kind, approved_ids=None):
    ids=work_ids(data) if approved_ids is None else approved_ids
    oid=next(iter(ids)) if len(ids)==1 else None
    for slot,creator in enumerate(data.get('metadata',{}).get('creators',[])):
        person=creator.get('person_or_org') or {}
        if person.get('type') != 'personal': continue
        orcids=[x['identifier'] for x in person.get('identifiers',[]) if x.get('scheme')=='orcid']
        key=digest([uid,kind,slot,creator])
        c.execute('INSERT INTO occurrences VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (key,creator_group(creator),data['id'],kind,slot,creator_name(creator),data.get('metadata',{}).get('title',''),
             json.dumps(creator,ensure_ascii=False),uid,'; '.join(orcids),oid,doi_of(data)))


def statistics(c, year_from=None, year_to=None, source_type='', subject='', primary_topic='', subfield='', field='', domain='', enrichment='none'):
    from .enrichment import attach, analytical_statistics
    version=attach(c,enrichment)
    where=[];params=[]
    for key,value,op in (('year',year_from,'>='),('year',year_to,'<='),('source_type',source_type,'=')):
        if value is not None and value!='':where.append('w.'+key+op+'?');params.append(value)
    if subject:
        # Materialize matching IDs once per query, rather than rerunning a
        # correlated tag scan for every joined author/institution/subject row.
        where.append("w.rid IN (SELECT rid FROM tags WHERE kind IN ('subject','keyword','topic') AND lower(label) LIKE lower(?))")
        params.append('%'+subject+'%')
    for level,value in [('primary_topic',primary_topic),('subfield',subfield),('field',field),('domain',domain)]:
        if value:
            path='$.primary_topic.id' if level=='primary_topic' else '$.primary_topic.'+level+'.id'
            where.append('w.rid IN (SELECT rid FROM approved WHERE json_extract(payload,?)=?)');params.extend([path,value])
    clause=' WHERE '+' AND '.join(where) if where else ''
    total=c.execute('SELECT count(*) FROM works w'+clause,params).fetchone()[0]
    def query(sql):return [dict(r) for r in c.execute(sql,params)]
    result={'total':total,'with_sources':c.execute('SELECT count(*) FROM works w'+clause+(' AND ' if where else ' WHERE ')+'w.source_id IS NOT NULL',params).fetchone()[0],
        'with_citations':c.execute('SELECT count(*) FROM works w'+clause+(' AND ' if where else ' WHERE ')+'w.citations IS NOT NULL',params).fetchone()[0],
        'years':query('SELECT year label,count(*) n FROM works w'+clause+' GROUP BY year ORDER BY year'),
        'journals':query('SELECT source label,source_id,count(*) n FROM works w'+clause+' GROUP BY source_id,source ORDER BY n DESC,label LIMIT 15'),
        'authors':query('SELECT a.aid,min(a.name) label,count(DISTINCT w.rid) n FROM works w JOIN authorship a ON w.rid=a.rid'+clause+' GROUP BY a.aid ORDER BY n DESC,label LIMIT 15'),
        'citations':query('SELECT w.rid,w.title label,w.citations n FROM works w'+clause+(' AND ' if where else ' WHERE ')+'w.citations IS NOT NULL ORDER BY n DESC,w.rid LIMIT 15')}
    result['summary']=dict(c.execute('SELECT count(DISTINCT source_id) sources,CASE WHEN count(*)=0 THEN 0 ELSE sum(citations) END citations,min(year) first_year,max(year) last_year FROM works w'+clause,params).fetchone())
    result['summary']['authors']=c.execute('SELECT count(DISTINCT a.aid) FROM works w JOIN authorship a ON w.rid=a.rid'+clause,params).fetchone()[0]
    result['source_types']=query('SELECT source_type label,count(*) n FROM works w'+clause+' GROUP BY source_type ORDER BY n DESC,label')
    for kind in ('subject','keyword','topic','country','institution'):
        result[kind]=[dict(r) for r in c.execute('SELECT t.id,t.label,count(DISTINCT w.rid) n FROM works w JOIN tags t ON w.rid=t.rid'+clause+(' AND ' if where else ' WHERE ')+'t.kind=? GROUP BY t.id,t.label ORDER BY n DESC,t.label LIMIT 15',[*params,kind])]
    result.update(analytical_statistics(c,clause,params,version))
    return result
