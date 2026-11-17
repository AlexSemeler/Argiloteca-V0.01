"""Immutable, source-backed census. Never changes native metadata or source lots."""
from collections import defaultdict
import json
from pathlib import Path
import re

from flask import current_app
from invenio_db import db
from sqlalchemy import text

from ..openalex.adapters import confined, digest, read_json
from ..openalex.analytics import creator_group, creator_name, doi_of, name_key, work_ids
from ..openalex.orcid import normalize_orcid
from ..openalex.preview import file_hash, iter_records, raw_items
from ..openalex.service import repository_handle

SOURCES = {'openalex': 'OpenAlex', 'pangaea': 'PANGAEA', 'mendeley': 'Mendeley Data',
           'lume': 'LUME UFRGS', 'ufsc': 'UFSC', 'unknown': 'Sem fonte identificada'}
PREPARE = {'prepare': 'openalex', 'pan_prepare': 'pangaea', 'men_prepare': 'mendeley', 'oai_prepare': 'repositories'}
IMPORT = {'import': 'openalex', 'pan_import': 'pangaea', 'men_import': 'mendeley', 'oai_import': 'repositories'}


def identifiers(data):
    """Only structured identifiers; never mine descriptions, names or references."""
    result = {'openalex:' + value for value in work_ids(data)}
    doi = doi_of(data)
    if doi and re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        result.add('doi:' + doi)
    for item in data.get('metadata', {}).get('identifiers', []) or []:
        declared = re.sub(r'^(?:https?://(?:dx\.)?doi.org/|doi:\s*)', '', str(item.get('identifier', '')).strip(), flags=re.I).lower()
        if re.fullmatch(r'10\.\d{4,9}/\S+', declared):
            result.add('doi:' + declared)
        handle = repository_handle(item)
        if handle:
            result.add('handle:' + handle)
    return result


def orcid_state(creator):
    values = [x.get('identifier') for x in creator.get('person_or_org', {}).get('identifiers', []) if x.get('scheme') == 'orcid']
    valid = {v for x in values if (v := normalize_orcid(x))}
    if not values:
        return '', 'missing'
    if len(valid) != 1 or any(not normalize_orcid(x) for x in values):
        return '; '.join(str(x) for x in values), 'conflict'
    return next(iter(valid)), 'linked'


def schema(c):
    c.executescript('''
      CREATE INDEX IF NOT EXISTS population_occurrence_rid ON occurrences(rid);
      CREATE TABLE p_records(id TEXT PRIMARY KEY,rid TEXT,uuid TEXT,kind TEXT,title TEXT,year INTEGER,
        type TEXT,doi TEXT,published INTEGER,draft INTEGER,review TEXT,row_key TEXT,payload TEXT,conflict INTEGER DEFAULT 0);
      CREATE TABLE p_tokens(token TEXT,record TEXT,UNIQUE(token,record));
      CREATE INDEX p_token ON p_tokens(token);
      CREATE TABLE p_sources(record TEXT,source TEXT,UNIQUE(record,source));
      CREATE INDEX p_source ON p_sources(source,record);
      CREATE TABLE p_entries(id TEXT PRIMARY KEY,record TEXT,source TEXT,lot TEXT,row_key TEXT,review TEXT,payload TEXT,sha TEXT);
      CREATE TABLE p_authors(key TEXT PRIMARY KEY,record TEXT,gid TEXT,slot INTEGER,name TEXT,orcid TEXT,status TEXT,
        native_key TEXT,creator TEXT,UNIQUE(record,slot));
      CREATE INDEX p_author_group ON p_authors(gid);
      CREATE TABLE p_lots(source TEXT,lot TEXT,count INTEGER,complete INTEGER,coverage TEXT,sha TEXT,UNIQUE(source,lot));
      CREATE TABLE p_warnings(source TEXT,lot TEXT,message TEXT);
      CREATE TABLE p_pdfs(sha TEXT PRIMARY KEY,bytes INTEGER,job TEXT);
    ''')


