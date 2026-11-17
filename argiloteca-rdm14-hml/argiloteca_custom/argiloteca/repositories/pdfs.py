"""Discover item-linked public PDFs and keep verified files in private staging."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse

from .client import atomic, sha, REPOSITORIES
from .network import AccessBlocked, check_access, fetch_bytes, open_public, safe_url, MAX_PDF

MAX_JOB_BYTES = 500 * 1024 * 1024
MAX_PER_RECORD = 5


class Links(HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag == 'a' and attrs.get('href'): self.links.append(attrs['href'])
        if tag == 'meta' and attrs.get('name','').lower() == 'citation_pdf_url' and attrs.get('content'): self.links.append(attrs['content'])


def linked_pdf(url, repository, handle, base):
    try: url=safe_url(urllib.parse.urljoin(base,url))
    except (ValueError, TypeError): return None
    p=urllib.parse.urlsplit(url)
    if p.hostname != REPOSITORIES[repository]['host']: return None
    path=urllib.parse.unquote(p.path)
    allowed=(f'/bitstream/{handle}/', f'/bitstream/handle/{handle}/')
    if not path.startswith(allowed) or not path.lower().endswith('.pdf'): return None
    # Do not treat PDF text extractions, thumbnails or another item's files as PDFs.
    return url


def discover(record):
    repository,handle=record['repository'],record['handle']
    expected='https://'+REPOSITORIES[repository]['host']+'/handle/'+handle
    if safe_url(record['url']) != expected: raise ValueError('Página do item diverge do Handle revisado.')
    rights=record.get('rights',[])
    terms=' '.join(rights).casefold()
    if any(t in terms for t in ['restrictedaccess','closedaccess','acesso restrito','acesso fechado','embargoedaccess']):
        raise AccessBlocked('A fonte declara acesso restrito ou embargo; download não realizado.')
    links=[]
    for value in record.get('identifiers',[]):
        link=linked_pdf(value,repository,handle,expected)
        if link and link not in links: links.append(link)
    body,headers=fetch_bytes(expected,limit=4*1024*1024)
    parser=Links();parser.feed(body.decode('utf-8',errors='replace'))
    for value in parser.links:
        link=linked_pdf(value,repository,handle,headers['url'])
        if link and link not in links: links.append(link)
    return links[:MAX_PER_RECORD], {'url':headers['url'],'sha256':hashlib.sha256(body).hexdigest(),
                                  'pdf_links_found':len(links),'pdf_links_limit':MAX_PER_RECORD}


def download(url, destination, budget):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True,mode=0o700)
    if destination.is_symlink(): raise ValueError('Armazenamento de PDFs por link simbólico recusado.')
    fd,temporary=tempfile.mkstemp(dir=destination,prefix='.download-')
    size=0;digest=hashlib.sha256();tail=b'';first=b''
    try:
        with os.fdopen(fd,'wb') as output, open_public(url) as response:
            content_type=response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
            length=response.headers.get('Content-Length','')
            if length.isdigit() and int(length)>min(MAX_PDF,budget): raise ValueError('PDF excede o limite por arquivo ou por tarefa.')
            while chunk:=response.read(64*1024):
                if not first:
                    first=chunk[:8192];check_access(first)
                    if not first.startswith(b'%PDF-'): raise ValueError('A URL não retornou um arquivo PDF (assinatura inválida).')
                    if content_type not in {'application/pdf','application/octet-stream','binary/octet-stream'}: raise ValueError('Tipo de conteúdo inesperado para PDF.')
                size+=len(chunk)
                if size>min(MAX_PDF,budget): raise ValueError('PDF excede o limite por arquivo ou por tarefa.')
                digest.update(chunk);output.write(chunk);tail=(tail+chunk)[-4096:]
            if not size or b'%%EOF' not in tail: raise ValueError('PDF vazio ou incompleto, sem marcador de fim.')
            if length.isdigit() and size!=int(length): raise ValueError('PDF incompleto: tamanho difere do Content-Length.')
            output.flush();os.fsync(output.fileno())
            final_url=safe_url(response.url)
        checksum=digest.hexdigest();path=destination/(checksum+'.pdf')
        if path.is_symlink(): raise ValueError('PDF preservado por link simbólico recusado.')
        if path.exists():
            if path.stat().st_size!=size or sha(path)!=checksum: raise ValueError('PDF preservado alterado; download não o sobrescreveu.')
        else: os.replace(temporary,path)
        return {'sha256':checksum,'bytes':size,'filename':checksum+'.pdf','source_url':url,'resolved_url':final_url,'content_type':content_type,
                'verification':'PDF signature, EOF, byte count and SHA256; not a full PDF parser validation'}
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def collect(root, job_id, records, progress=lambda *args:None):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id) or not 1<=len(records)<=20: raise ValueError('Tarefa PDF inválida.')
    root=Path(root);folder=root/'pdfs'/'jobs'/job_id;manifest=folder/'manifest.json';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    recipe=hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    result=json.loads(manifest.read_text()) if manifest.exists() else {'job_id':job_id,'records_sha256':recipe,'items':{},'complete':False,'bytes':0}
    if result['records_sha256']!=recipe: raise ValueError('A seleção PDF preservada diverge da revisão.')
    for item in result['items'].values():
        for file in item.get('files',[]):
            path=root/'pdfs'/'blobs'/file['filename']
            if path.is_symlink() or not path.is_file() or path.stat().st_size!=file['bytes'] or sha(path)!=file['sha256']: raise ValueError('PDF preservado alterado; tarefa não pode reutilizá-lo.')
    if result['complete']: return result
    for index,record in enumerate(records):
        key=record['key']
        if key in result['items']: continue
        item={'title':record['title'],'handle':record['handle'],'repository':record['repository'],'source_url':record['url'],
              'source_metadata_sha256':record['source_metadata_sha256'],'rights':record.get('rights',[]),'files':[],'issues':[]}
        try:
            links,page=discover(record);item['landing_page']=page
            if page['pdf_links_found']>MAX_PER_RECORD: item['issues'].append('Limite de cinco PDFs por item; confira os demais links na fonte.')
            for url in links:
                try:
                    saved=download(url,root/'pdfs'/'blobs',MAX_JOB_BYTES-result['bytes'])
                    result['bytes']+=saved['bytes']
                    previous=next((f for f in item['files'] if f['sha256']==saved['sha256']),None)
                    if previous:
                        previous.setdefault('source_aliases',[]).append(saved['source_url'])
                    else: item['files'].append(saved)
                except Exception as exc:
                    item['issues'].append(str(exc)[:500] if isinstance(exc,ValueError) else 'Falha no download do PDF; confira a disponibilidade na fonte.')
            item['state']='downloaded' if item['files'] and not item['issues'] else 'partial' if item['files'] else 'unavailable' if links else 'not_found'
        except AccessBlocked as exc: item.update(state='access_blocked',issues=[str(exc)])
        except Exception as exc: item.update(state='failed',issues=[str(exc)[:500] if isinstance(exc,ValueError) else 'Falha no acesso à página do item; tente outra tarefa PDF.'])
        result['items'][key]=item;atomic(manifest,result);progress(index+1,len(records),sum(len(v['files']) for v in result['items'].values()))
    result.update(complete=True,completed_at=datetime.now(timezone.utc).isoformat(),summary={state:sum(v['state']==state for v in result['items'].values()) for state in ['downloaded','partial','unavailable','not_found','access_blocked','failed']})
    atomic(manifest,result);return result
