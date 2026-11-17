"""Disk-backed, immutable previews; never materialize the complete raw corpus.

The verified V59 normalizer and transitive DOI/OpenAlex merge are reused. Full
raw candidates and original payloads remain in the private SQLite artifact.
Only page-sized records enter the web process or a selected import snapshot.
"""
from contextlib import closing
from copy import deepcopy
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from flask import current_app

from .adapters import confined, converter, digest, lot_path, read_json


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class JSONStream:
    """Incremental stdlib decoder, bounded by one JSON value, not its array."""
    def __init__(self, stream):
        self.stream, self.buffer, self.eof = stream, '', False
        self.decoder = json.JSONDecoder(parse_constant=self.invalid)

    @staticmethod
    def invalid(value):
        raise ValueError('Constante JSON invalida: ' + value)

    def peek(self):
        self.buffer = self.buffer.lstrip()
        while not self.buffer and not self.eof:
            part = self.stream.read(65536)
            self.eof = not part
            self.buffer += part
            self.buffer = self.buffer.lstrip()
        return self.buffer[:1]

    def take(self, expected):
        if self.peek() != expected:
            raise ValueError('Estrutura JSON inválida; esperado ' + expected)
        self.buffer = self.buffer[1:]

    def value(self):
        self.peek()
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer)
                # A number at the chunk boundary may still continue.
                if end == len(self.buffer) and not self.eof:
                    raise json.JSONDecodeError('boundary', self.buffer, end)
                self.buffer = self.buffer[end:]
                return value
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError('JSON incompleto ou inválido.') from None
                if len(self.buffer) > 16 * 1024 * 1024:
                    raise ValueError('Objeto JSON excedeu 16 MiB.')
                part = self.stream.read(65536)
                self.eof = not part
                self.buffer += part

    def array(self):
        self.take('[')
        if self.peek() == ']':
            self.take(']')
            return
        while True:
            yield self.value()
            if self.peek() == ']':
                self.take(']')
                return
            self.take(',')


def raw_items(path):
    """Support the same top-level list/results/records/data envelopes as V59."""
    with Path(path).open(encoding='utf-8-sig') as stream:
        parser = JSONStream(stream)
        if parser.peek() == '[':
            for row in parser.array():
                if isinstance(row, dict):
                    yield '', row
        elif parser.peek() == '{':
            parser.take('{')
            while parser.peek() != '}':
                key = parser.value()
                if not isinstance(key, str):
                    raise ValueError('Chave JSON inválida.')
                parser.take(':')
                if key in ('results', 'records', 'data') and parser.peek() == '[':
                    # Emit the envelope even when its list is empty; priority
                    # must match raw_records(), independent of JSON key order.
                    yield key, None
                    for row in parser.array():
                        if isinstance(row, dict):
                            yield key, row
                else:
                    parser.value()
                if parser.peek() == '}':
                    break
                parser.take(',')
                if parser.peek() == '}':
                    raise ValueError('Vírgula final inválida em JSON.')
            parser.take('}')
        else:
            parser.value()
        if parser.peek():
            raise ValueError('Conteúdo após o JSON.')


def connect(path, readonly=False):
    db = sqlite3.connect('file:' + str(path) + '?mode=ro', uri=True) if readonly else sqlite3.connect(path)
    db.execute('PRAGMA cache_size=-2048')
    db.execute('PRAGMA temp_store=FILE')
    return db


