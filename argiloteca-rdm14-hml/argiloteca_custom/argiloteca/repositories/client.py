"""OAI-PMH catalogues for LUME/UFSC, local boolean search and audited lots."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unicodedata
import urllib.parse
from xml.etree import ElementTree as ET

from .network import fetch_bytes, check_access, atomic_bytes

VERSION = 'argiloteca-repositories/1.0'
OAI = 'http://www.openarchives.org/OAI/2.0/'
DC = 'http://purl.org/dc/elements/1.1/'
REPOSITORIES = {
    'lume': {'name': 'LUME UFRGS', 'base': 'https://lume.ufrgs.br/oai/request',
             'host': 'lume.ufrgs.br', 'prefix': '10183', 'set': 'com_10183_2',
             'oai_hosts': ['www.lume.ufrgs.br', 'lume.ufrgs.br']},
    'ufsc': {'name': 'Repositório UFSC', 'base': 'https://repositorio.ufsc.br/oai/request',
             'host': 'repositorio.ufsc.br', 'prefix': '123456789', 'set': '',
             'oai_hosts': ['repositorio.ufsc.br']}}

def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def vocabulary(path):
    return [r for line in Path(path).read_text().splitlines() if line.strip()
            if (r := json.loads(line)).get('props', {}).get('status') in (None, '', 'preferred')]


def vocabulary_digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def search_parameters(data, rows):
    term, raw_free = str(data.get('term', '')).strip(), str(data.get('free_text', ''))
    free = raw_free.strip()
    if len(raw_free) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in raw_free):
        raise ValueError('A busca livre deve ter até 500 caracteres, sem controles.')
    if term not in {'', '__all__', *(r['id'] for r in rows)} or not (term or free):
        raise ValueError('Informe uma busca livre ou selecione um argilomineral válido.')
    result = {'term': term, 'free_text': free,
              'search_mode': 'combined' if term and free else 'free' if free else 'vocabulary'}
    for key, default, low, high in [('per_term', 1, 1, 100), ('max_terms', 1, 1, 81), ('offset', 0, 0, 80)]:
        try:
            value = int(data.get(key, default))
        except (TypeError, ValueError):
            raise ValueError('Limite numérico inválido: ' + key) from None
        if not low <= value <= high:
            raise ValueError('Limite fora da faixa: ' + key)
        result[key] = value
    if term and term != '__all__' and result['offset']:
        raise ValueError('Para um mineral específico use deslocamento 0.')
    return result


def search_queries(params, rows):
    if not params['term']:
        return [{'query': params['free_text'], 'term': None}]
    selected = sorted(rows, key=lambda r: r.get('title', {}).get('pt', r['id']).casefold())
    if params['term'] == '__all__':
        selected = selected[params['offset']:params['offset'] + params['max_terms']]
    else:
        selected = [r for r in selected if r['id'] == params['term']]
    if not selected:
        raise ValueError('Nenhum termo selecionado. Reduza o deslocamento.')
    queries = []
    for row in selected:
        names = list(dict.fromkeys(row.get('title', {}).get(k, row['id']) for k in ('en', 'pt')))
        mineral = ' OR '.join(json.dumps(n, ensure_ascii=False) for n in names)
        query = f'({mineral})'
        if params['free_text']:
            query = f'({params["free_text"]}) AND {query}'
        queries.append({'query': query, 'term': row})
    return queries


def fold(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value)).casefold() if not unicodedata.combining(c))


def expression(query):
    """Parse a bounded boolean grammar. Never evaluate user input as Python."""
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|\(|\)|[^\s()"]+', query)
    if len(tokens) > 128 or len(query) > 1200 or query.count('"') % 2:
        raise ValueError('Expressão inválida ou muito longa. Use palavras, aspas, AND, OR, NOT e parênteses.')
    position = 0

    def atom(depth):
        nonlocal position
        if depth > 20 or position >= len(tokens): raise ValueError('Expressão incompleta ou aninhada demais.')
        token = tokens[position]; position += 1
        if token == 'NOT': return ('not', atom(depth + 1))
        if token == '(':
            node = disjunction(depth + 1)
            if position >= len(tokens) or tokens[position] != ')': raise ValueError('Parênteses incompletos na expressão.')
            position += 1; return node
        if token in {'AND', 'OR', ')'}: raise ValueError('Operador sem termo na expressão.')
        value = json.loads(token) if token.startswith('"') else token
        if not value.strip() or value == '*' or '*' in value[:-1]: raise ValueError('Termo inválido; use * somente ao final de uma palavra.')
        return ('term', fold(value))

    def conjunction(depth):
        nonlocal position
        node = atom(depth)
        while position < len(tokens) and tokens[position] not in {')', 'OR'}:
            if tokens[position] == 'AND': position += 1
            node = ('and', node, atom(depth))
        return node

    def disjunction(depth):
        nonlocal position
        node = conjunction(depth)
        while position < len(tokens) and tokens[position] == 'OR':
            position += 1; node = ('or', node, conjunction(depth))
        return node
    if not tokens: raise ValueError('Informe termos para a busca.')
    node = disjunction(0)
    if position != len(tokens): raise ValueError('Expressão inválida.')
    return node


def evaluate(node, text):
    if node[0] == 'and': return evaluate(node[1], text) and evaluate(node[2], text)
    if node[0] == 'or': return evaluate(node[1], text) or evaluate(node[2], text)
    if node[0] == 'not': return not evaluate(node[1], text)
    term = node[1]; prefix = term.endswith('*'); term = term.rstrip('*')
    return bool(re.search(r'(?<!\w)' + re.escape(term).replace(r'\ ', r'\s+') + (r'\w*' if prefix else r'(?!\w)'), text))


def parameters(data, rows):
    result = search_parameters(data, rows)
    repository = str(data.get('repository', 'lume'))
    if repository not in REPOSITORIES: raise ValueError('Selecione LUME UFRGS ou UFSC.')
    result['repository'] = repository
    set_spec = str(data.get('set_spec', REPOSITORIES[repository]['set'])).strip()
    if set_spec == '__all__': set_spec = ''
    if len(set_spec) > 128 or set_spec and not re.fullmatch(r'[A-Za-z0-9_:.-]+', set_spec): raise ValueError('Conjunto OAI inválido.')
    result['set_spec'] = set_spec
    for field in ('from_date', 'until_date'):
        value = str(data.get(field, '')).strip()
        if value:
            try: datetime.strptime(value, '%Y-%m-%d')
            except ValueError: raise ValueError('Use datas OAI no formato AAAA-MM-DD.') from None
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value): raise ValueError('Data OAI inválida.')
        result[field] = value
    if result['from_date'] and result['until_date'] and result['from_date'] > result['until_date']: raise ValueError('Data inicial maior que a final.')
    try: pages = int(data.get('max_pages', 10))
    except (ValueError, TypeError): raise ValueError('Quantidade de páginas inválida.') from None
    if not 0 <= pages <= 100: raise ValueError('Use de 0 a 100 páginas novas; zero pesquisa apenas o catálogo já coletado.')
    result['max_pages'] = pages
    try: cycle = int(data.get('catalog_cycle', 1))
    except (ValueError,TypeError): raise ValueError('Ciclo do catálogo inválido.') from None
    if not 1 <= cycle <= 99999: raise ValueError('Ciclo do catálogo fora da faixa.')
    result['catalog_cycle'] = cycle
    for query in search_queries(result, rows): expression(query['query'])
    return result


def record_identity(raw, repository):
    config = REPOSITORIES[repository]
    identifier = raw.get('identifier', '')
    hosts = '|'.join(re.escape(v) for v in config['oai_hosts'])
    match = re.fullmatch(r'oai:(?:' + hosts + '):(' + config['prefix'] + r'/\d+)', identifier)
    if not match: raise ValueError('Identificador OAI fora da identidade esperada do repositório.')
    handle = match[1]
    declared = []
    for value in raw.get('dc', {}).get('identifier', []):
        url = urllib.parse.urlsplit(value)
        if url.hostname in {'hdl.handle.net', config['host'], 'www.' + config['host']}:
            path = url.path.removeprefix('/xmlui').removeprefix('/handle').strip('/')
            if re.fullmatch(config['prefix'] + r'/\d+', path): declared.append(path)
    if not raw.get('deleted') and (not declared or set(declared) != {handle}):
        raise ValueError('Handle dos metadados ausente ou divergente do identificador OAI.')
    return {'handle': handle, 'identifier': identifier, 'url': 'https://' + config['host'] + '/handle/' + handle}


def parse_page(body, repository):
    check_access(body)
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper(): raise ValueError('DTD e entidades XML não são aceitos.')
    try: root = ET.fromstring(body)
    except ET.ParseError: raise ValueError('Resposta não é XML OAI-PMH válido; confira disponibilidade e acesso ao repositório.') from None
    if root.tag != '{' + OAI + '}OAI-PMH': raise ValueError('Resposta não é OAI-PMH; nenhum resultado vazio foi presumido.')
    errors = root.findall('{' + OAI + '}error')
    if errors:
        if len(errors) == 1 and errors[0].get('code') == 'noRecordsMatch': return [], None
        code = errors[0].get('code', 'unknown')
        if code == 'badResumptionToken': raise ValueError('Token OAI expirou. Inicie um novo ciclo de catálogo; páginas preservadas não foram apagadas.')
        raise ValueError('Erro OAI-PMH ' + code + ': ' + (errors[0].text or '')[:300])
    listing = root.find('{' + OAI + '}ListRecords')
    if listing is None: raise ValueError('Resposta sem ListRecords.')
    records = []
    for record in listing.findall('{' + OAI + '}record'):
        header = record.find('{' + OAI + '}header')
        if header is None: raise ValueError('Registro sem cabeçalho OAI.')
        raw = {'identifier': header.findtext('{' + OAI + '}identifier', ''), 'datestamp': header.findtext('{' + OAI + '}datestamp', ''),
               'sets': [v.text or '' for v in header.findall('{' + OAI + '}setSpec')],
               'deleted': header.get('status') == 'deleted', 'dc': {}, 'xml': ET.tostring(record, encoding='unicode')}
        metadata = record.find('{' + OAI + '}metadata')
        if not raw['deleted']:
            dc = metadata.find('{http://www.openarchives.org/OAI/2.0/oai_dc/}dc') if metadata is not None else None
            if dc is None: raise ValueError('Registro ativo sem Dublin Core oai_dc.')
            for child in dc:
                if child.tag.startswith('{' + DC + '}'):
                    value = ''.join(child.itertext()).strip()
                    if value: raw['dc'].setdefault(child.tag.split('}', 1)[1], []).append(value)
        record_identity(raw, repository)
        records.append(raw)
    token = listing.find('{' + OAI + '}resumptionToken')
    continuation = (token.text or '').strip() if token is not None else ''
    if len(continuation) > 8192: raise ValueError('Token OAI acima do limite.')
    if not records: raise ValueError('Página OAI vazia sem noRecordsMatch; resposta não aceita como coleta completa.')
    return records, continuation or None


def scope_parameters(params):
    return {k: params[k] for k in ('repository', 'set_spec', 'from_date', 'until_date', 'catalog_cycle')}


def catalog_path(base, params):
    fingerprint = hashlib.sha256(json.dumps(scope_parameters(params), sort_keys=True).encode()).hexdigest()
    return Path(base) / 'catalogues' / fingerprint


def harvest(base, params, progress=lambda *args: None):
    """Increment a persistent catalogue with transactional token/checkpoint state."""
    import urllib.parse
    folder = catalog_path(base, params); folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.is_symlink(): raise ValueError('Catálogo por link simbólico não é permitido.')
    with closing(sqlite3.connect(folder / 'catalog.sqlite')) as db:
        db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, body TEXT NOT NULL, deleted INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY)')
        stored = db.execute('SELECT body FROM state WHERE id=1').fetchone()
        state = json.loads(stored[0]) if stored else {'scope': scope_parameters(params), 'pages': 0, 'seen': 0, 'deleted': 0, 'cursor': None, 'complete': False}
        if state['scope'] != scope_parameters(params): raise ValueError('Escopo de catálogo divergente.')
        for step in range(params['max_pages']):
            if state['complete']: break
            if state['cursor']:
                query = {'verb': 'ListRecords', 'resumptionToken': state['cursor']}
            else:
                query = {'verb': 'ListRecords', 'metadataPrefix': 'oai_dc'}
                for source, target in [('set_spec', 'set'), ('from_date', 'from'), ('until_date', 'until')]:
                    if params[source]: query[target] = params[source]
            url = REPOSITORIES[params['repository']]['base'] + '?' + urllib.parse.urlencode(query)
            page = folder / ('page_%06d.xml' % state['pages']); receipt = page.with_suffix('.json')
            if page.is_symlink() or receipt.is_symlink(): raise ValueError('Página de catálogo por link simbólico não é permitida.')
            if receipt.exists():
                proof = json.loads(receipt.read_text())
                if proof['request_url'] != url or not page.is_file() or proof['sha256'] != sha(page): raise ValueError('Página OAI preservada alterada.')
            else:
                body, headers = fetch_bytes(url)
                # Validate before making a response reusable as a metadata page.
                parse_page(body, params['repository'])
                atomic_bytes(page, body); atomic(receipt, {'request_url': url, 'sha256': sha(page), 'headers': headers})
            records, cursor = parse_page(page.read_bytes(), params['repository'])
            if cursor and (cursor == state['cursor'] or db.execute('SELECT 1 FROM tokens WHERE token=?', (cursor,)).fetchone()): raise ValueError('O repositório repetiu um token OAI; coleta interrompida para evitar repetição infinita.')
            if params['set_spec'] and any(not raw['deleted'] and params['set_spec'] not in raw['sets'] for raw in records):
                raise ValueError('O repositório retornou registro fora do conjunto OAI solicitado.')
            page_checksum = sha(page)
            for raw in records:
                raw['source_page'] = {'file': str(page), 'sha256': page_checksum, 'request_url': url}
                db.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)', (raw['identifier'], json.dumps(raw, ensure_ascii=False), int(raw['deleted'])))
            if cursor: db.execute('INSERT INTO tokens VALUES (?)', (cursor,))
            state.update(pages=state['pages']+1, seen=state['seen']+len(records), deleted=state['deleted']+sum(r['deleted'] for r in records), cursor=cursor, complete=not cursor)
            db.execute('INSERT OR REPLACE INTO state VALUES (1,?)', (json.dumps(state),)); db.commit()
            state['available_records'] = db.execute('SELECT count(*) FROM records WHERE deleted=0').fetchone()[0]
            atomic(folder / 'status.json',state)
            progress(step+1, params['max_pages'], state['available_records'])
        state['available_records'] = db.execute('SELECT count(*) FROM records WHERE deleted=0').fetchone()[0]
    atomic(folder / 'status.json', state)
    return folder, state


def source_date(values):
    candidates = []
    for value in values:
        # Unqualified DC dates can contain deposit/accession timestamps. Never
        # substitute a timestamp or OAI header datestamp for publication.
        if not re.fullmatch(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', value): continue
        try: datetime.strptime(value, {4:'%Y',7:'%Y-%m',10:'%Y-%m-%d'}[len(value)])
        except ValueError: continue
        candidates.append(value)
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else ''


def build_payload(raw, repository):
    identity = record_identity(raw, repository)
    if raw['deleted']: raise ValueError('Registro excluído na fonte não pode ser importado.')
    dc = raw['dc']; creators = []
    for name in dc.get('creator', []):
        person = {'type': 'personal', 'name': name}
        if ',' in name:
            family, given = name.split(',', 1)
            if family.strip(): person['family_name'] = family.strip()
            if given.strip(): person['given_name'] = given.strip()
        creators.append({'person_or_org': person})
    kinds = fold(' '.join(dc.get('type', [])))
    resource = 'publication-dissertation' if any(v in kinds for v in ['tese', 'dissertacao', 'thesis']) else 'publication-article' if 'article' in kinds or 'artigo' in kinds else 'publication-other'
    md = {'title': next(iter(dc.get('title', [])), ''), 'creators': creators, 'publication_date': source_date(dc.get('date', [])),
          'resource_type': {'id': resource}, 'identifiers': [{'scheme':'handle','identifier':identity['handle']},{'scheme':'url','identifier':identity['url']}]}
    dois=[]
    for value in dc.get('identifier',[]):
        candidate=re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:)', '', value.strip(), flags=re.I)
        if re.fullmatch(r'10\.\d{4,9}/[^\s]+',candidate,re.I) and candidate.lower() not in dois: dois.append(candidate.lower())
    if len(dois)==1: md['identifiers'].append({'scheme':'doi','identifier':dois[0]})
    if dc.get('publisher'): md['publisher'] = dc['publisher'][0]
    if dc.get('description'): md['description'] = ''.join('<p>'+html.escape(v).replace('\n','<br>')+'</p>' for v in dc['description'])
    if dc.get('subject'): md['subjects'] = [{'subject':v} for v in dict.fromkeys(dc['subject'])]
    languages = {'por':'por','pt':'por','pt_BR':'por','pt-BR':'por','eng':'eng','en':'eng','spa':'spa','es':'spa','fra':'fra','fr':'fra'}
    known = list(dict.fromkeys(languages[v] for v in dc.get('language', []) if v in languages))
    if known: md['languages'] = [{'id':v} for v in known]
    # Access declarations are not reuse licenses. Preserve them in provenance.
    licenses = [v for v in dc.get('rights', []) if re.match(r'https?://(?:creativecommons.org|www.creativecommons.org)/', v)]
    if licenses: md['rights'] = [{'title':{'en':v},'link':v} for v in licenses]
    issues = [{'severity':'error','code':'missing_source','path':'metadata.'+v,'message':'Campo obrigatório ausente ou ambíguo na fonte; confira antes de corrigir.'} for v in ('title','creators','publication_date') if not md[v]]
    if len(dois)>1: issues.append({'severity':'error','code':'ambiguous_doi','path':'identity','message':'Mais de um DOI declarado como identificador na fonte; confira a identidade antes de importar.'})
    if not licenses: issues.append({'severity':'warning','code':'license_missing','path':'metadata.rights','message':'Acesso aberto não define licença de reutilização. Direitos da fonte preservados na procedência.'})
    if len(dc.get('title', [])) > 1:
        issues.append({'severity':'warning','code':'additional_titles_preserved','path':'metadata.additional_titles','message':'Títulos adicionais sem qualificador de idioma/tipo preservados na procedência.'})
    return {'metadata':md,'files':{'enabled':False},'access':{'record':'public','files':'public'}}, issues


def collect(folder, params, rows, progress=lambda *args: None):
    params = parameters(params, rows); folder = Path(folder)
    queries = search_queries(params, rows)
    recipe = {'adapter':VERSION,'params':params,'queries':queries,'vocabulary_sha256':vocabulary_digest(rows)}
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = folder/'busca.json'; completed = folder/'resultado.json'
    if existing.exists() and json.loads(existing.read_text()) != recipe: raise ValueError('A coleta preservada usa outros parâmetros ou vocabulário.')
    if completed.exists():
        result = json.loads(completed.read_text())
        if any(Path(n).name != n or sha(folder/n) != h for n,h in result['input_hashes'].items()): raise ValueError('Lote concluído alterado; crie outra extração.')
        return result
    atomic(existing, recipe)
    # A single serial host agent owns this catalogue. Retried lots pin the same
    # catalogue boundary rather than silently consuming another page batch.
    boundary = folder/'catalogue.json'
    if boundary.exists():
        coverage = json.loads(boundary.read_text()); catalogue = catalog_path(folder.parents[1],params)
    else:
        catalogue, coverage = harvest(folder.parents[1],params,progress)
        atomic(boundary,coverage)
    nodes = [(q,expression(q['query'])) for q in queries]; counts = [0]*len(nodes); selected = {}; hashes={'busca.json':sha(existing),'catalogue.json':sha(boundary)}
    with closing(sqlite3.connect('file:'+str(catalogue/'catalog.sqlite')+'?mode=ro',uri=True)) as db:
        for (body,) in db.execute('SELECT body FROM records WHERE deleted=0 ORDER BY id'):
            raw = json.loads(body)
            if coverage.get('pages',0) and int(Path(raw['source_page']['file']).stem.split('_')[-1]) >= coverage['pages']: continue
            text = fold(' '.join(v for k in ('title','subject','description') for v in raw['dc'].get(k,[])))
            hits = [i for i,(_,node) in enumerate(nodes) if counts[i] < params['per_term'] and evaluate(node,text)]
            if not hits: continue
            identity = record_identity(raw,params['repository']); key = params['repository']+'_'+identity['handle'].replace('/','_')
            raw_file = 'metadata_'+key+'.json'; path=folder/raw_file
            if path.exists():
                pinned=json.loads(path.read_text())
                if pinned!=raw: raise ValueError('Registro de catálogo mudou durante retomada; gere uma nova coleta.')
            else: atomic(path,raw)
            hashes[raw_file]=sha(path)
            payload,issues=build_payload(raw,params['repository'])
            origins=[]
            for i in hits:
                query,_=nodes[i]; counts[i]+=1
                origins.append({'query':query['query'],'term':deepcopy(query['term']),'search_result':{'identifier':raw['identifier'],'datestamp':raw['datestamp'],'matched_fields':['title','subject','description']}})
            selected[key]={'key':key,'repository':params['repository'],'doi':next((v['identifier'] for v in payload['metadata']['identifiers'] if v['scheme']=='doi'),''),'handle':identity['handle'],'oai_identifier':raw['identifier'],
                'url':identity['url'],'payload':payload,'issues':issues,'origins':origins,'raw_file':raw_file}
    atomic(folder/'records.json',list(selected.values()));hashes['records.json']=sha(folder/'records.json')
    result={'status':'coleta_concluida','payloads':len(selected),'input_hashes':hashes,'adapter':VERSION,'coverage':coverage,
            'partial':not coverage['complete'],'collected_at':datetime.now(timezone.utc).isoformat()}
    atomic(completed,result);return result
