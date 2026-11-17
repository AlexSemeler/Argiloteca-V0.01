"""Bounded HTTPS reads of two public repositories, checking every redirect."""
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HOSTS = {'lume.ufrgs.br', 'www.lume.ufrgs.br', 'repositorio.ufsc.br'}
MAX_XML = 16 * 1024 * 1024
MAX_PDF = 100 * 1024 * 1024


class AccessBlocked(ValueError):
    pass


def safe_url(url):
    p = urllib.parse.urlsplit(str(url))
    if p.scheme not in {'https', 'http'} or p.hostname not in HOSTS or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('URL fora dos repositórios públicos permitidos.')
    if any(ord(c) < 32 for c in str(url)) or '\\' in str(url):
        raise ValueError('URL inválida.')
    decoded=urllib.parse.unquote(p.path)
    if '\\' in decoded or any(v in {'.','..'} for v in decoded.split('/')):
        raise ValueError('Travessia de caminho na URL recusada.')
    host = 'lume.ufrgs.br' if p.hostname == 'www.lume.ufrgs.br' else p.hostname
    return urllib.parse.urlunsplit(('https', host, p.path or '/', p.query, ''))


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked = safe_url(urllib.parse.urljoin(req.full_url, newurl))
        old, new = urllib.parse.urlsplit(req.full_url), urllib.parse.urlsplit(checked)
        if old.hostname != new.hostname:
            raise ValueError('Redirecionamento para outro repositório recusado.')
        if '/login' in new.path or '/authenticate' in new.path:
            raise AccessBlocked('Arquivo exige autenticação no repositório; acesso não contornado.')
        return super().redirect_request(req, fp, code, msg, headers, checked)


def check_access(body):
    prefix = body[:8192].lower()
    if any(v in prefix for v in [b'cf-turnstile', b'challenges.cloudflare.com', b'captcha', b'sistema de preven', b'verify you are human']):
        raise AccessBlocked('O repositório exige verificação de acesso. Na UFSC, use acesso institucional/VPN autorizado e retome a tarefa. O módulo não contorna essa verificação.')


def open_public(url):
    url = safe_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'Argiloteca-OAI/1.0', 'Accept': 'application/xml,text/html,application/pdf;q=0.9,*/*;q=0.1', 'Accept-Encoding': 'identity'})
    opener = urllib.request.build_opener(Redirects())
    for attempt in range(3):
        try:
            return opener.open(request, timeout=30)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403, 451}:
                raise AccessBlocked(f'Acesso recusado pelo repositório (HTTP {exc.code}). Confira acesso/embargo na fonte e retome após liberação.') from None
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                raise
            retry = str(exc.headers.get('Retry-After', ''))
            time.sleep(min(30, int(retry)) if retry.isdigit() else 2 ** (attempt + 1))


def fetch_bytes(url, limit=MAX_XML):
    with open_public(url) as response:
        length = response.headers.get('Content-Length', '')
        if length.isdigit() and int(length) > limit:
            raise ValueError('Resposta remota acima do limite permitido.')
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError('Resposta remota acima do limite permitido.')
        check_access(body)
        return body, {'url': safe_url(response.url), 'content_type': response.headers.get('Content-Type', ''),
                      'last_modified': response.headers.get('Last-Modified', ''), 'etag': response.headers.get('ETag', '')}


def atomic_bytes(path, body):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
