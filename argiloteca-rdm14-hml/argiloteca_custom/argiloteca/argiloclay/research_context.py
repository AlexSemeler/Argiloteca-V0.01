"""Bounded, anonymous publication suggestions and dated repository counts."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from .community_sources import normalize_question, GENERAL, GRAMMAR
from .presentation import record_source

EQUIVALENTS={'caulinita':['kaolinite','kaolinita'],'kaolinite':['caulinita','kaolinita'],
 'esmectitas':['smectite','smectites'],'esmectita':['smectite','smectites'],
 'ilita':['illite'],'illite':['ilita'],'hidrotalcita':['hydrotalcite'],'hidrotalcitas':['hydrotalcite']}


def terms_for(question):
    q=normalize_question(question)
    if any(re.search(r'\b'+re.escape(t)+r'\b',q) for t in GENERAL):
        return ['argilominerais','clay minerals','clay mineral']
    if re.search(r'\b(argilas?|clays?)\b',q):return ['argilas','clays','clay']
    words=[w for w in re.findall(r'[\w-]+',q) if w not in GRAMMAR and len(w)>2]
    terms=[]
    for w in words[:4]:
        terms.extend([w,*EQUIVALENTS.get(w,[])])
    return list(dict.fromkeys(terms))[:8]


def native_search(query, size=3):
    from flask_principal import AnonymousIdentity
    from invenio_access.permissions import any_user
    from invenio_rdm_records.proxies import current_rdm_records_service
    identity=AnonymousIdentity();identity.provides.add(any_user)
    return current_rdm_records_service.search(identity,params={'q':query,'size':size,'sort':'bestmatch'}).to_dict()


def collect(question, resolver, searcher=None, today=None):
    from flask import has_app_context
    if searcher is None and not has_app_context():return {'sources':[]}
    searcher=searcher or native_search
    terms=terms_for(question)
    if not terms:return {'sources':[]}
    # No raw search syntax from the user enters a query.
    if any(not re.fullmatch(r'[\w -]{2,100}',t) for t in terms):return {'sources':[]}
    query='('+' OR '.join('"'+t+'"' for t in terms)+') AND metadata.resource_type.id:publication*'
    result=searcher(query,3);sources=[];seen=set();dois=set()
    for hit in result.get('hits',{}).get('hits',[])[:3]:
        rid=hit.get('id')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',rid) or rid in seen:continue
        current=resolver(rid)
        if (not current or current.get('access',{}).get('record')!='public'
                or current.get('is_draft') or current.get('is_published') is False
                or not current.get('metadata',{}).get('resource_type',{}).get('id','').startswith('publication')):continue
        doi=str(current.get('pids',{}).get('doi',{}).get('identifier','')).lower().removeprefix('https://doi.org/').strip()
        if doi and doi in dois:continue
        source=record_source(current,rid)
        if source:
            sources.append(source);seen.add(rid)
            if doi:dois.add(doi)
    today=today or datetime.now(ZoneInfo('America/Sao_Paulo')).date()
    end=today.year-1;windows=[(end-9,end-5),(end-4,end)];counts=[]
    for start,stop in windows:
        value=searcher(query+f' AND metadata.publication_date:[{start}-01-01 TO {stop}-12-31]',1)['hits']['total']
        if isinstance(value,dict):
            if value.get('relation','eq')!='eq':return {'sources':sources}
            value=value['value']
        if not isinstance(value,int) or isinstance(value,bool) or value<0:return {'sources':sources}
        counts.append(value)
    return {'sources':sources,'statistics':{'terms':terms,'query':query,'periods':windows,'counts':counts,'as_of':today.isoformat(),'scope':'public_published_publications'}}


def describe(stats, language='pt'):
    if not stats or sum(stats['counts'])<10:return ''
    a,b=stats['counts'];pa,pb=stats['periods'];en=language=='en'
    if en:
        change='more' if b>a else 'fewer' if b<a else 'the same number of'
        return f"In Argiloteca’s public collection, the topic has {a} publications in {pa[0]}–{pa[1]} and {b} in {pb[0]}–{pb[1]}. The more recent complete period contains {change} publications for this search (queried on {stats['as_of']})."
    change='mais publicações' if b>a else 'menos publicações' if b<a else 'o mesmo número de publicações'
    return f"No acervo público da Argiloteca, o tema aparece em {a} publicações de {pa[0]}–{pa[1]} e em {b} de {pb[0]}–{pb[1]}. O período completo mais recente tem {change} para essa busca (consulta em {stats['as_of']})."
