"""Resumable public metadata snapshots. Each invocation reads at most one batch.

The active corpus is never the work area. A failed/partial scan cannot remove
records. All index writers use the same lock and generation fingerprint.
"""
import fcntl
import hashlib
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .index_sync import atomic_json, chunks, now, static_digest


class CheckpointConflict(ValueError):
    """The checkpoint cannot safely overwrite the current generation."""


def records_digest(conn):
    digest = hashlib.sha256()
    for row in conn.execute("SELECT * FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='registro_invenio' ORDER BY id"):
        digest.update(json.dumps(tuple(row), ensure_ascii=False).encode())
    return digest.hexdigest()


def manifest_digest(conn):
    value = json.loads(conn.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
    # These two fields are the only manifest changes owned by Library.index_approved.
    for key in ('counts', 'library_updated_at'):
        value.pop(key, None)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@contextmanager
def database(path):
    conn=sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


@contextmanager
def writer_lock(index):
    with Path(index).with_suffix('.sync.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def state(index):
    path = Path(index).with_suffix('.batch-status.json')
    return json.loads(path.read_text()) if path.exists() else {'state': 'idle', 'processed': 0}


def save(index, value):
    atomic_json(Path(index).with_suffix('.batch-status.json'), value)
    # Compatible with the existing RAG status boundary.
    atomic_json(Path(index).with_suffix('.sync-status.json'), value)


def backup(index, label):
    root = Path(index).parent / 'versions'
    root.mkdir(exist_ok=True)
    path = root / (label + '-' + uuid.uuid4().hex + '.sqlite3')
    with database(index) as source, database(path) as target:
        source.backup(target)
        if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('Backup integrity')
    os.chmod(path, 0o600)
    return {'name': path.name, 'sha256': sha(path), 'created_at': now()}


def start(index, actor='scheduler', batch_size=100, *, restart=False):
    index = Path(index)
    if not index.is_file() or index.is_symlink():
        raise ValueError('Existing corpus required')
    if not 1 <= int(batch_size) <= 500:
        raise ValueError('Batch size 1–500')
    with writer_lock(index):
        old = state(index)
        if old.get('state') in ('running', 'paused', 'failed', 'restart_required') and not restart:
            return old
        staging = index.with_suffix('.batch.sqlite3')
        previous = None
        if restart:
            # Preserve the interrupted work and its original status before resetting.
            folder = index.parent/'versions'/'checkpoints'/uuid.uuid4().hex
            folder.mkdir(parents=True, mode=0o700)
            atomic_json(folder/'status.json', old)
            if staging.is_file():
                with database(staging) as source, database(folder/'checkpoint.sqlite3') as target:
                    source.backup(target)
                    if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise ValueError('Checkpoint integrity')
                os.chmod(folder/'checkpoint.sqlite3', 0o600)
            previous = {'run_id': old.get('run_id'), 'processed': old.get('processed', 0),
                        'archive': folder.name, 'backup': backup(index, 'before-restart')}
        staging.unlink(missing_ok=True)
        with database(index) as source, database(staging) as target:
            source.backup(target)
            target.executescript('''
                DROP TABLE IF EXISTS sync_seen;
                DROP TABLE IF EXISTS sync_fts;
                DROP TABLE IF EXISTS sync_counts;
                CREATE TABLE sync_seen(rid TEXT PRIMARY KEY, updated TEXT);
                CREATE TABLE sync_fts(id TEXT PRIMARY KEY, position INTEGER UNIQUE);
                INSERT INTO sync_fts SELECT id,rowid FROM search;
                CREATE INDEX IF NOT EXISTS docs_record_id ON docs(json_extract(metadata,'$.record_id'));
            ''')
            original = static_digest(target)
            record_base = records_digest(target)
            manifest_base = manifest_digest(target)
        value = {'state': 'running', 'run_id': uuid.uuid4().hex, 'actor': str(actor),
                 'started_at': now(), 'updated_at': now(), 'processed': 0, 'added': 0,
                 'changed': 0, 'unchanged': 0, 'batch_size': int(batch_size), 'errors': 0,
                 'base_sha256': sha(index), 'static_corpus_sha256': original,
                 'base_records_sha256': record_base, 'base_manifest_sha256': manifest_base,
                 'last_success_at': old.get('last_success_at')}
        if previous:
            value['previous_checkpoint'] = previous
        save(index, value)
        return value


def erase_record(conn, rid):
    ids = conn.execute("SELECT id FROM docs WHERE json_extract(metadata,'$.record_id')=? AND json_extract(metadata,'$.tipo_fonte')='registro_invenio'", (rid,)).fetchall()
    for (identifier,) in ids:
        position = conn.execute('SELECT position FROM sync_fts WHERE id=?', (identifier,)).fetchone()
        if not position:
            raise ValueError('Missing FTS document')
        conn.execute('DELETE FROM search WHERE rowid=?', position)
        conn.execute('DELETE FROM sync_fts WHERE id=?', (identifier,))
        conn.execute('DELETE FROM docs WHERE id=?', (identifier,))


def rebase_library(index, staging, value):
    """Merge current non-record evidence only when the public base is unchanged.

    Caller holds the common writer lock. Processed bibliographic rows, checkpoints
    and counters remain in staging; the active index is read-only throughout.
    """
    with database(index) as active:
        if (not value.get('base_records_sha256') or not value.get('base_manifest_sha256')
                or records_digest(active) != value['base_records_sha256']
                or manifest_digest(active) != value['base_manifest_sha256']):
            raise CheckpointConflict('Active index changed; restart required')
        with database(staging) as pending:
            scientific = "coalesce(json_extract(metadata,'$.tipo_fonte'),'')!='registro_invenio'"
            # Resolve actual FTS rowids, including sparse IDs from previous writers.
            pending.execute('DELETE FROM search WHERE rowid IN (SELECT position FROM sync_fts WHERE id IN (SELECT id FROM docs WHERE '+scientific+'))')
            pending.execute('DELETE FROM sync_fts WHERE id IN (SELECT id FROM docs WHERE '+scientific+')')
            pending.execute('DELETE FROM docs WHERE '+scientific)
            for identifier, title, text, metadata in active.execute('SELECT * FROM docs WHERE '+scientific+' ORDER BY id'):
                pending.execute('INSERT INTO docs VALUES(?,?,?,?)', (identifier, title, text, metadata))
                cursor = pending.execute('INSERT INTO search VALUES(?,?,?)', (identifier, title, text))
                pending.execute('INSERT INTO sync_fts VALUES(?,?)', (identifier, cursor.lastrowid))
            current_digest = static_digest(active)
            if static_digest(pending) != current_digest:
                raise ValueError('Scientific corpus changed')
            manifest = json.loads(pending.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
            latest = json.loads(active.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
            if 'library_updated_at' in latest:
                manifest['library_updated_at'] = latest['library_updated_at']
            # A prepared but unpublished checkpoint must validate/backup again.
            if manifest.get('synchronization', {}).get('run_id') == value['run_id']:
                manifest['synchronization'] = {'run_id': value['run_id'], 'state': 'preparing'}
            pending.execute("UPDATE manifest SET value=? WHERE key='corpus'", (json.dumps(manifest),))
            if pending.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('Staged index integrity')
    value.update(base_sha256=sha(index), static_corpus_sha256=current_digest,
                 library_rebases=value.get('library_rebases', 0)+1, last_library_rebase_at=now())
    save(index, value)


def step(index, provider):
    """provider(seen_connection, size) returns (projected rows, complete scan).

    Exhaustion must be positively established, never inferred from a timeout.
    """
    index = Path(index)
    try:
        with writer_lock(index):
            value = state(index)
            if value.get('state') not in ('running', 'paused', 'failed'):
                return value
            staging = index.with_suffix('.batch.sqlite3')
            if sha(index) != value['base_sha256']:
                # A worker may die after atomic publication but before writing
                # its sidecar. The published manifest is the commit receipt.
                with database(index) as active:
                    manifest=json.loads(active.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
                committed=manifest.get('synchronization',{})
                if committed.get('run_id')==value['run_id'] and committed.get('state')=='ok':
                    committed['version_sha256']=sha(index)
                    save(index,committed)
                    return committed
                rebase_library(index, staging, value)
            elif not value.get('base_records_sha256'):
                # Upgrade an unchanged legacy checkpoint without guessing its base.
                with database(index) as active:
                    value.update(base_records_sha256=records_digest(active), base_manifest_sha256=manifest_digest(active))
                save(index, value)
            with database(staging) as ready_db:
                ready_manifest=json.loads(ready_db.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
                ready=ready_manifest.get('synchronization',{})
                complete_checkpoint=(ready.get('run_id')==value['run_id'] and ready.get('state')=='ok')
                if complete_checkpoint and ready_db.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise ValueError('Staged index integrity')
            if complete_checkpoint:
                saved=ready['backup']
                if sha(index.parent/'versions'/saved['name'])!=saved['sha256']:
                    raise ValueError('Checkpoint backup integrity')
                os.chmod(staging,0o644)
                with open(staging,'rb') as stream:os.fsync(stream.fileno())
                os.replace(staging,index)
                ready['version_sha256']=sha(index)
                save(index,ready)
                return ready
            with database(staging) as conn:
                rows, complete = provider(conn, value['batch_size'])
                count = 0
                delta = {'added': 0, 'changed': 0, 'unchanged': 0}
                for row in rows:
                    rid = row.get('record_id')
                    if (not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', rid)
                            or row.get('access') != 'public' or row.get('source_type') != 'registro_invenio'
                            or not row.get('updated') or not isinstance(row.get('text'), str)
                            or len(row['text'].encode()) > 2_000_000
                            or hashlib.sha256(row['text'].encode()).hexdigest() != row.get('sha256')):
                        raise ValueError('Invalid public snapshot')
                    if conn.execute('SELECT 1 FROM sync_seen WHERE rid=?', (rid,)).fetchone():
                        raise ValueError('Duplicate checkpoint record')
                    old = conn.execute("SELECT json_extract(metadata,'$.updated'),json_extract(metadata,'$.sha256'),json_extract(metadata,'$.catalog_profile') FROM docs WHERE json_extract(metadata,'$.record_id')=? AND json_extract(metadata,'$.tipo_fonte')='registro_invenio' LIMIT 1", (rid,)).fetchone()
                    same = bool(old and old[:2] == (row['updated'], row['sha256'])
                                and (json.loads(old[2]) if old[2] else None) == row.get('catalog_profile'))
                    delta['unchanged' if same else 'changed' if old else 'added'] += 1
                    if not same:
                        erase_record(conn, rid)
                        for n, text in enumerate(chunks(row['text'])):
                            identifier = f'record:{rid}:c{n}'
                            meta = {'tipo_fonte': 'registro_invenio', 'record_id': rid,
                                    'updated': row['updated'], 'sha256': row['sha256'],
                                    'source_relative_path': 'records/' + rid + '.json',
                                    'access': 'public', 'snapshot': True, 'evidence_kind': 'bibliographic_metadata'}
                            if row.get('catalog_profile'):
                                meta['catalog_profile'] = row['catalog_profile']
                            conn.execute('INSERT INTO docs VALUES(?,?,?,?)', (identifier, row['title'], text, json.dumps(meta, ensure_ascii=False)))
                            cursor = conn.execute('INSERT INTO search VALUES(?,?,?)', (identifier, row['title'], text))
                            conn.execute('INSERT INTO sync_fts VALUES(?,?)', (identifier, cursor.lastrowid))
                    conn.execute('INSERT INTO sync_seen VALUES(?,?)', (rid, row['updated']))
                    count += 1
                    if count > value['batch_size']:
                        raise ValueError('Batch limit')
                if value.get('errors'):
                    value['last_failure']={'error_type':value.get('error_type'),'at':value.get('updated_at')}
                value.pop('error_type',None);value.pop('message',None);value.pop('error_code',None)
                value.update(processed=conn.execute('SELECT count(*) FROM sync_seen').fetchone()[0], state='running', updated_at=now(),errors=0)
                # Counters live in the transactional checkpoint, too, so a killed
                # worker between commit and status publication does not double count.
                conn.execute('CREATE TABLE IF NOT EXISTS sync_counts(name TEXT PRIMARY KEY,value INTEGER)')
                for key, number in delta.items():
                    conn.execute('INSERT INTO sync_counts VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value', (key, number))
                value.update(dict(conn.execute('SELECT name,value FROM sync_counts')))
                if complete:
                    removed = 0
                    while True:
                        absent = conn.execute("SELECT DISTINCT json_extract(metadata,'$.record_id') FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='registro_invenio' AND json_extract(metadata,'$.record_id') NOT IN (SELECT rid FROM sync_seen) LIMIT 100").fetchall()
                        if not absent:
                            break
                        for (rid,) in absent:
                            erase_record(conn, rid)
                            removed += 1
                    if static_digest(conn) != value['static_corpus_sha256']:
                        raise ValueError('Scientific corpus changed')
                    value.update(state='ok', removed=removed, public_records=value['processed'], last_success_at=now(), errors=0,
                                 attachment_policy='disabled; approved PDF corpus retained separately')
                    value['backup']=backup(index,'before-sync')
                    manifest = json.loads(conn.execute("SELECT value FROM manifest WHERE key='corpus'").fetchone()[0])
                    manifest.update(synchronization=value, counts=dict(conn.execute("SELECT json_extract(metadata,'$.tipo_fonte'),count(*) FROM docs GROUP BY 1")))
                    conn.execute("UPDATE manifest SET value=? WHERE key='corpus'", (json.dumps(manifest),))
                    # Retain checkpoint tables in this immutable generation.
                    # They make the last batch resumable even if publication
                    # fails. The next run drops them only in its staging copy.
                conn.commit()
                if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Index integrity')
            if complete:
                os.chmod(staging, 0o644)
                with open(staging, 'rb') as stream:
                    os.fsync(stream.fileno())
                os.replace(staging, index)
                value['version_sha256'] = sha(index)
            save(index, value)
            return value
    except BlockingIOError:
        return {'state': 'busy'}
    except Exception as exc:
        value = state(index)
        value.update(state='restart_required' if isinstance(exc, CheckpointConflict) else 'failed',
                     error_code='active_index_changed' if isinstance(exc, CheckpointConflict) else 'batch_failed',
                     errors=1, updated_at=now(), error_type=type(exc).__name__,
                     message='Previous valid index retained; resume or restart the checkpoint.')
        save(index, value)
        raise
