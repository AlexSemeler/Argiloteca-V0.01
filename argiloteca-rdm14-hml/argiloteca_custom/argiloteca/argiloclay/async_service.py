"""Session-owned jobs; recheck current public sources before publishing prose."""
import hashlib
import json
import re
import time
from .service import query, revalidate_response, public_record, Unavailable
from .presentation import enrich_generation


def fingerprint(sources):
    return hashlib.sha256(json.dumps(sources, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def reader_fallback(data,language='pt',pending=False):
    if data.get('generation_mode') in ('metadata_template','verified_foundations','bibliographic_lookup','rag_generated'):return data
    if not data.get('sources'):return data
    data['answer']=('I am preparing an explanation based on the retrieved sources.' if language=='en' else 'Estou preparando uma explicação com base nas fontes recuperadas.') if pending else ('I could not produce a reliable explanation from the retrieved sources. Please narrow the question or inspect the source pages in Sources.' if language=='en' else 'Não consegui produzir uma explicação confiável a partir das fontes recuperadas. Especifique melhor a pergunta ou confira as páginas citadas no botão Fontes.')
    return data


def start(payload, client, resolver=public_record):
    started=time.monotonic()
    base=query(payload,client,resolver)
    if not base['sources']:
        base['generation']={'state':'refused','reason':'no_evidence'};return base
    if base.get('generation_mode')=='verified_foundations':
        base['generation']={'state':'complete','reason':'reviewed_definitions'};return base
    if base.get('generation_mode')=='bibliographic_lookup':
        base['generation']={'state':'complete','reason':'verified_bibliography'};return base
    if base.get('generation_mode')=='metadata_template' and all(source.get('derivation') in ('live_mineral_catalog','live_public_metadata_fields','live_public_metadata_overview','live_community_about') for source in base['sources']):
        base['generation']={'state':'complete','reason':'verified_metadata'}
        return base
    budget=max(1, min(90,95-(time.monotonic()-started)))
    try:
        job=client.call('/api/v1/chat/generation',{'question':payload['question'].strip(),'sources':base['sources'],
                         'language':base['page_context']['language'],'budget_seconds':budget,'limitations':base.get('limitations',[])})
    except Unavailable:
        job={'state':'fallback','reason':'unavailable'}
    base['generation']=job
    return reader_fallback(base,base['page_context']['language'],pending=job.get('state')=='pending')


def poll(key, client, language='pt', resolver=public_record):
    row=client.call('/api/v1/chat/generation/'+key)
    if row.get('state') not in {'pending','complete','fallback','cancelled'}: raise Unavailable('Estado de geração inválido.')
    sources=row.get('sources',[])
    if not isinstance(sources,list) or len(sources)>4: raise Unavailable('Fontes inválidas.')
    original=fingerprint(sources)
    data=revalidate_response({'sources':sources,'schema_version':'1.0','available':True,'limitations':list(row.get('limitations',[]))},resolver,language,question=row.get('question'))
    # Any revoked or changed source invalidates the entire generated paragraph.
    # Strip only gateway-added URL/visibility flags before comparing provenance.
    same=len(data['sources'])==len(sources) and all(
        all(a.get(k)==b.get(k) for k in ('document_id','excerpt','sha256','record_id','updated'))
        for a,b in zip(data['sources'],sources))
    state=row['state'];data['generation']={'state':state,'reason':row.get('reason'),'model':'qwen3:0.6b'}
    if not same:
        data['generation']={'state':'fallback','reason':'source_changed'}
        return reader_fallback(data,language,pending=data.get('generation',{}).get('state')=='pending')
    if state=='complete':
        answer=row.get('generated_answer');refs=re.findall(r'\[Fonte (\d+)\]',answer) if isinstance(answer,str) else []
        if not row.get('validated') or row.get('sources_fingerprint')!=original or not refs or any(int(n)<1 or int(n)>len(sources) for n in refs):
            data['generation']={'state':'fallback','reason':'invalid_generation'};return reader_fallback(data,language)
        data.update(answer=enrich_generation(answer,sources),generation_mode='rag_generated',model='qwen3:0.6b',response_kind='grounded_summary')
        if re.search(r'\b(amostra|sample|drx|xrd|pico|peak|identific|teor|curva|curve)\w*',row.get('question','').lower()):data['limitations'].append('Síntese automática dos trechos citados; não confirma identificação mineralógica.' if language=='pt' else 'Automatic synthesis of cited excerpts; it does not confirm mineral identification.')
    return reader_fallback(data,language,pending=data.get('generation',{}).get('state')=='pending')