def source_records(root, name, staging, corrections=None, limit=0, progress=lambda *a: None):
    """Normalize a row at a time and merge complete identity components on disk."""
    metadata, reader, version = converter(root)
    if not isinstance(limit, int) or not 0 <= limit <= 10000:
        raise ValueError('Limite fora da faixa.')
    lot = reader.completed_lot(lot_path(root, name))
    corrections = corrections or {}
    allowed = {'creators', 'title', 'publication_date', 'resource_type', 'description', 'languages', 'rights', 'subjects', 'publisher', 'contributors', 'additional_titles', 'additional_descriptions', 'dates', 'version', 'sizes', 'formats', 'references', 'funding', 'locations'}
    if not isinstance(corrections, dict) or any(not isinstance(k, str) or not isinstance(v, dict) or set(v)-allowed for k, v in corrections.items()):
        raise ValueError('Correções devem conter apenas campos descritivos por chave de origem.')
    hashes = {f: file_hash(lot/f) for f in ('manifest.tsv', 'resultado.json')}
    warnings, envelopes, raw_failed = [], set(), False
    staging.executescript('CREATE TABLE raw (seq INTEGER PRIMARY KEY, envelope TEXT, doi TEXT, work TEXT, body TEXT); CREATE INDEX raw_doi ON raw(doi); CREATE INDEX raw_work ON raw(work); CREATE TABLE prepared (seq INTEGER PRIMARY KEY, component INTEGER, body TEXT); CREATE INDEX prepared_component ON prepared(component);')
    raw = lot/'openalex_raw.json'
    if raw.exists():
        try:
            reader.confined_file(raw, lot)
            if raw.stat().st_size > 256*1024*1024:
                raise ValueError('Dados brutos acima do limite de 256 MiB.')
            hashes[raw.name] = file_hash(raw)
            for seq, (envelope, item) in enumerate(raw_items(raw)):
                envelopes.add(envelope)
                if item is not None:
                    doi, work = reader.raw_identity(item)
                    staging.execute('INSERT INTO raw VALUES (?,?,?,?,?)', (seq, envelope, doi, work, json.dumps(item, ensure_ascii=False)))
                if seq % 500 == 0:
                    staging.commit()
                    progress('raw', seq)
        except (OSError, ValueError, UnicodeError) as exc:
            raw_failed = True
            staging.execute('DELETE FROM raw')
            warnings.append(f'Dados brutos nao aproveitados: {exc}')
    envelope = next((e for e in ('', 'results', 'records', 'data') if e in envelopes), '')
    if raw.exists() and not raw_failed and not staging.execute('SELECT 1 FROM raw WHERE envelope=? LIMIT 1', (envelope,)).fetchone():
        warnings.append('openalex_raw.json nao tem uma lista reconhecida de obras; normalizacao usa os payloads e registra as limitacoes.')
    parent, seen, keys = [], {}, set()

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    manifest = reader.confined_file(lot/'manifest.tsv', lot)
    if manifest.stat().st_size > 256*1024*1024:
        raise ValueError('Manifesto acima do limite de 256 MiB.')
    with manifest.open(encoding='utf-8-sig', newline='') as stream:
        for lineno, values in enumerate(csv.reader(stream, delimiter='\t'), 1):
            if not values or not any(values):
                continue
            origin = dict(zip(reader.FIELDS, (values+['']*8)[:8]))
            origin.update(manifest_line=lineno, lot=str(lot))
            issues, payload = [], {}
            if len(values) != 8:
                issues.append(reader.issue('manifest_columns', f'Linha com {len(values)} colunas; esperado 8.', f'manifest.tsv:{lineno}'))
            if not origin['key']:
                issues.append(reader.issue('missing_source_key', 'Chave vazia no manifesto.', f'manifest.tsv:{lineno}'))
            keys.add(origin['key'])
            if len(values) == 8:
                try:
                    path = reader.resolve_payload(origin['payload_path'], lot)
                    content = reader.read_bytes(path, 16*1024*1024)
                    signature = reader.sha(content)
                    hashes[str(path.relative_to(lot))] = signature
                    payload = reader.json_loads(content.decode('utf-8-sig'))
                    if not isinstance(payload, dict):
                        raise ValueError('Payload precisa ser objeto JSON.')
                    origin.update(resolved_payload=str(path), payload_sha256=signature)
                except (ValueError, OSError, UnicodeError) as exc:
                    payload = {}
                    issues.append(reader.issue('payload_read', str(exc), origin['payload_path']))
            candidates = []
            origin_doi = metadata.normalize_doi(origin['doi'])
            origin_work = metadata.normalize_openalex_id(origin['openalex_id'])
            # DOI matches precede work matches, as in the original reader.
            for column, value in (('doi', origin_doi), ('work', origin_work)):
                if value:
                    for (body,) in staging.execute(f'SELECT body FROM raw WHERE envelope=? AND {column}=? ORDER BY seq', (envelope, value)):
                        candidate = json.loads(body)
                        if candidate not in candidates:
                            candidates.append(candidate)
            item = candidates[0] if len(candidates) == 1 else None
            if item:
                doi, work = reader.raw_identity(item)
                if (doi and origin_doi and doi != origin_doi) or (work and origin_work and work != origin_work):
                    issues.append(reader.issue('raw_identity_conflict', 'Identidade dos dados brutos diverge do manifesto; dados brutos nao aplicados.', 'openalex_raw.json'))
                    item = None
            elif candidates:
                issues.append(reader.issue('raw_ambiguous', 'Mais de uma representacao bruta corresponde a identidade; mantidas como proveniencia, sem enriquecimento automatico.', 'openalex_raw.json', 'warning'))
            original = deepcopy(payload)
            patch = corrections.get(origin['key'])
            if patch:
                if not isinstance(payload.get('metadata'), dict):
                    payload['metadata'] = {}
                payload['metadata'].update(deepcopy(patch))
                origin['manual_fields'] = list(patch)
            row = metadata.normalize_payload(payload, origin, item)
            row['issues'] = issues + row.get('issues', [])
            row['provenance'] = [{'origin': origin, 'original_payload': original, 'raw_candidates': candidates, 'manual_corrections': patch or {}, 'omitted_fields': row.pop('omitted_fields', {}), 'field_sources': row.pop('field_sources', {})}]
            seq = len(parent)
            parent.append(seq)
            for scheme in ('doi', 'openalex_id'):
                value = row.get('identity', {}).get(scheme)
                if value:
                    token = (scheme, value)
                    if token in seen:
                        parent[find(seq)] = find(seen[token])
                    seen[token] = seq
            staging.execute('INSERT INTO prepared VALUES (?,?,?)', (seq, seq, json.dumps(row, ensure_ascii=False)))
            if len(parent) % 100 == 0:
                staging.commit()
                progress('normalize', len(parent))
    if set(corrections)-keys:
        raise ValueError('Correcoes incluem chaves ausentes do manifesto: ' + ', '.join(sorted(set(corrections)-keys)))
    if not parent:
        raise ValueError('Manifesto nao contem registros.')
    staging.executemany('UPDATE prepared SET component=? WHERE seq=?', ((find(i), i) for i in range(len(parent))))
    staging.commit()
    groups = [r[0] for r in staging.execute('SELECT component FROM prepared GROUP BY component ORDER BY min(seq)')]
    total = len(groups)
    statuses = dict.fromkeys(('apto', 'apto_com_alertas', 'bloqueado'), 0)

    def records():
        for component in groups[:limit or None]:
            entries = [json.loads(r[0]) for r in staging.execute('SELECT body FROM prepared WHERE component=? ORDER BY seq', (component,))]
            row = reader.merge_records(entries)[0]
            row['payload_sha256'] = digest(row['payload'])
            statuses[row['status']] += 1
            yield row

    snapshot = {'format': reader.FORMAT, 'source': str(lot), 'input_hashes': hashes, 'source_warnings': warnings, 'converter': version, 'corrections': corrections}
    if (lot/'busca.json').exists():
        snapshot['extraction_search'] = read_json(lot/'busca.json', lot, 128*1024)
        hashes['busca.json'] = file_hash(lot/'busca.json')
    snapshot['summary'] = {'manifest_rows': len(parent), 'unique_records': total, 'selected_records': len(groups[:limit or None]), 'duplicates_merged': len(parent)-total, **statuses}
    return snapshot, records(), statuses


