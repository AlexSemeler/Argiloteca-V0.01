#!/usr/bin/env python3
"""Register the workspace-owned Repositórios OAI launchd job, only on this Mac."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

app = Path(__file__).resolve().parents[1]
queue = app / 'data/openalex-admin-queue/repositories'
queue.mkdir(parents=True, exist_ok=True, mode=0o700)
label = 'br.argiloteca.repositories-host'
plist = queue / (label + '.plist')
plist.write_bytes(plistlib.dumps({'Label': label,
    'ProgramArguments': [sys.executable, str(app / 'scripts/repositories-local-agent.py')],
    'WorkingDirectory': str(app), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
    'StandardOutPath': str(queue / 'agent.stdout.log'), 'StandardErrorPath': str(queue / 'agent.stderr.log')}))
plist.chmod(0o600)
domain = 'gui/' + str(os.getuid())
subprocess.run(['launchctl', 'bootout', domain + '/' + label], capture_output=True)
for attempt in range(10):
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], capture_output=True)
    if result.returncode == 0:
        break
    time.sleep(0.3)
else:
    raise SystemExit(result.stderr.decode(errors='replace'))
print('Agente Repositórios OAI ativado:', label)
print('Fila:', queue)
