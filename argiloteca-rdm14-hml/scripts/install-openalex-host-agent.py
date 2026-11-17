#!/usr/bin/env python3
"""Install/reload the workspace-owned launchd job for the Mac OpenAlex queue."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys

app = Path(__file__).resolve().parents[1]
queue = app/'data/openalex-admin-queue'
queue.mkdir(parents=True, exist_ok=True, mode=0o700)
label = 'br.argiloteca.openalex-host'
plist = queue/(label+'.plist')
job = {'Label': label, 'ProgramArguments': [sys.executable,
    str(app/'scripts/openalex-host-agent.py'), '--source-root',
    str(app.parent/'povoamento/openalex'), '--queue', str(queue)],
    'WorkingDirectory': str(app), 'RunAtLoad': True, 'KeepAlive': True,
    'ThrottleInterval': 10, 'StandardOutPath': str(queue/'agent.stdout.log'),
    'StandardErrorPath': str(queue/'agent.stderr.log')}
plist.write_bytes(plistlib.dumps(job))
plist.chmod(0o600)
launch_agents = Path.home()/'Library/LaunchAgents'
launch_agents.mkdir(parents=True, exist_ok=True)
installed = launch_agents/(label+'.plist')
if installed.exists():
    previous = plistlib.loads(installed.read_bytes())
    if previous.get('Label') != label or str(app/'scripts/openalex-host-agent.py') not in previous.get('ProgramArguments', []):
        raise SystemExit('Já existe outro agente com esse nome; configuração preservada.')
installed.write_bytes(plist.read_bytes())
installed.chmod(0o600)
domain = 'gui/'+str(os.getuid())
subprocess.run(['launchctl', 'bootout', domain+'/'+label], capture_output=True)
subprocess.run(['launchctl', 'bootstrap', domain, str(installed)], check=True)
print('Agente OpenAlex ativado:', label)
print('Fila:', queue)
