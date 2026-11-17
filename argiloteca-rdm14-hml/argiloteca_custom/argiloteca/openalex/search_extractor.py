"""Free/combined searches using the verified V59 transport and bibliographic tools.

Loaded in an isolated Mac child process; never modifies an installed V59 release.
"""
from copy import copy
import csv
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.parse import urlencode
import urllib.request


def search_queries(params, vocabulary):
    """Exact selected IDs; only All is sliced. Free input keeps OpenAlex syntax."""
    free = params['free_text']
    if not params['term']:
        return [free]
    selected = sorted(vocabulary, key=lambda r: r.get('title', {}).get('pt', r['id']).casefold())
    if params['term'] != '__all__':
        selected = [r for r in selected if r['id'] == params['term']]
        if params['offset']:
            raise ValueError('Para combinar um argilomineral específico, use deslocamento 0.')
    else:
        selected = selected[params['offset']:params['offset']+params['max_terms']]
    if not selected:
        raise ValueError('Nenhum termo selecionado. Reduza o deslocamento no vocabulário.')
    return [f'({free}) AND ({json.dumps(r["id"], ensure_ascii=False)})' for r in selected]


def fetch_query(client, query, limit):
    """Use V59 authenticated urllib transport, but propagate API errors as failures."""
    rows=[];page=1
    while len(rows)<limit:
        params={'search':query,'page':page,'per-page':min(client.per_page,limit-len(rows)),
                'select':client.SELECT_FIELDS}
        with urllib.request.urlopen(client.BASE_URL+'?'+urlencode(params),timeout=client.request_timeout) as response:
            payload=json.load(response)
        if not isinstance(payload,dict) or not isinstance(payload.get('results'),list):
            raise ValueError('Resposta inválida do OpenAlex; lote parcial preservado.')
        batch=payload['results'];rows.extend(batch)
        if len(batch)<params['per-page']:break
        page+=1
    return rows[:limit]


def collect(work, params, vocabulary):
    """Retain unclassified works and record the actual search without faking terms."""
    from sources.openalex import OpenAlexClient
    from processors.normalizer import normalize_work
    from processors.classifier import VocabularyClassifier
    from utils.dedup import deduplicate_records
    from outputs.exporter import export_records
    from outputs.argiloteca_exporter import record_to_argiloteca_payload

    queries=search_queries(params,vocabulary)
    (work/'busca.json').write_text(json.dumps({'mode':params['search_mode'],'queries':queries,
        'parameters':params,'unclassified_retained':True},ensure_ascii=False,indent=2))
    client=OpenAlexClient(per_page=100,request_timeout=30)
    raw=[]
    for query in queries:
        print('Consulta OpenAlex:',query,flush=True)
        raw.extend(fetch_query(client,query,params['per_term']))
    (work/'openalex_raw.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2))
    classifier=VocabularyClassifier(os.environ['GROUP_MAP_FILE'])
    records=deduplicate_records([classifier.classify(normalize_work(r)) for r in raw])
    export_records(records,work/'openalex_normalized.json')
    by_id={r['id']:r for r in vocabulary};payloads=[]
    with (work/'manifest.tsv').open('w',newline='') as handle:
        writer=csv.writer(handle,delimiter='\t',lineterminator='\n')
        for index,record in enumerate(records,1):
            # Bibliography only. A free search is neither a mineral nor a sample.
            bibliography=copy(record)
            if record.doi:bibliography.url='https://doi.org/'+record.doi
            payload=record_to_argiloteca_payload(bibliography);payload.pop('custom_fields',None)
            payload['metadata']['identifiers'] = ([{'scheme':'doi','identifier':record.doi}] if record.doi else []) + [
                {'scheme':'url','identifier':record.id}]
            payloads.append(payload)
            filename=f'payload_{index:05d}.json'
            (work/filename).write_text(json.dumps(payload,ensure_ascii=False,indent=2))
            term=record.matched_terms[0] if record.matched_terms else ''
            title=by_id.get(term,{}).get('title',{})
            writer.writerow([f'{index:05d}',str(work/filename),title.get('en',term),title.get('pt',term),
                             record.url or record.id,record.id,record.doi or '',f'{record.confidence_score:.2f}'])
    (work/'openalex_argiloteca.json').write_text(json.dumps(payloads,ensure_ascii=False,indent=2))
    return {'payloads':len(records),'manifest_rows':len(records),
        'distinct_openalex_ids':len({r.id for r in records}),
        'unclassified':sum(not r.matched_terms for r in records),'queries':queries}


def run(root,params,adapter):
    install,fingerprint=adapter.release(root,'extractor')
    spec=importlib.util.spec_from_file_location('verified_v59_runner',install/'runtime_runner.py')
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    sys.path.insert(0,str(install))  # The verified runner imports its sibling auth adapter.
    config,key=runner.configuration()
    saved_out,saved_err=sys.stdout,sys.stderr
    sys.stdout,sys.stderr=runner.SafeStream(saved_out,key),runner.SafeStream(saved_err,key)
    work=None
    try:
        state=runner.precheck(config,key)
        params=adapter.extraction_parameters(params,adapter.terms(root))
        if not params['free_text']:raise ValueError('Informe o termo livre para esta modalidade.')
        vocabulary=runner.vocabulary()
        search_queries(params,vocabulary)  # Refuse invalid selection before creating a lot.
        work=Path(tempfile.mkdtemp(prefix=time.strftime('v59_%Y%m%d_%H%M%S_'),dir=Path(root)/'lotes'))
        print('Lote novo:',work,flush=True)
        runner.write_new_json(work/'parametros.json',{'install':str(install),'parameters':params,
            'adapter':'free-combined-v1','release_sha256':fingerprint,'api_key_configured':True})
        before=state.stats()['authenticated_requests']
        result=collect(work,params,vocabulary)
        if result['payloads']:runner.validate_result(work)
        if state.stats()['authenticated_requests']<=before:
            raise ValueError('Não foi observada requisição autenticada no OpenAlex.')
        result.update(status='coleta_concluida',authentication=state.stats(),invenio_schema_validated=False)
        runner.write_new_json(work/'resultado.json',result)
        print('COLETA CONCLUIDA:',result['payloads'],'publicações; sem classificação:',result['unclassified'])
        print('Pasta do lote:',work)
        return 0
    except Exception as exc:
        # No raw exceptions/URLs in public job messages: they may contain a key.
        if work:
            runner.write_new_json(work/'falha.json',{'status':'falha','error_type':type(exc).__name__,
                'message':runner.redact(str(exc),key)})
        print('Falha na busca OpenAlex:',runner.redact(str(exc),key),file=sys.stderr)
        return 1
    finally:
        sys.stdout.finish();sys.stderr.finish();sys.stdout,sys.stderr=saved_out,saved_err