def store_path(descriptor, verify=True):
    jid = descriptor.get('id', '')
    if len(jid) != 32 or any(c not in '0123456789abcdef' for c in jid) or descriptor.get('schema') != 1:
        raise ValueError('Identificador de prévia inválido.')
    folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'previews'
    path = confined(folder/(jid+'.sqlite'), folder)
    if verify and (not path.is_file() or path.stat().st_size != descriptor['bytes'] or file_hash(path) != descriptor['sha256']):
        raise ValueError('Prévia ausente ou alterada; prepare uma nova revisão.')
    return path


def decode(body, signature):
    row = json.loads(body)
    if digest(row) != signature:
        raise ValueError('Registro da prévia alterado; importação interrompida.')
    return row


def iter_records(snapshot, keys=None):
    excluded=set(snapshot.get('admin_excluded_records',[]))
    descriptor = snapshot.get('record_store')
    if not descriptor:
        yield from (r for r in snapshot.get('records', []) if r['key'] not in excluded and (keys is None or r['key'] in keys))
        return
    with closing(connect(store_path(descriptor), readonly=True)) as db:
        query, args = 'SELECT body,sha256 FROM records', []
        if keys is not None:
            if not keys:
                return
            query += ' WHERE key IN (' + ','.join('?' for _ in keys) + ')'
            args = list(keys)
        cursor = db.execute(query+' ORDER BY seq', args)
        while batch := cursor.fetchmany(20):
            for body, signature in batch:
                row=decode(body,signature)
                if row['key'] not in excluded:yield row


