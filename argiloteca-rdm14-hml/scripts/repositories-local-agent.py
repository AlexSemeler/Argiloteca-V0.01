#!/usr/bin/env python3
"""Workspace-only OAI/PDF bridge; no listener or repository credentials."""
import argparse
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import threading
import time

APP=Path(__file__).resolve().parents[1]
package=APP/'argiloteca_custom/argiloteca/repositories'
spec=importlib.util.spec_from_file_location('repository_runtime',package/'__init__.py',submodule_search_locations=[str(package)])
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from repository_runtime import client, pdfs


def heartbeat(queue,**kwargs):
    client.atomic(queue/'heartbeat.json',{'state':'ready','updated':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),**kwargs})


def process(request,queue,vocabulary):
    jid=request.name.removesuffix('.request.json')
    if not re.fullmatch('[a-f0-9]{32}',jid) or request.is_symlink(): return
    result=queue/(jid+'.result.json')
    if result.exists(): return
    stopped=threading.Event();status={'state':'running','job':jid}
    def pulse():
        while not stopped.wait(3): heartbeat(queue,**status.copy())
    worker=threading.Thread(target=pulse,daemon=True);worker.start()
    try:
        if request.stat().st_size>1024*1024: raise ValueError('Requisição acima do limite.')
        data=json.loads(request.read_text())
        if data.get('id')!=jid or data.get('version')!=1: raise ValueError('Requisição inválida.')
        def progress(done,total,count):
            status.update(processed=done,total=total,records=count);heartbeat(queue,**status.copy())
        if data.get('operation')=='pdf':
            summary=pdfs.collect(queue,jid,data['records'],progress)
            client.atomic(result,{'state':'completed','pdfs':summary,'adapter':client.VERSION})
        elif data.get('operation')=='metadata':
            rows=client.vocabulary(vocabulary)
            if len(rows)!=81 or data.get('vocabulary_sha256')!=client.vocabulary_digest(rows): raise ValueError('O vocabulário difere dos 81 termos da administração.')
            params=client.parameters(data['params'],rows)
            lot='oai_'+data['params'].get('collection_id',jid)
            if not re.fullmatch(r'oai_[a-f0-9]{32}',lot): raise ValueError('Identificador de lote inválido.')
            folder=queue/'lotes'/lot
            if folder.is_symlink() or (queue/'lotes').is_symlink(): raise ValueError('Lote por link simbólico recusado.')
            summary=client.collect(folder,params,rows,progress)
            client.atomic(result,{'state':'completed','lot':lot,'empty':not summary['payloads'],'count':summary['payloads'],
                'coverage':summary['coverage'],'partial':summary['partial'],'adapter':client.VERSION})
        else: raise ValueError('Operação não reconhecida.')
    except Exception as exc:
        client.atomic(result,{'state':'failed','error_type':type(exc).__name__,'message':str(exc)[:1000] if isinstance(exc,ValueError) else 'Falha no acesso ao repositório. Confira disponibilidade e retome; respostas já obtidas foram preservadas.'})
    finally:
        stopped.set();worker.join();heartbeat(queue)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,default=APP/'data/openalex-admin-queue/repositories')
    p.add_argument('--vocabulary',type=Path,default=APP/'app_data/vocabularies/argilominerais.jsonl')
    p.add_argument('--once',action='store_true');args=p.parse_args();queue=args.queue.resolve();queue.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (queue/'host.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            heartbeat(queue)
            for request in sorted(queue.glob('*.request.json')): process(request,queue,args.vocabulary)
            if args.once:return
            time.sleep(3)


if __name__=='__main__': main()
