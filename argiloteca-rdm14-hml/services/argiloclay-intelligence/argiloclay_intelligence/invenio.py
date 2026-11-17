"""Public REST API only. No SQL, privileged token, file download or URL following."""
from __future__ import annotations

import hashlib
import json
import re
import ssl
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPSHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Redirecionamento da API não autorizado.")


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = Plain(); parser.feed(str(value)); return " ".join(parser.parts)


class Invenio:
    def __init__(self, base_url, *, local_self_signed=False, opener=None):
        parts = urlsplit(base_url)
        if parts.scheme != "https" or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Use uma URL HTTPS fixa, sem credenciais, query ou fragmento.")
        if local_self_signed and parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Exceção de certificado permitida apenas no loopback local.")
        self.base = base_url.rstrip("/")
        context = ssl._create_unverified_context() if local_self_signed else ssl.create_default_context()
        self.opener = opener or build_opener(NoRedirect(), HTTPSHandler(context=context)).open

    def get(self, suffix="", **params):
        url = self.base + "/api/records" + suffix
        if params:
            url += "?" + urlencode(params)
        req = Request(url, headers={"Accept": "application/json"}, method="GET")
        with self.opener(req, timeout=10) as response:
            raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError("Página da API acima do limite.")
        return json.loads(raw)

    def record(self, record_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", record_id):
            raise ValueError("ID de registro inválido.")
        row = self.get("/" + record_id)
        if row.get("access", {}).get("record") != "public":
            raise ValueError("Apenas metadados publicados e públicos.")
        return project(row, self.base)

    def records(self, maximum=5000):
        seen = set()
        for page in range(1, (maximum + 99) // 100 + 1):
            data = self.get(page=page, size=100, sort="newest")
            rows = data.get("hits", {}).get("hits", [])
            if not rows:
                return
            for row in rows:
                rid = row.get("id")
                if not rid or rid in seen:
                    raise ValueError("ID ausente/duplicado durante paginação; refaça snapshot estável.")
                seen.add(rid)
                if row.get("access", {}).get("record") == "public":
                    yield project(row, self.base)
                if len(seen) >= maximum:
                    if len(rows) == 100:
                        raise ValueError("Limite de registros alcançado; aumente maximum explicitamente.")
                    return
            if len(rows) < 100:
                return



from .public_metadata import project