def page_records(snapshot, q='', status='', page=1):
    excluded=set(snapshot.get('admin_excluded_records',[]))
    descriptor = snapshot.get('record_store')
    if not descriptor:
        rows = [r for r in snapshot.get('records', []) if r['key'] not in excluded and (not q or q.casefold() in json.dumps({'metadata': r['payload'].get('metadata'), 'identity': r['identity']}, ensure_ascii=False).casefold()) and (not status or r['status'] == status)]
        total = len(rows)
        pages = max(1, (total+19)//20)
        page = min(page, pages)
        return rows[(page-1)*20:page*20], total, page, pages
    with closing(connect(store_path(descriptor), readonly=True)) as db:
        where, args = [], []
        if excluded:
            where.append('key NOT IN ('+','.join('?' for _ in excluded)+')');args.extend(sorted(excluded))
        if q:
            where.append('instr(search,?)>0'); args.append(q.casefold())
        if status:
            where.append('status=?'); args.append(status)
        clause = ' WHERE '+' AND '.join(where) if where else ''
        total = db.execute('SELECT count(*) FROM records'+clause, args).fetchone()[0]
        pages = max(1, (total+19)//20)
        page = min(page, pages)
        rows = [decode(*r) for r in db.execute('SELECT body,sha256 FROM records'+clause+' ORDER BY seq LIMIT 20 OFFSET ?', [*args, (page-1)*20])]
        return rows, total, page, pages


def build(job, root):
    """Publish an immutable artifact atomically; partial work is never importable."""
    from datetime import datetime, timezone
    from invenio_db import db
    from .service import review_context, review_snapshot
    folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE'])/'previews'
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = confined(folder/(job.id+'.sqlite'), folder)
    if target.exists():
        if getattr(job, 'snapshot', {}).get('record_store', {}).get('id') == job.id:
            # A previously journalled artifact already has its trusted checksum.
            store_path(job.snapshot['record_store'])
            from .adapters import verify_snapshot
            verify_snapshot(root, {**job.snapshot, 'records': []})
            return deepcopy(job.snapshot)
        # Crash between the atomic file rename and the journal commit: recover
        # the already complete artifact instead of rebuilding or overwriting it.
        with closing(connect(target, readonly=True)) as saved:
            metadata = json.loads(saved.execute('SELECT body FROM preview_metadata').fetchone()[0])
            count = saved.execute('SELECT count(*) FROM records').fetchone()[0]
        if metadata['params_sha256'] != digest(job.params) or metadata['actor'] != job.actor or metadata['snapshot']['summary']['selected_records'] != count:
            raise ValueError('Prévia preservada não corresponde a esta tarefa.')
        from .adapters import verify_snapshot
        snapshot = metadata['snapshot']
        verify_snapshot(root, {**snapshot, 'records': []})
        snapshot['record_store'] = {'schema': 1, 'id': job.id, 'sha256': file_hash(target), 'bytes': target.stat().st_size, 'count': count}
        return snapshot
    # A killed process cannot run finally. Remove only this locked job's
    # unpublished temporary artifacts when recovering, never another job's data.
    for prefix in ('.source-'+job.id+'-', '.preview-'+job.id+'-'):
        for abandoned in folder.glob(prefix+'*'):
            if abandoned.is_file() and not abandoned.is_symlink():
                abandoned.unlink()
    staging_fd, staging_path = tempfile.mkstemp(prefix='.source-'+job.id+'-', dir=folder)
    final_fd, final_path = tempfile.mkstemp(prefix='.preview-'+job.id+'-', dir=folder)
    os.close(staging_fd); os.close(final_fd)

    def progress(stage, count, total=None):
        job.result = {'progress': {'stage': stage, 'processed': count, 'total': total}}
        job.updated = datetime.now(timezone.utc)
        db.session.commit()

    try:
        progress('raw', 0)
        with closing(connect(staging_path)) as staging, closing(connect(final_path)) as output:
            output.execute('CREATE TABLE records (seq INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL, search TEXT NOT NULL)')
            output.execute('CREATE TABLE preview_metadata (body TEXT NOT NULL)')
            output.execute('CREATE INDEX record_status ON records(status)')
            snapshot, source, source_statuses = source_records(root, job.params['lot'], staging, job.params.get('corrections'), job.params.get('limit', 0), progress)
            context = review_context(root, job.actor)
            statuses = dict.fromkeys(source_statuses, 0)
            classified = needs_review = count = 0
            batch = []

            def flush():
                nonlocal classified, needs_review, count
                reviewed = review_snapshot(root, {'records': batch, 'summary': {}}, job.actor, context=context)
                for row in reviewed['records']:
                    count += 1
                    statuses[row['status']] += 1
                    classified += bool(row['classification']['communities'])
                    needs_review += row['classification']['state'] == 'needs_review'
                    search = json.dumps({'metadata': row['payload'].get('metadata'), 'identity': row['identity']}, ensure_ascii=False).casefold()
                    output.execute('INSERT INTO records VALUES (?,?,?,?,?,?)', (count, row['key'], row['status'], json.dumps(row, ensure_ascii=False), digest(row), search))
                output.commit()
                progress('validate', count, snapshot['summary']['selected_records'])
                batch.clear()

            for row in source:
                batch.append(row)
                if len(batch) == 20:
                    flush()
            if batch:
                flush()
            snapshot['source_summary'] = {**snapshot['summary'], **source_statuses}
            snapshot['summary'] = {**snapshot['summary'], **statuses}
            snapshot['classification'] = {'rule': context['classification'][1], 'classified': classified, 'needs_review': needs_review}
            # Detect concurrent source edits before publishing the snapshot.
            from .adapters import verify_snapshot
            verify_snapshot(root, {**snapshot, 'records': []})
            output.execute('INSERT INTO preview_metadata VALUES (?)', (json.dumps({'snapshot': snapshot, 'params_sha256': digest(job.params), 'actor': job.actor}, ensure_ascii=False),))
            output.commit()
        with open(final_path, 'rb') as handle:
            os.fsync(handle.fileno())
        signature, size = file_hash(final_path), Path(final_path).stat().st_size
        if target.exists():
            raise ValueError('Esta tarefa já possui uma prévia preservada. Prepare uma nova revisão.')
        os.replace(final_path, target)
        snapshot['record_store'] = {'schema': 1, 'id': job.id, 'sha256': signature, 'bytes': size, 'count': count}
        return snapshot
    finally:
        for name in (staging_path, final_path):
            if os.path.exists(name):
                os.unlink(name)
