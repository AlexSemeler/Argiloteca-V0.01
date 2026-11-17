"""Public Mendeley metadata via its DataCite deposit. Stdlib-only host adapter.

No authenticated search, scraping, scientific-file download or inferred samples.
A collected dataset pins the latest version declared by its concept DOI.
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
import time
import urllib.error
import urllib.parse
import urllib.request

SEARCH_URL = 'https://api.datacite.org/dois'
CLIENT = 'bl.mendeley'
VERSION = 'argiloteca-mendeley/1.0'
DOI = re.compile(r'10\.17632/([a-z0-9]{10})(?:\.([1-9][0-9]*))?', re.I)
MAX_BYTES = 8 * 1024 * 1024


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


def parameters(data, rows):
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


def fetch_json(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.netloc != 'api.datacite.org' or not parts.path.startswith('/dois'):
        raise ValueError('Endpoint público de metadados inválido.')
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.api+json', 'User-Agent': VERSION})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if urllib.parse.urlsplit(response.url).netloc != 'api.datacite.org':
                    raise ValueError('Redirecionamento externo inesperado.')
                body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('Resposta DataCite acima de 8 MiB.')
            return json.loads(body)
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 502, 503, 504} or attempt == 2:
                raise
            retry = str(exc.headers.get('Retry-After', ''))
            time.sleep(min(30, int(retry)) if retry.isdigit() else 2 ** (attempt + 1))


def identity(raw):
    if not isinstance(raw, dict) or raw.get('type') != 'dois':
        raise ValueError('Registro DataCite inválido.')
    attrs = raw.get('attributes', {})
    doi = str(attrs.get('doi', '')).lower()
    match = DOI.fullmatch(doi)
    if not match or str(raw.get('id', '')).lower() != doi:
        raise ValueError('DOI primário Mendeley Data ausente ou divergente.')
    client = raw.get('relationships', {}).get('client', {}).get('data', {}).get('id')
    if client != CLIENT or attrs.get('types', {}).get('resourceTypeGeneral') != 'Dataset' or attrs.get('state') != 'findable':
        raise ValueError('O registro não é um dataset público do Mendeley Data.')
    expected_path = '/datasets/' + match[1] + ('/' + match[2] if match[2] else '')
    url = urllib.parse.urlsplit(str(attrs.get('url', '')))
    if url.scheme != 'https' or url.netloc != 'data.mendeley.com' or url.path.rstrip('/') != expected_path or url.query or url.fragment:
        raise ValueError('A URL do dataset difere da identidade e versão DOI.')
    return {'doi': doi, 'dataset_id': match[1], 'version': match[2],
            'concept_doi': '10.17632/' + match[1], 'url': 'https://data.mendeley.com' + expected_path}


def publication_date(attrs):
    for date in attrs.get('dates') or []:
        if date.get('dateType') == 'Issued':
            value = str(date.get('date', ''))
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T.*)?', value):
                try:
                    datetime.strptime(value[:10], '%Y-%m-%d')
                    return value[:10]
                except ValueError:
                    continue
            if re.fullmatch(r'\d{4}(?:-\d{2})?', value):
                try:
                    datetime.strptime(value, '%Y-%m' if len(value) == 7 else '%Y')
                    return value
                except ValueError:
                    continue
    # A year is a valid native EDTF value; do not invent a month/day.
    year = str(attrs.get('publicationYear', ''))
    return year if re.fullmatch(r'[1-9]\d{3}', year) else ''


def build_payload(raw, doi):
    source = identity(raw)
    if source['doi'] != doi.lower():
        raise ValueError('Metadados não correspondem ao DOI selecionado.')
    attrs = raw['attributes']
    creators = []
    for author in attrs.get('creators') or []:
        if not author.get('name'):
            continue
        person = {'type': 'organizational' if author.get('nameType') == 'Organizational' else 'personal', 'name': author['name']}
        if person['type'] == 'personal':
            for field, target in [('familyName', 'family_name'), ('givenName', 'given_name')]:
                if author.get(field):
                    person[target] = author[field]
            for item in author.get('nameIdentifiers') or []:
                value = str(item.get('nameIdentifier', '')).removeprefix('https://orcid.org/').removeprefix('http://orcid.org/')
                if str(item.get('nameIdentifierScheme', '')).lower() == 'orcid' and re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', value):
                    person['identifiers'] = [{'scheme': 'orcid', 'identifier': value}]
                    break
        creator = {'person_or_org': person}
        affiliations = [{'name': v.get('name')} if isinstance(v, dict) else {'name': v} for v in author.get('affiliation') or []]
        affiliations = [v for v in affiliations if v['name']]
        if affiliations:
            creator['affiliations'] = affiliations
        creators.append(creator)
    titles = attrs.get('titles') or []
    publisher = attrs.get('publisher')
    if isinstance(publisher, dict):
        publisher = publisher.get('name')
    metadata = {'resource_type': {'id': 'dataset'}, 'title': next((v['title'] for v in titles if v.get('title')), ''),
                'publication_date': publication_date(attrs), 'creators': creators,
                'publisher': publisher or 'Mendeley Data',
                'identifiers': [{'scheme': 'doi', 'identifier': source['doi']}, {'scheme': 'url', 'identifier': source['url']}]}
    if source['version']:
        metadata['version'] = source['version']
    descriptions = [v['description'] for v in attrs.get('descriptions') or [] if v.get('description')]
    if descriptions:
        metadata['description'] = ''.join('<p>' + html.escape(v).replace('\n', '<br>') + '</p>' for v in descriptions)
    subjects = list(dict.fromkeys(v['subject'].strip() for v in attrs.get('subjects') or [] if v.get('subject', '').strip()))
    if subjects:
        metadata['subjects'] = [{'subject': s} for s in subjects]
    language = {'en': 'eng', 'pt': 'por', 'de': 'deu', 'fr': 'fra', 'es': 'spa', 'eng': 'eng', 'por': 'por'}.get(attrs.get('language'))
    if language:
        metadata['languages'] = [{'id': language}]
    rights = []
    for item in attrs.get('rightsList') or []:
        link = item.get('rightsUri', '')
        if urllib.parse.urlsplit(link).scheme in {'https', 'http'}:
            rights.append({'title': {'en': item.get('rights') or link}, 'link': link})
    if rights:
        metadata['rights'] = rights
    locations = []
    for item in attrs.get('geoLocations') or []:
        location = {'place': item['geoLocationPlace']} if item.get('geoLocationPlace') else {}
        point = item.get('geoLocationPoint') or {}
        try:
            lon, lat = float(point['pointLongitude']), float(point['pointLatitude'])
            if -180 <= lon <= 180 and -90 <= lat <= 90:
                location['geometry'] = {'type': 'Point', 'coordinates': [lon, lat]}
        except (KeyError, TypeError, ValueError):
            pass
        if location:
            locations.append(location)
    if locations:
        metadata['locations'] = {'features': locations}
    for field in ('sizes', 'formats'):
        if attrs.get(field):
            metadata[field] = deepcopy(attrs[field])
    issues = []
    for field in ('title', 'creators', 'publication_date'):
        if not metadata[field]:
            issues.append({'severity': 'error', 'code': 'missing_source', 'path': 'metadata.' + field,
                           'message': 'Campo obrigatório ausente na fonte; corrija após conferência.'})
    if not source['version']:
        issues.append({'severity': 'warning', 'code': 'version_missing', 'path': 'metadata.version',
                       'message': 'A fonte não declara versão; DOI geral preservado sem inferir versão.'})
    if not rights:
        issues.append({'severity': 'warning', 'code': 'license_missing', 'path': 'metadata.rights',
                       'message': 'Licença não informada; confira a página de origem.'})
    return {'metadata': metadata, 'files': {'enabled': False}, 'access': {'record': 'public', 'files': 'public'}}, issues


def collect(folder, params, rows, progress=lambda *args: None):
    """Pin versions, preserve all responses and fail closed on malformed input."""
    folder = Path(folder)
    params = parameters(params, rows)
    queries = search_queries(params, rows)
    recipe = {'adapter': VERSION, 'provider': 'DataCite', 'repository_client': CLIENT,
              'params': params, 'queries': queries, 'version_policy': 'latest-declared-or-unversioned-legacy',
              'vocabulary_sha256': vocabulary_digest(rows)}
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    recipe_path = folder / 'busca.json'
    if recipe_path.exists() and json.loads(recipe_path.read_text()) != recipe:
        raise ValueError('A coleta preservada usa parâmetros ou vocabulário diferentes.')
    completed = folder / 'resultado.json'
    if completed.exists():
        result = json.loads(completed.read_text())
        for name, expected in result['input_hashes'].items():
            if Path(name).name != name or sha(folder / name) != expected:
                raise ValueError('O lote concluído foi alterado; execute uma nova coleta.')
        return result
    atomic(recipe_path, recipe)
    records, hashes = {}, {'busca.json': sha(recipe_path)}

    def cached(name, url):
        path = folder / name
        if path.is_symlink():
            raise ValueError('Resposta preservada por link simbólico não é permitida.')
        if not path.exists():
            atomic(path, fetch_json(url))
        hashes[name] = sha(path)
        return json.loads(path.read_text())

    for index, query in enumerate(queries):
        url = SEARCH_URL + '?' + urllib.parse.urlencode({'query': query['query'], 'client-id': CLIENT,
            'resource-type-id': 'dataset', 'page[size]': params['per_term'], 'page[number]': 1, 'sort': '-published'})
        search = cached(f'search_{index:03d}.json', url)
        if not isinstance(search, dict) or not isinstance(search.get('data'), list) or search.get('errors'):
            raise ValueError('Resposta de busca DataCite inválida.')
        for item in search['data'][:params['per_term']]:
            found = identity(item)
            key = found['dataset_id']
            origin = {'query': query['query'], 'term': deepcopy(query['term']), 'search_result': item, 'search_url': url}
            if key in records:
                records[key]['origins'].append(origin)
                continue
            concept_file = 'concept_' + key + '.json'
            concept = cached(concept_file, SEARCH_URL + '/' + found['concept_doi'])
            base = identity(concept.get('data'))
            if base['doi'] != found['concept_doi'] or base['version']:
                raise ValueError('DOI geral diverge do dataset encontrado.')
            versions = []
            for relation in concept['data']['attributes'].get('relatedIdentifiers') or []:
                if relation.get('relationType') == 'HasVersion' and relation.get('relatedIdentifierType') == 'DOI':
                    match = DOI.fullmatch(str(relation.get('relatedIdentifier', '')).lower())
                    if not match or match[1] != key or not match[2]:
                        raise ValueError('Relação de versão DOI divergente.')
                    versions.append(int(match[2]))
            if versions:
                version = max(versions)
                if found['version'] and int(found['version']) > version:
                    raise ValueError('Versão encontrada não está declarada no DOI geral; tente novamente mais tarde.')
                doi = found['concept_doi'] + '.' + str(version)
                raw_file = f'metadata_{key}_{version}.json'
                raw = cached(raw_file, SEARCH_URL + '/' + doi)
            else:
                # Legacy Mendeley records can have only an unversioned DOI.
                # Never guess .1 or replace it with a DOI cited by the paper.
                version, doi, raw_file, raw = '', base['doi'], concept_file, concept
                if found['version']:
                    version, doi = found['version'], found['doi']
                    raw_file = f'metadata_{key}_{version}.json'
                    raw = cached(raw_file, SEARCH_URL + '/' + doi)
            payload, issues = build_payload(raw.get('data'), doi)
            if not versions and version:
                issues.append({'severity': 'warning', 'code': 'latest_unverified', 'path': 'metadata.version',
                               'message': 'Versão encontrada preservada; o DOI geral não declara qual é a mais recente.'})
            source = identity(raw['data'])
            records[key] = {'key': key, 'doi': doi, 'concept_doi': found['concept_doi'], 'version': str(version),
                            'url': source['url'], 'payload': payload, 'issues': issues, 'origins': [origin],
                            'raw_file': raw_file, 'concept_file': concept_file}
        progress(index + 1, len(queries), len(records))
    atomic(folder / 'records.json', list(records.values()))
    hashes['records.json'] = sha(folder / 'records.json')
    result = {'status': 'coleta_concluida', 'payloads': len(records), 'input_hashes': hashes,
              'adapter': VERSION, 'provider': 'DataCite', 'repository_client': CLIENT,
              'collected_at': datetime.now(timezone.utc).isoformat()}
    atomic(folder / 'resultado.json', result)
    return result
