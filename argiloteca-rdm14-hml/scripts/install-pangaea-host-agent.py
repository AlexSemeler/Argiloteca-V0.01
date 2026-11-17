#!/usr/bin/env python3
"""Register the workspace-owned PANGAEA launchd job, only on this Mac."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

app = Path(__file__).resolve().parents[1]
queue = app / 'data/openalex-admin-queue/pangaea'
queue.mkdir(parents=True, exist_ok=True, mode=0o700)
label = 'br.argiloteca.pangaea-host'
plist = queue / (label + '.plist')
plist.write_bytes(plistlib.dumps({'Label': label,
    'ProgramArguments': [sys.executable, str(app / 'scripts/pangaea-local-agent.py')],
    'WorkingDirectory': str(app), 'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
    'StandardOutPath': str(queue / 'agent.stdout.log'), 'StandardErrorPath': str(queue / 'agent.stderr.log')}))
plist.chmod(0o600)
domain = 'gui/' + str(os.getuid())
subprocess.run(['launchctl', 'bootout', domain + '/' + label], capture_output=True)
subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
print('Agente PANGAEA ativado:', label)
print('Fila:', queue)
