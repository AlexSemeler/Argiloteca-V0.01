"""Private lots, immutable review artifacts and native validation for Repositórios OAI."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import json
from itertools import islice
import os
from pathlib import Path
import re
import tempfile

from flask import current_app
from invenio_db import db

from ..openalex.adapters import confined, digest, read_json, release
from ..openalex.preview import connect, file_hash, raw_items
from ..openalex.service import review_context, review_snapshot
from .client import vocabulary, vocabulary_digest

CORRECTABLE = {'title', 'creators', 'publication_date', 'resource_type', 'description',
               'languages', 'rights', 'subjects', 'publisher', 'contributors',
               'additional_titles', 'additional_descriptions', 'dates',
               'sizes', 'formats', 'references', 'funding', 'locations'}


def root():
    return Path(current_app.config['ARGILOTECA_REPOSITORIES_ROOT'])


def terms(openalex_root=None):
    folder, _ = release(openalex_root or current_app.config['ARGILOTECA_OPENALEX_ROOT'], 'extractor')
    rows = vocabulary(folder / 'runtime/argiloteca/app_data/data/vocabularies/argilominerais.jsonl')
    if len(rows) != 81 or len({r['id'] for r in rows}) != 81:
        raise ValueError('O vocabulário de repositórios deve conter os mesmos 81 argilominerais do OpenAlex.')
    return rows


def lot_path(base, name):
    if not re.fullmatch(r'oai_[a-f0-9]{32}', str(name)):
        raise ValueError('Identificador de lote Repositórios OAI inválido.')
    return confined(Path(base) / 'lotes' / name, Path(base) / 'lotes')


def lots():
    result = []
    for folder in sorted((root() / 'lotes').glob('oai_*'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            marker = read_json(folder / 'resultado.json', root())
            result.append({'name': folder.name, 'complete': marker.get('status') == 'coleta_concluida', 'count': marker.get('payloads', 0)})
        except (ValueError, OSError):
            result.append({'name': folder.name, 'complete': False, 'count': 0})
    return result


def verify_snapshot(base, snapshot):
    folder = lot_path(base, Path(snapshot['source']).name)
    for name, expected in snapshot['input_hashes'].items():
        if file_hash(confined(folder / name, folder)) != expected:
            raise ValueError('Lote Repositórios OAI alterado; prepare uma nova revisão.')
    for row in snapshot.get('records', []):
        if digest(row['payload']) != row['payload_sha256']:
            raise ValueError('Payload alterado após a revisão.')


def extraction(job):
    from ..openalex.tasks import atomic_json
    queue = root()
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    result_path = queue / (job.id + '.result.json')
    if result_path.exists():
        job.result = read_json(result_path, queue)
        job.state = job.result['state']
        if job.state == 'failed':
            job.result = {**job.result, 'error': job.result.get('message', 'Falha na coleta Repositórios OAI.')}
        return
    request = queue / (job.id + '.request.json')
    if not request.exists():
        atomic_json(request, {'version': 1, 'id': job.id, 'params': job.params, 'operation': 'metadata',
                              'vocabulary_sha256': vocabulary_digest(terms())})
    heartbeat = queue / 'heartbeat.json'
    if not heartbeat.exists() or datetime.now(timezone.utc).timestamp() - heartbeat.stat().st_mtime > 60:
        raise ValueError('O agente local de repositórios está offline. Inicie scripts/repositories-local-agent.py.')
    job.state = 'waiting_host'
    job.result = {'host': read_json(heartbeat, queue)}


def build(job):
    folder = lot_path(root(), job.params['lot'])
    marker = read_json(folder / 'resultado.json', folder)
    if marker.get('status') != 'coleta_concluida':
        raise ValueError('O lote ainda não foi concluído.')
    hashes = {**marker['input_hashes'], 'resultado.json': file_hash(folder / 'resultado.json')}
    snapshot = {'format': 'repositories-v1', 'source': str(folder), 'input_hashes': hashes,
                'extraction_search': read_json(folder / 'busca.json', folder), 'coverage':marker['coverage'],
                'corrections': job.params.get('corrections', {}), 'summary': {}}
    verify_snapshot(root(), snapshot)
    output_folder = Path(current_app.config['ARGILOTECA_OPENALEX_QUEUE']) / 'previews'
    output_folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = confined(output_folder / (job.id + '.sqlite'), output_folder)
    if target.exists():
        with closing(connect(target, readonly=True)) as saved:
            metadata = json.loads(saved.execute('SELECT body FROM preview_metadata').fetchone()[0])
        if metadata['params_sha256'] != digest(job.params) or metadata['actor'] != job.actor:
            raise ValueError('Prévia preservada divergente.')
        snapshot = metadata['snapshot']
        verify_snapshot(root(), snapshot)
        descriptor = {'schema': 1, 'id': job.id, 'sha256': file_hash(target),
                      'bytes': target.stat().st_size, 'count': snapshot['summary']['selected_records']}
        if job.snapshot.get('record_store') and descriptor != job.snapshot['record_store']:
            raise ValueError('Prévia preservada alterada.')
        return {**snapshot, 'record_store': descriptor}
    corrections = job.params.get('corrections', {})
    if not isinstance(corrections, dict) or any(not isinstance(p, dict) or set(p) - CORRECTABLE for p in corrections.values()):
        raise ValueError('Correções devem conter somente campos descritivos permitidos.')
    records = (row for _, row in raw_items(folder / 'records.json'))
    total = min(marker['payloads'], job.params.get('limit') or marker['payloads'])
    selected = islice(records, total)
    context = review_context(current_app.config['ARGILOTECA_OPENALEX_ROOT'], job.actor)
    counts = dict.fromkeys(('apto', 'apto_com_alertas', 'bloqueado'), 0)
    fd, temporary = tempfile.mkstemp(dir=output_folder, prefix='.repositories-')
    os.close(fd)
    try:
        with closing(connect(temporary)) as output:
            output.execute('CREATE TABLE records (seq INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, status TEXT NOT NULL, body TEXT NOT NULL, sha256 TEXT NOT NULL, search TEXT NOT NULL)')
            output.execute('CREATE INDEX record_status ON records(status)')
            output.execute('CREATE TABLE preview_metadata (body TEXT NOT NULL)')
            for seq, source in enumerate(selected, 1):
                payload = deepcopy(source['payload'])
                payload['metadata'].update(deepcopy(corrections.get(source['key'], {})))
                issues = [deepcopy(i) for i in source['issues'] if i['path'].split('.')[-1] not in corrections.get(source['key'], {})]
                row = {'key': source['key'], 'identity': {'doi': source['doi'], 'handle': source['handle'], 'oai_identifier':source['oai_identifier'], 'openalex_id': ''},
                       'payload': payload, 'payload_sha256': digest(payload), 'issues': issues,
                       'status': 'bloqueado' if any(i['severity'] == 'error' for i in issues) else 'apto_com_alertas' if issues else 'apto',
                       'provenance': [{'origin': {'key': source['key'], 'termo_en': origin['term']['title'].get('en', '') if origin['term'] else '',
                                                  'termo_pt': origin['term']['title'].get('pt', '') if origin['term'] else '',
                                                  'query': origin['query'], 'source_url': source['url']},
                                       'search_result': origin['search_result'],
                                       'metadata_file': source['raw_file'], 'metadata_sha256': hashes[source['raw_file']],
                                       'source_metadata': read_json(folder / source['raw_file'], folder),
                                       'provider': 'OAI-PMH', 'repository': source['repository'],
                                       'handle': source['handle'], 'oai_identifier': source['oai_identifier'],
                                       'coverage': marker['coverage'],
                                       'mapping': 'Dublin Core bibliográfico; XML, direitos e campos não mapeados preservados nesta procedência.'}
                                      for origin in source['origins']]}
                review_snapshot(current_app.config['ARGILOTECA_OPENALEX_ROOT'], {'records': [row], 'summary': {}}, job.actor, context=context)
                counts[row['status']] += 1
                search = json.dumps({'metadata': payload['metadata'], 'identity': row['identity']}, ensure_ascii=False).casefold()
                output.execute('INSERT INTO records VALUES (?,?,?,?,?,?)', (seq, row['key'], row['status'], json.dumps(row, ensure_ascii=False), digest(row), search))
                if seq % 20 == 0:
                    job.result = {'progress': {'processed': seq, 'total': total}}
                    db.session.commit()
            if sum(counts.values()) != total:
                raise ValueError('O total do lote diverge dos registros preservados.')
            snapshot['summary'] = {**counts, 'unique_records': marker['payloads'], 'selected_records': total}
            verify_snapshot(root(), snapshot)
            output.execute('INSERT INTO preview_metadata VALUES (?)', (json.dumps({'snapshot': snapshot, 'params_sha256': digest(job.params), 'actor': job.actor}, ensure_ascii=False),))
            output.commit()
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    snapshot['record_store'] = {'schema': 1, 'id': job.id, 'sha256': file_hash(target), 'bytes': target.stat().st_size, 'count': total}
    return snapshot


def run(job):
    if job.kind == 'oai_extract':
        extraction(job)
    elif job.kind == 'oai_pdf':
        pdf_extraction(job)
    elif job.kind == 'oai_prepare':
        from ..openalex.service import job_lock
        with job_lock('openalex-preview-preparation') as locked:
            if not locked:
                job.state = 'queued'
                db.session.commit()
                return
            job.snapshot = build(job)
            job.state = 'review'
    elif job.kind == 'oai_import':
        from ..openalex.service import import_job
        import_job(job, current_app.config['ARGILOTECA_OPENALEX_ROOT'], verify=lambda _, snapshot: verify_snapshot(root(), snapshot))
        return
    elif job.kind == 'oai_publish_scan':
        from ..openalex.publication import prepare
        from ..openalex.service import job_lock
        with job_lock('openalex-publication-preview') as locked:
            if not locked:
                job.state = 'queued'
                db.session.commit()
                return
            prepare(job)
    elif job.kind == 'oai_publish':
        from ..openalex.publication import run_chunk
        from ..openalex.tasks import run as dispatch
        if run_chunk(job):
            dispatch.apply_async(args=[job.id], countdown=2)
        return
    else:
        raise ValueError('Tipo de tarefa Repositórios OAI inválido.')
    db.session.commit()


def pdf_extraction(job):
    from ..openalex.tasks import atomic_json
    queue = root(); queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    result_path = queue / (job.id + '.result.json')
    if result_path.exists():
        job.result = read_json(result_path, queue); job.state = job.result['state']
        if job.state == 'failed': job.result = {**job.result,'error':job.result.get('message','Falha na tarefa PDF.')}
        return
    verify_snapshot(queue, job.snapshot)
    folder = lot_path(queue, Path(job.snapshot['source']).name)
    records=[]
    for row in job.snapshot['records']:
        origin=row['provenance'][0]
        raw=read_json(folder/origin['metadata_file'],folder)
        records.append({'key':row['key'],'title':row['payload']['metadata']['title'],
                        'repository':origin['repository'],'handle':origin['handle'],
                        'url':origin['origin']['source_url'],'rights':raw['dc'].get('rights',[]),
                        'identifiers':raw['dc'].get('identifier',[]),
                        'source_metadata_sha256':origin['metadata_sha256']})
    request=queue/(job.id+'.request.json')
    if not request.exists(): atomic_json(request,{'version':1,'id':job.id,'operation':'pdf','records':records})
    heartbeat=queue/'heartbeat.json'
    if not heartbeat.exists() or datetime.now(timezone.utc).timestamp()-heartbeat.stat().st_mtime>60:
        raise ValueError('O agente local de repositórios está offline. Inicie scripts/repositories-local-agent.py.')
    job.state='waiting_host';job.result={'host':read_json(heartbeat,queue)}
