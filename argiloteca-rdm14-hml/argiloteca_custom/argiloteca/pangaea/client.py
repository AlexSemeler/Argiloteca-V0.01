"""Public PANGAEA search/JSON-LD adapter; stdlib-only for the Mac bridge.

Based on V57's search endpoint, DOI candidate extraction and bilingual terms.
Structured source metadata replaces V57's inferred samples and placeholders.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse
import urllib.request

SEARCH_URL = 'https://www.pangaea.de/advanced/search.php'
DOI = re.compile(r'10\.1594/PANGAEA\.\d+', re.I)
VERSION = 'argiloteca-pangaea/1.0'


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
    try:
        with os.fdopen(fd, 'w') as stream:
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


def parameters(data, rows):
    """Same three search modes and bounds as OpenAlex; exact mineral selection."""
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
        queries.append({'query': query + ' -type:series -type:bundled', 'term': row})
    return queries


def fetch_json(url):
    request = urllib.request.Request(url, headers={
        'Accept': 'application/ld+json, application/json', 'User-Agent': VERSION + ' (+https://www.pangaea.de)'})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError('Resposta PANGAEA acima de 8 MiB.')
    return json.loads(body)


def result_to_candidate(item):
    # V57 searched the entire JSON blob and could pick a cited, unrelated DOI.
    # The search API declares the dataset's own identity in URI.
    match = DOI.fullmatch(str(item.get('URI', '')).removeprefix('doi:').removeprefix('https://doi.org/').removeprefix('https://doi.pangaea.de/'))
    if not match:
        return None
    doi = '10.1594/PANGAEA.' + match.group().rsplit('.', 1)[1]
    return {'doi': doi, 'url': 'https://doi.pangaea.de/' + doi, 'raw': item}


def dataset_node(raw):
    nodes = raw if isinstance(raw, list) else raw.get('@graph', [raw]) if isinstance(raw, dict) else []
    for node in nodes:
        if isinstance(node, dict) and 'Dataset' in [str(t).rsplit('/', 1)[-1] for t in as_list(node.get('@type'))]:
            return node
    raise ValueError('Metadados JSON-LD sem Dataset.')


def as_list(value):
    return value if isinstance(value, list) else [] if value is None else [value]


def text(value):
    if isinstance(value, dict):
        return str(value.get('@value', value.get('name', '')))
    return str(value or '')


def build_payload(raw, doi):
    node = dataset_node(raw)
    source_ids = [text(v) for v in as_list(node.get('identifier'))] + [text(node.get('@id')), text(node.get('url'))]
    if not any(DOI.search(v) and DOI.search(v).group().lower() == doi.lower() for v in source_ids):
        raise ValueError('O DOI dos metadados difere do resultado da busca.')
    creators = []
    for author in as_list(node.get('creator') or node.get('author')):
        author = author if isinstance(author, dict) else {'name': text(author)}
        name = text(author.get('name'))
        if not name:
            continue
        person = {'type': 'organizational' if 'Organization' in as_list(author.get('@type')) else 'personal', 'name': name}
        if person['type'] == 'personal':
            if author.get('familyName'):
                person['family_name'] = text(author['familyName'])
            if author.get('givenName'):
                person['given_name'] = text(author['givenName'])
            for value in (author.get('@id'), author.get('identifier')):
                match = re.fullmatch(r'https?://orcid.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])', text(value))
                if match:
                    person['identifiers'] = [{'scheme': 'orcid', 'identifier': match.group(1)}]
                    break
        creators.append({'person_or_org': person})
    metadata = {'resource_type': {'id': 'dataset'}, 'title': text(node.get('name')),
                'publication_date': text(node.get('datePublished'))[:10], 'creators': creators,
                'publisher': text(node.get('publisher')) or 'PANGAEA',
                'identifiers': [{'scheme': 'doi', 'identifier': doi},
                                {'scheme': 'url', 'identifier': 'https://doi.pangaea.de/' + doi}]}
    description = text(node.get('description') or node.get('abstract'))
    if description:
        metadata['description'] = '<p>' + html.escape(description).replace('\n', '<br>') + '</p>'
    keywords = node.get('keywords', [])
    if isinstance(keywords, str):
        keywords = keywords.split(',')
    subjects = list(dict.fromkeys(text(v).strip() for v in as_list(keywords) if text(v).strip()))
    if subjects:
        metadata['subjects'] = [{'subject': s} for s in subjects]
    language = {'en': 'eng', 'pt': 'por', 'de': 'deu', 'fr': 'fra', 'es': 'spa'}.get(text(node.get('inLanguage')))
    if language:
        metadata['languages'] = [{'id': language}]
    rights = []
    for license in as_list(node.get('license')):
        value = license.get('url') or license.get('@id') if isinstance(license, dict) else license
        if value and urllib.parse.urlsplit(str(value)).scheme in ('http', 'https'):
            rights.append({'title': {'en': text(license.get('name')) or str(value)} if isinstance(license, dict) else {'en': str(value)}, 'link': str(value)})
    if rights:
        metadata['rights'] = rights
    locations = []
    for place in as_list(node.get('spatialCoverage')):
        if not isinstance(place, dict):
            continue
        location = {}
        if place.get('name'):
            location['place'] = text(place['name'])
        geo = place.get('geo', {})
        if isinstance(geo, dict) and 'latitude' in geo and 'longitude' in geo:
            try:
                lat, lon = float(geo['latitude']), float(geo['longitude'])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    location['geometry'] = {'type': 'Point', 'coordinates': [lon, lat]}
            except (ValueError, TypeError):
                pass
        if location:
            locations.append(location)
    if locations:
        metadata['locations'] = {'features': locations}
    payload = {'metadata': metadata, 'files': {'enabled': False},
               'access': {'record': 'public', 'files': 'public'}}
    issues = []
    for field in ('title', 'creators', 'publication_date'):
        if not metadata[field]:
            issues.append({'severity': 'error', 'code': 'missing_source', 'path': 'metadata.' + field,
                           'message': 'Campo obrigatório ausente na fonte; corrija após conferência.'})
    if not rights:
        issues.append({'severity': 'warning', 'code': 'license_missing', 'path': 'metadata.rights',
                       'message': 'Licença não informada; confira a página de origem.'})
    return payload, issues


def collect(folder, params, rows, progress=lambda *args: None):
    """Cache every response for resumable collection; completed lots are immutable."""
    folder = Path(folder)
    queries = search_queries(params, rows)
    recipe = {'adapter': VERSION, 'params': params, 'queries': queries,
              'vocabulary_sha256': vocabulary_digest(rows)}
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    recipe_path = folder / 'busca.json'
    if recipe_path.exists() and json.loads(recipe_path.read_text()) != recipe:
        raise ValueError('A coleta preservada usa parâmetros ou vocabulário diferentes.')
    completed = folder / 'resultado.json'
    if completed.exists():
        result = json.loads(completed.read_text())
        if any(sha(folder / name) != expected for name, expected in result['input_hashes'].items()):
            raise ValueError('O lote concluído foi alterado; execute uma nova coleta.')
        return result
    atomic(recipe_path, recipe)
    records = {}
    hashes = {'busca.json': sha(recipe_path)}
    for index, query in enumerate(queries):
        path = folder / f'search_{index:03d}.json'
        if not path.exists():
            url = SEARCH_URL + '?' + urllib.parse.urlencode({'q': query['query'], 'count': params['per_term'], 'offset': 0})
            atomic(path, fetch_json(url))
        search = json.loads(path.read_text())
        if not isinstance(search, dict) or not isinstance(search.get('results'), list):
            raise ValueError('Resposta de busca PANGAEA inválida.')
        hashes[path.name] = sha(path)
        for item in search['results'][:params['per_term']]:
            candidate = result_to_candidate(item)
            if not candidate:
                raise ValueError('Resultado PANGAEA sem DOI primário reconhecido.')
            doi = candidate['doi']
            origin = {'query': query['query'], 'term': deepcopy(query['term']), 'search_result': item}
            if doi in records:
                records[doi]['origins'].append(origin)
                continue
            key = doi.rsplit('.', 1)[1]
            metadata_path = folder / ('metadata_' + key + '.json')
            if not metadata_path.exists():
                atomic(metadata_path, fetch_json(candidate['url']))
            raw = json.loads(metadata_path.read_text())
            payload, issues = build_payload(raw, doi)
            hashes[metadata_path.name] = sha(metadata_path)
            records[doi] = {'key': key, 'doi': doi, 'url': candidate['url'], 'payload': payload,
                            'issues': issues, 'origins': [origin], 'raw_file': metadata_path.name}
        progress(index + 1, len(queries), len(records))
    atomic(folder / 'records.json', list(records.values()))
    hashes['records.json'] = sha(folder / 'records.json')
    result = {'status': 'coleta_concluida', 'payloads': len(records), 'input_hashes': hashes,
              'adapter': VERSION, 'collected_at': datetime.now(timezone.utc).isoformat()}
    atomic(folder / 'resultado.json', result)
    return result
