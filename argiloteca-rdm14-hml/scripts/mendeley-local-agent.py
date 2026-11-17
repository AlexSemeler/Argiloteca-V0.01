#!/usr/bin/env python3
"""Local Mendeley Data bridge: no listener, shell commands or credentials."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import time

APP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mendeley_client', APP / 'argiloteca_custom/argiloteca/mendeley/client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def heartbeat(queue, **kwargs):
    client.atomic(queue / 'heartbeat.json', {'state': 'ready', 'updated': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(), **kwargs})


def process(request, queue, vocabulary):
    jid = request.name.removesuffix('.request.json')
    if not re.fullmatch('[a-f0-9]{32}', jid) or request.is_symlink():
        return
    result = queue / (jid + '.result.json')
    if result.exists():
        return
    try:
        if request.stat().st_size > 32768:
            raise ValueError('Requisição acima do limite.')
        data = json.loads(request.read_text())
        if data.get('id') != jid or data.get('version') != 1:
            raise ValueError('Requisição Mendeley Data inválida.')
        rows = client.vocabulary(vocabulary)
        if len(rows) != 81:
            raise ValueError('O vocabulário deve conter 81 argilominerais.')
        if data.get('vocabulary_sha256') and data['vocabulary_sha256'] != client.vocabulary_digest(rows):
            raise ValueError('O vocabulário do agente difere dos 81 termos revisados na administração.')
        params = client.parameters(data['params'], rows)
        lot = 'men_' + data['params'].get('collection_id', jid)
        if not re.fullmatch(r'men_[a-f0-9]{32}', lot):
            raise ValueError('Identificador de retomada inválido.')
        folder = queue / 'lotes' / lot
        if folder.is_symlink() or (queue / 'lotes').is_symlink():
            raise ValueError('Lote por link simbólico não é permitido.')
        # A heartbeat remains fresh even during a single slow HTTP request.
        import threading
        stopped = threading.Event()
        def pulse():
            while not stopped.wait(3):
                heartbeat(queue, state='running', job=jid)
        worker = threading.Thread(target=pulse, daemon=True)
        worker.start()
        try:
            summary = client.collect(folder, params, rows,
                progress=lambda done, total, count: heartbeat(queue, state='running', job=jid, processed=done, total=total, records=count))
        finally:
            stopped.set()
            worker.join()
        client.atomic(result, {'state': 'completed', 'lot': lot, 'empty': not summary['payloads'],
                              'count': summary['payloads'], 'adapter': client.VERSION})
    except Exception as exc:
        client.atomic(result, {'state': 'failed', 'error_type': type(exc).__name__,
                              'message': str(exc)[:500] if isinstance(exc, ValueError) else 'Falha no acesso ao Mendeley Data. Retome a coleta; respostas já obtidas foram preservadas.'})
    finally:
        heartbeat(queue)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue', type=Path, default=APP / 'data/openalex-admin-queue/mendeley')
    parser.add_argument('--vocabulary', type=Path, default=APP / 'app_data/vocabularies/argilominerais.jsonl')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    queue = args.queue.resolve()
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (queue / 'host.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            heartbeat(queue)
            for request in sorted(queue.glob('*.request.json')):
                process(request, queue, args.vocabulary)
            if args.once:
                return
            time.sleep(3)


if __name__ == '__main__':
    main()
