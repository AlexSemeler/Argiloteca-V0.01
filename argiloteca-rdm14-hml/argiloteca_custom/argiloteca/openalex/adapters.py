"""Read the existing V59 inputs and verified bibliographic converter, unchanged."""
from functools import lru_cache
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

LOT = re.compile(r'v59_[A-Za-z0-9_]+')


def confined(path, root):
    path, root = Path(path).absolute(), Path(root).resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError('Caminho fora da raiz configurada ou por link simbólico.')
    if any(p.is_symlink() for p in (path, *path.parents) if p != root):
        raise ValueError('Links simbólicos não são permitidos.')
    return path


def read_json(path, root, limit=16*1024*1024):
    path = confined(path, root)
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Arquivo ausente ou acima do limite.')
    return json.loads(path.read_text(encoding='utf-8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def verify_files(folder, files):
    if not isinstance(files, dict) or not files:
        raise ValueError('Manifesto de instalação ausente.')
    for relative, expected in files.items():
        path = confined(folder / relative, folder)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Instalação alterada: ' + str(relative))


def release(root, kind):
    root = Path(root)
    parent = root / ('processos/metadados_invenio/instalacoes' if kind == 'metadata' else 'instalacoes')
    candidates = []
    for folder in parent.glob('metadados_v1_*' if kind == 'metadata' else 'v59_*'):
        try:
            marker = read_json(folder / 'PRONTO.json', parent)
            if marker.get('state') != 'ready':
                continue
            files = marker.get('files') if kind == 'metadata' else read_json(folder / 'arquivos-preparados.json', folder)
            required = {'invenio_metadata.py', 'lote_inputs.py', 'preparar_metadados.py'} if kind == 'metadata' else {'runtime_runner.py', 'pipeline_v59.py', 'executar_openalex.sh', 'configuracao.json'}
            if not required.issubset(files):
                continue
            verify_files(folder, files)
            candidates.append((folder.stat().st_mtime_ns, folder, digest(files)))
        except (ValueError, OSError, TypeError):
            continue
    if not candidates:
        raise ValueError('Nenhuma instalação íntegra disponível: ' + kind)
    return max(candidates, key=lambda v: (v[0], str(v[1])))[1:]


@lru_cache(maxsize=4)
def _converter(folder, fingerprint):
    # Original imports are preserved. A worker uses one verified release until restart.
    folder = Path(folder)
    modules = []
    for name in ('invenio_metadata', 'lote_inputs'):
        existing = sys.modules.get(name)
        if existing and Path(existing.__file__).parent != folder:
            raise ValueError('Conversor atualizado: reinicie os workers antes de continuar.')
        if not existing:
            spec = importlib.util.spec_from_file_location(name, folder / (name + '.py'))
            existing = importlib.util.module_from_spec(spec)
            sys.modules[name] = existing
            spec.loader.exec_module(existing)
        modules.append(existing)
    # Reuse the legacy CLI's pure vocabulary enumeration without executing its
    # dispatcher, HTTP client imports or sys.path mutations in the web worker.
    tree = ast.parse((folder / 'preparar_metadados.py').read_text(encoding='utf-8'))
    helper = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'required_vocabularies')
    namespace = {}
    exec(compile(ast.Module(body=[helper], type_ignores=[]), str(folder / 'preparar_metadados.py'), 'exec'), namespace)
    modules[0].required_vocabularies = namespace['required_vocabularies']
    return modules


def converter(root):
    folder, fingerprint = release(root, 'metadata')
    return (*_converter(str(folder), fingerprint), {'release': folder.name, 'sha256': fingerprint})


def lot_path(root, name):
    if not LOT.fullmatch(str(name)):
        raise ValueError('Identificador de lote inválido.')
    return confined(Path(root) / 'lotes' / name, Path(root) / 'lotes')


def lots(root):
    result = []
    for folder in sorted((Path(root) / 'lotes').glob('v59_*'), reverse=True):
        try:
            marker = read_json(folder / 'resultado.json', Path(root) / 'lotes', 2*1024*1024)
            complete = marker.get('status') == 'coleta_concluida'
            result.append({'name': folder.name, 'complete': complete, 'count': marker.get('payloads', 0)})
        except (ValueError, OSError):
            result.append({'name': folder.name, 'complete': False, 'count': 0})
    return result


def terms(root):
    folder, _ = release(root, 'extractor')
    path = folder / 'runtime/argiloteca/app_data/data/vocabularies/argilominerais.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [{'id': r['id'], 'title': r.get('title', {}).get('pt', r['id'])}
            for r in rows if r.get('props', {}).get('status') in (None, '', 'preferred')]


def extraction_parameters(data, available):
    term = str(data.get('term', '')).strip()
    free_text = str(data.get('free_text', '')).strip()
    if len(free_text) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in free_text):
        raise ValueError('O termo livre deve ter até 500 caracteres, sem quebras de linha ou controles.')
    if term and term not in {t['id'] for t in available} | {'__all__'}:
        raise ValueError('Selecione um termo válido do vocabulário.')
    if not term and not free_text:
        raise ValueError('Informe um termo livre ou selecione um termo do vocabulário.')
    result = {'term': term, 'free_text': free_text,
              'search_mode': 'combined' if term and free_text else 'free' if free_text else 'vocabulary'}
    for name, default, minimum, maximum in [('max_terms', 1, 1, 100), ('per_term', 1, 1, 100), ('offset', 0, 0, 10000)]:
        try:
            value = int(data.get(name, default))
        except (TypeError, ValueError):
            raise ValueError('Limite numérico inválido: ' + name) from None
        if not minimum <= value <= maximum:
            raise ValueError('Limite fora da faixa: ' + name)
        result[name] = value
    if free_text and term and term != '__all__' and result['offset']:
        raise ValueError('Para combinar um argilomineral específico, use deslocamento 0.')
    return result


def prepare(root, name, corrections=None, limit=0):
    metadata, reader, version = converter(root)
    path = lot_path(root, name)
    # Validate all correction fields using the original reader's validator.
    if corrections:
        allowed = {'creators', 'title', 'publication_date', 'resource_type', 'description', 'languages', 'rights', 'subjects', 'publisher', 'contributors', 'additional_titles', 'additional_descriptions', 'dates', 'version', 'sizes', 'formats', 'references', 'funding', 'locations'}
        if not isinstance(corrections, dict) or any(not isinstance(v, dict) or set(v)-allowed for v in corrections.values()):
            raise ValueError('Correções devem conter apenas campos descritivos por chave de origem.')
    result = reader.prepare_lot(path, corrections=corrections, limit=limit)
    if (path / 'busca.json').exists():
        result['extraction_search'] = read_json(path / 'busca.json', path, 128*1024)
        result['input_hashes']['busca.json'] = hashlib.sha256((path / 'busca.json').read_bytes()).hexdigest()
    result['converter'] = version
    result['corrections'] = corrections or {}
    for row in result['records']:
        row['payload_sha256'] = digest(row['payload'])
    return result


def verify_snapshot(root, snapshot):
    path = lot_path(root, Path(snapshot['source']).name)
    for relative, expected in snapshot['input_hashes'].items():
        file = confined(path / relative, path)
        with file.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('Lote de origem alterado; prepare uma nova revisão.')
    for row in snapshot['records']:
        if digest(row['payload']) != row['payload_sha256']:
            raise ValueError('Payload alterado após a revisão.')