def native_record(c, uid, data, kind):
    rid = data.get('id')
    if not rid:
        return
    key = 'native:' + rid
    md = data.get('metadata') or {}
    date = str(md.get('publication_date', ''))
    year = int(date[:4]) if re.match(r'^\d{4}', date) else None
    prior = c.execute('SELECT published,draft FROM p_records WHERE id=?', (key,)).fetchone()
    published = int(kind == 'published' or bool(prior and prior[0]))
    draft = int(kind == 'draft' or bool(prior and prior[1]))
    c.execute('INSERT OR REPLACE INTO p_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
              (key, rid, str(uid), kind, md.get('title', ''), year, (md.get('resource_type') or {}).get('id', ''),
               doi_of(data), published, draft, '', '', json.dumps(data, ensure_ascii=False), 0))
    for token in identifiers(data):
        c.execute('INSERT OR IGNORE INTO p_tokens VALUES(?,?)', (token, key))
        source = 'openalex' if token.startswith('openalex:') else 'lume' if token.startswith('handle:10183/') else 'ufsc' if token.startswith('handle:123456789/') else 'pangaea' if token.startswith('doi:10.1594/pangaea.') else 'mendeley' if token.startswith('doi:10.17632/') else None
        if source:
            c.execute('INSERT OR IGNORE INTO p_sources VALUES(?,?)', (key, source))


def add_authors(c, record, data, native=False):
    for slot, creator in enumerate(data.get('metadata', {}).get('creators', [])):
        if creator.get('person_or_org', {}).get('type') != 'personal':
            continue
        orcid, status = orcid_state(creator)
        occurrence = None
        if native:
            row = c.execute('SELECT key FROM occurrences WHERE rid=? AND kind=? AND slot=? AND creator=?',
                            (record['rid'], record['kind'], slot, json.dumps(creator, ensure_ascii=False))).fetchone()
            occurrence = row[0] if row else None
        c.execute('INSERT INTO p_authors VALUES(?,?,?,?,?,?,?,?,?)',
                  (digest([record['id'], slot, creator]), record['id'], creator_group(creator), slot,
                   creator_name(creator), orcid, status, occurrence, json.dumps(creator, ensure_ascii=False)))


def add_entry(c, source, lot, row_key, payload, review='', observation=None):
    """A source row is an observation, not another native record."""
    entry = digest([source, lot, row_key if observation is None else observation])
    c.execute('INSERT OR REPLACE INTO p_entries VALUES(?,?,?,?,?,?,?,?)',
              (entry, '', source, lot, row_key, review, json.dumps(payload, ensure_ascii=False), digest(payload)))


