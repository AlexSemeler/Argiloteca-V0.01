#!/usr/bin/env python3
"""Mac-only file-queue bridge. No HTTP listener and no arbitrary command input."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time


def atomic(path, value):
    fd, temp = tempfile.mkstemp(prefix='.host-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def heartbeat(queue, state='ready', job=None):
    atomic(queue/'heartbeat.json', {'state': state, 'job': job, 'updated': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid()})


def process(request, root, queue, adapter):
    jid = request.name.removesuffix('.request.json')
    if not re.fullmatch('[a-f0-9]{32}', jid):
        return
    result_path = queue/(jid+'.result.json')
    running_path = queue/(jid+'.running.json')
    if result_path.exists():
        return
    if running_path.exists():
        atomic(result_path, {'state': 'failed', 'message': 'A execução no Mac foi interrompida. Confira os lotes antes de iniciar outra coleta.'})
        return
    log_path = queue/(jid+'.host.log')
    try:
        data = adapter.read_json(request, queue, 8*1024*1024)
        if data.get('id') != jid or data.get('version') != 1:
            raise ValueError('Requisição de coleta inválida.')
        if data.get('operation') == 'maintenance_lot':
            atomic(running_path, {'started':datetime.now(timezone.utc).isoformat(),'operation':'maintenance_lot'})
            atomic(result_path, adapter.maintenance_files.apply_on_mac(root,queue,jid,data['params']))
            return
        params = adapter.extraction_parameters(data['params'], adapter.terms(root))
        install, fingerprint = adapter.release(root, 'extractor')
        credentials = adapter.read_json(install/'credenciais/openalex.json', install)
        secret = credentials.get('api_key', '')
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'OPENALEX_API_KEY', 'ARGILOTECA_OPENALEX_SEARCH')}
        env.update({'MAX_RECORDS': str(params['max_terms']), 'MINERAL_FILTER': '' if params['term'] == '__all__' else params['term'],
                    'RESULTS_PER_TERM': str(params['per_term']), 'START_OFFSET': str(params['offset']),
                    'PER_PAGE': '100', 'HTTP_TIMEOUT': '30'})
        command = ['/bin/bash', str(install/'executar_openalex.sh'), '--coletar']
        if params['free_text']:
            env['ARGILOTECA_OPENALEX_SEARCH'] = json.dumps(params, ensure_ascii=False)
            command = [str(install/'.venv/bin/python3'), '-B', str(Path(__file__).with_name('openalex-search-extractor.py')),
                       '--source-root', str(root)]
        atomic(running_path, {'started': datetime.now(timezone.utc).isoformat(), 'release': install.name, 'sha256': fingerprint})
        before = {p.name for p in (root/'lotes').glob('v59_*')}
        # V59 owns the credential redaction. Output stays in a private local file.
        with log_path.open('w') as output:
            log_path.chmod(0o600)
            child = subprocess.Popen(command,
                cwd=root, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic()+1200
            while child.poll() is None:
                heartbeat(queue, 'running', jid)
                if time.monotonic() > deadline:
                    os.killpg(child.pid, signal.SIGTERM)
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid, signal.SIGKILL)
                        child.wait()
                    raise ValueError('Coleta excedeu 20 minutos; lote parcial preservado.')
                time.sleep(2)
        output = log_path.read_text(errors='replace')
        if secret:
            output = output.replace(secret, '[CHAVE_OCULTA]')
        output = re.sub(r'(?i)(api_key[=\s:"\x27]+)[^&\s"\x27<>]+', r'\1[OCULTO]', output)
        output = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[OCULTO]', output)
        log_path.write_text(output)
        new_lots = [p for p in (root/'lotes').glob('v59_*') if p.name not in before]
        # The runner reports its exact folder. Do not associate an unrelated CLI run.
        names = re.findall(r'(?:Pasta do lote:|Lote novo:)\s*(.+)', output)
        target = Path(names[-1].strip()).name if names else ''
        completed = [p for p in new_lots if p.name == target and (p/'resultado.json').is_file()]
        success = child.returncode == 0 and len(completed) == 1
        empty = False
        if success:
            result = adapter.read_json(completed[0]/'resultado.json', completed[0])
            success = result.get('status') == 'coleta_concluida'
            empty = result.get('payloads') == 0
        atomic(result_path, {'state': 'completed' if success else 'failed',
            'lot': completed[0].name if success else None, 'returncode': child.returncode,
            'empty': empty, 'message': ('Busca concluída sem resultados. Ajuste o termo livre ou o vocabulário.' if empty else 'Coleta concluída.') if success else 'A coleta falhou. Consulte o log e os lotes preservados.',
            'log': output[-24000:], 'release': install.name, 'sha256': fingerprint})
    except Exception as exc:
        atomic(result_path, {'state': 'failed', 'message': str(exc) if isinstance(exc, ValueError) else 'Falha do agente local. Verifique sua configuração.'})
    finally:
        heartbeat(queue)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--queue', required=True, type=Path)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    root, queue = args.source_root.resolve(), args.queue.resolve()
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    module_path = Path(__file__).resolve().parents[1]/'argiloteca_custom/argiloteca/openalex/adapters.py'
    spec = importlib.util.spec_from_file_location('openalex_host_adapters', module_path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    file_spec=importlib.util.spec_from_file_location('openalex_host_maintenance',module_path.with_name('maintenance_files.py'))
    adapter.maintenance_files=importlib.util.module_from_spec(file_spec);file_spec.loader.exec_module(adapter.maintenance_files)
    with (queue/'host.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            heartbeat(queue)
            for request in sorted(queue.glob('*.request.json')):
                process(request, root, queue, adapter)
            if args.once:
                break
            time.sleep(3)


if __name__ == '__main__':
    main()