def consolidate(c):
    """Group recovered observations transitively by strong IDs; never merge native RIDs."""
    parent = {}; aliases = {}; entries = {}
    def find(key):
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]; key = parent[key]
        return key
    for row in c.execute('SELECT id,payload FROM p_entries ORDER BY id'):
        key, body = row; payload = json.loads(body); ids = identifiers(payload)
        entries[key] = ids; find(key)
        for token in ids:
            if token in aliases:
                a, b = find(key), find(aliases[token]); parent[max(a, b)] = min(a, b)
            aliases[token] = key
    groups = defaultdict(list)
    for key in entries:
        groups[find(key)].append(key)
    for keys in groups.values():
        ids = set().union(*(entries[key] for key in keys)); native = set()
        for token in ids:
            native.update(r[0] for r in c.execute('SELECT record FROM p_tokens WHERE token=?', (token,)))
        conflict = len(native) > 1
        representative = c.execute('SELECT * FROM p_entries WHERE id IN (' + ','.join('?' for _ in keys) + ') ORDER BY (review!=\'\') DESC,lot DESC LIMIT 1', keys).fetchone()
        fields = [d[0] for d in c.execute('SELECT * FROM p_entries LIMIT 0').description]
        chosen = dict(zip(fields, representative)); payload = json.loads(chosen['payload'])
        record = next(iter(native)) if len(native) == 1 else 'recovered:' + min(keys)
        if len(native) != 1:
            md = payload.get('metadata') or {}; date = str(md.get('publication_date', ''))
            year = int(date[:4]) if re.match(r'^\d{4}', date) else None
            c.execute('INSERT INTO p_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (record, '', '', 'recovered', md.get('title', ''), year, (md.get('resource_type') or {}).get('id', ''),
                       doi_of(payload), 0, 0, chosen['review'], chosen['row_key'], chosen['payload'], int(conflict)))
        if conflict:
            for nid in native:
                c.execute('UPDATE p_records SET conflict=1 WHERE id=?', (nid,))
        for key in keys:
            c.execute('UPDATE p_entries SET record=? WHERE id=?', (record, key))
            source = c.execute('SELECT source FROM p_entries WHERE id=?', (key,)).fetchone()[0]
            c.execute('INSERT OR IGNORE INTO p_sources VALUES(?,?)', (record, source))
            # Evidence requires the same identified work AND exact normalized name.
            # Multiple source slots with the same name remain ambiguous suggestions.
            if len(native) == 1:
                data = json.loads(c.execute('SELECT payload FROM p_entries WHERE id=?', (key,)).fetchone()[0])
                for source_creator in data.get('metadata', {}).get('creators', []):
                    if source_creator.get('person_or_org', {}).get('type') != 'personal': continue
                    orcid, state = orcid_state(source_creator)
                    if state != 'linked': continue
                    for occurrence, creator in c.execute('SELECT key,creator FROM occurrences WHERE rid=?', (record.removeprefix('native:'),)):
                        if name_key(creator_name(json.loads(creator))) != name_key(creator_name(source_creator)): continue
                        evidence = {'orcid': orcid, 'name': creator_name(source_creator), 'lot': c.execute('SELECT lot FROM p_entries WHERE id=?', (key,)).fetchone()[0],
                                    'source': SOURCES[source], 'method': 'Nome no mesmo registro identificado; revisar identidade'}
                        c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?)',
                                  (occurrence, orcid, SOURCES[source], json.dumps(evidence, ensure_ascii=False)))
    for row in c.execute('SELECT id,rid,kind,payload FROM p_records').fetchall():
        record = dict(zip(('id', 'rid', 'kind', 'payload'), row))
        add_authors(c, record, json.loads(record['payload']), native=record['kind'] != 'recovered')
    # Duplicate native identifiers are reported, never silently collapsed.
    c.execute('UPDATE p_records SET conflict=1 WHERE id IN (SELECT record FROM p_tokens WHERE token IN (SELECT token FROM p_tokens GROUP BY token HAVING count(*)>1))')
    c.execute("INSERT OR IGNORE INTO p_sources SELECT id,'unknown' FROM p_records WHERE id NOT IN (SELECT record FROM p_sources)")


def source_lots(c):
    """Read immutable collected payloads; skip incomplete or corrupt lots explicitly."""
    configs = [('openalex', current_app.config['ARGILOTECA_OPENALEX_ROOT'], 'v59_*', 'openalex_argiloteca.json'),
               ('pangaea', current_app.config.get('ARGILOTECA_PANGAEA_ROOT'), 'pan_*', 'records.json'),
               ('mendeley', current_app.config.get('ARGILOTECA_MENDELEY_ROOT'), 'men_*', 'records.json'),
               ('repositories', current_app.config.get('ARGILOTECA_REPOSITORIES_ROOT'), 'oai_*', 'records.json')]
    # Latest reviewed payload wins within that specific lot; raw artifacts stay intact.
    reviews = {}
    from ..openalex.models import OpenAlexJob
    for job in OpenAlexJob.query.filter(OpenAlexJob.kind.in_(PREPARE), OpenAlexJob.state == 'review').order_by(OpenAlexJob.created.desc()).yield_per(5):
        source = PREPARE[job.kind]; lot = job.params.get('lot')
        if not lot or (source, lot) in reviews: continue
        reviews[(source, lot)] = job
    for provider, base, pattern, filename in configs:
        if not base: continue
        for folder in sorted((Path(base) / 'lotes').glob(pattern), reverse=True):
            try:
                folder = confined(folder, Path(base) / 'lotes')
                excluded = current_app.config.get('ARGILOTECA_POPULATION_EXCLUDED_LOTS', {})
                if folder.name in excluded:
                    raise ValueError('Excluído deste retrato por configuração: ' + str(excluded[folder.name]))
                marker = read_json(folder / 'resultado.json', folder)
                if marker.get('status') != 'coleta_concluida':
                    raise ValueError('Lote incompleto; registros excluídos do retrato.')
                path = confined(folder / filename, folder); signature = file_hash(path)
                for relative, expected in (marker.get('input_hashes') or {}).items():
                    if file_hash(confined(folder / relative, folder)) != expected:
                        raise ValueError('Hash do lote divergente; registros excluídos do retrato.')
                review = reviews.get((provider, folder.name))
                if review:
                    for relative, value in review.snapshot.get('input_hashes', {}).items():
                        if file_hash(confined(folder / relative, folder)) != value:
                            raise ValueError('Origem da revisão alterada; registros excluídos do retrato.')
                source = provider
                if provider == 'repositories':
                    source = (marker.get('coverage') or {}).get('scope', {}).get('repository')
                    if source not in ('lume', 'ufsc'): raise ValueError('Repositório não identificado.')
                reviewed = {r['key']: r for r in iter_records(review.snapshot)} if review else {}
                # Enumerate first so malformed lots cannot leave partial counts.
                observations = []
                reviewed_ids = {}
                if provider == 'openalex':
                    for candidate in reviewed.values():
                        for token in identifiers(candidate['payload']):
                            reviewed_ids.setdefault(token, candidate)
                for number, (_, raw) in enumerate(raw_items(path), 1):
                    if raw is None: continue
                    payload = raw if provider == 'openalex' else raw['payload']
                    key = raw.get('key') or str(number)
                    if provider == 'openalex':
                        # Legacy review keys come from the verified converter; use
                        # exact payload identifiers to pair them, never titles.
                        match = next((reviewed_ids[token] for token in sorted(identifiers(payload)) if token in reviewed_ids), None)
                    else: match = reviewed.get(key)
                    observations.append((match['key'] if match else key, match['payload'] if match else payload, review.id if match else ''))
                if len(observations) != marker.get('payloads'):
                    raise ValueError('Contagem de registros diverge do manifesto.')
                c.execute('INSERT INTO p_lots VALUES(?,?,?,?,?,?)', (source, folder.name, len(observations), 1, json.dumps(marker.get('coverage', {})), signature))
                for observation, (key, payload, review_id) in enumerate(observations, 1):
                    add_entry(c, source, folder.name, key, payload, review_id, observation=observation)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                c.execute('INSERT INTO p_warnings VALUES(?,?,?)', (provider, folder.name, str(exc)[:350]))


def extend(c, job):
    schema(c); retired = set()
    for uid, data, state in db.session.execute(text('SELECT id::text,json,deletion_status FROM rdm_records_metadata').execution_options(stream_results=True, yield_per=100)).yield_per(100):
        if state != 'P': retired.add(str(uid)); continue
        if data: native_record(c, uid, data, 'published')
    for uid, data in db.session.execute(text('SELECT id::text,json FROM rdm_drafts_metadata WHERE json IS NOT NULL').execution_options(stream_results=True, yield_per=100)).yield_per(100):
        if str(uid) not in retired: native_record(c, uid, data, 'draft')
    source_lots(c)
    consolidate(c)
    from ..openalex.models import OpenAlexJob
    # Journal attribution supplements declared IDs. It never claims that a
    # source row imported successfully merely because its collection completed.
    for journal in OpenAlexJob.query.filter(OpenAlexJob.kind.in_(IMPORT), OpenAlexJob.state == 'completed').yield_per(10):
        provider = IMPORT[journal.kind]
        for outcome in (journal.result or {}).get('items', {}).values():
            source = provider
            rid = outcome.get('draft_id')
            if outcome.get('state') not in ('created', 'updated', 'duplicate') or not rid: continue
            key = 'native:' + rid
            if source == 'repositories':
                row = c.execute("SELECT source FROM p_sources WHERE record=? AND source IN ('lume','ufsc')", (key,)).fetchone()
                if not row: continue
                source = row[0]
            if c.execute('SELECT 1 FROM p_records WHERE id=?', (key,)).fetchone():
                c.execute('DELETE FROM p_sources WHERE record=? AND source=\'unknown\'', (key,))
                c.execute('INSERT OR IGNORE INTO p_sources VALUES(?,?)', (key, source))
    for journal in OpenAlexJob.query.filter_by(kind='oai_pdf', state='completed').yield_per(10):
        for item in (journal.result or {}).get('pdfs', {}).get('items', {}).values():
            for file in item.get('files', []):
                sha = file.get('sha256', '')
                if re.fullmatch('[a-f0-9]{64}', sha):
                    c.execute('INSERT OR IGNORE INTO p_pdfs VALUES(?,?,?)', (sha, file.get('bytes', 0), journal.id))
    return {'schema': 1, 'records': c.execute('SELECT count(*) FROM p_records').fetchone()[0],
            'warnings': c.execute('SELECT count(*) FROM p_warnings').fetchone()[0]}
