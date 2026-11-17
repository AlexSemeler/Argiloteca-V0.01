"""Invenio identity boundary, short HTTP client and current source verification."""
import re
import json
import os
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen
from .context import validate_context, RID
from .presentation import record_source, didactic_answer, catalog_source


class Unavailable(Exception):
    pass


class PublicContextUnavailable(ValueError):
    """No assertion that a private/deleted identifier actually exists."""


class ChatClient:
    def __init__(self, opener=urlopen):
        self.base = os.getenv("ARGILOCLAY_URL", "http://127.0.0.1:7861").rstrip("/")
        self.opener = opener

    def call(self, path, payload=None, method=None):
        req = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={"Content-Type": "application/json", "Accept": "application/json"},method=method)
        try:
            with self.opener(req, timeout=7) as response:
                raw = response.read(100_001)
            if len(raw) > 100_000: raise ValueError("Resposta acima do limite.")
            data = json.loads(raw)
            if not isinstance(data, dict): raise ValueError("Resposta inválida.")
            return data
        except (URLError, OSError, ValueError) as exc:
            raise Unavailable("Assistente indisponível; as seções da Argiloteca continuam operacionais.") from exc


def public_record(record_id):
    """No system identity. Restricted records are excluded even for their owner."""
    from flask import g
    from invenio_rdm_records.proxies import current_rdm_records_service
    from invenio_records_resources.services.errors import PermissionDeniedError, RecordPermissionDeniedError
    from invenio_pidstore.errors import PIDDoesNotExistError, PIDDeletedError, PIDUnregistered
    from invenio_rdm_records.services.errors import RecordDeletedException
    from sqlalchemy.orm.exc import NoResultFound
    try:
        result = current_rdm_records_service.read(g.identity, record_id).to_dict()
        if result.get("access", {}).get("record") != "public" or result.get("is_draft") is True or result.get("is_published") is False or result.get("deletion_status", {}).get("is_deleted") is True:
            return None
        return result
    except (PermissionDeniedError, RecordPermissionDeniedError, PIDDoesNotExistError, PIDDeletedError,
            PIDUnregistered, RecordDeletedException, NoResultFound):
        return None
    except Exception as exc:
        raise Unavailable("Os metadados estão temporariamente indisponíveis. Tente novamente.") from exc


def verify_records(payload, resolver=public_record):
    rows = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > 12: raise ValueError("Lote de verificação inválido.")
    verified = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("record_id"), str) or not RID.fullmatch(row["record_id"]) or not isinstance(row.get("updated"), str) or len(row["updated"]) > 100:
            raise ValueError("Referência inválida.")
        current = resolver(row["record_id"])
        if current and current.get("updated") == row["updated"]:
            verified.append(row)
    library_rows=payload.get('library_sources',[]) if isinstance(payload,dict) else []
    if not isinstance(library_rows,list) or len(library_rows)>12:raise ValueError('Lote de fontes inválido.')
    library_verified=[]
    if library_rows:
        from .admin import library
        lib=library()
        for source in library_rows:
            if not isinstance(source,dict):raise ValueError('Fonte inválida.')
            if lib.source_allowed(source,check_excerpt=False):library_verified.append(source.get('document_id'))
    from .community_sources import verify as verify_community
    community_rows=payload.get('community_sources',[])
    if not isinstance(community_rows,list) or len(community_rows)>12:raise ValueError('Lote de comunidades inválido.')
    community_verified=[]
    for source in community_rows:
        if not isinstance(source,dict):raise ValueError('Comunidade inválida.')
        if verify_community(source,excerpt=False):community_verified.append(source['document_id'])
    return {"verified": verified,'library_verified':library_verified,'community_verified':community_verified}


def community_question_language(question):
    from .presentation import fold
    q=fold(question).strip()
    if re.search(r'\b(em ingles|in english)\b',q):return 'en'
    if re.search(r'\b(em portugues|in portuguese)\b',q):return 'pt'
    if re.match(r'^(o que|quais|qual|como|por que|explique|descreva|voce|resuma)\b',q):return 'pt'
    if re.match(r'^(what|which|how|why|explain|describe|do you|summari[sz]e)\b',q):return 'en'
    return None


def query(payload, client, resolver=public_record):
    if not isinstance(payload, dict) or set(payload) - {"question", "context"}: raise ValueError("Envie question e context.")
    question = payload.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000: raise ValueError("Pergunta vazia ou acima de 2000 caracteres.")
    context = validate_context(payload.get("context")); checked = {}
    # A question's explicit language wins over a stale interface preference.
    normalized=community_question_language(question)
    if normalized:context['language']=normalized
    ids = context["record_ids"] + [r["record_id"] for r in context["selection"] if r["record_id"]]
    for rid in set(ids):
        checked[rid] = resolver(rid)
        if not checked[rid]: raise PublicContextUnavailable("Este contexto não está disponível para acesso público.")
    from . import community_sources
    from . import foundations
    foundational=[];literature=[]
    if not ids or foundations.kind(question):
        from flask import has_app_context
        if has_app_context():
            from .admin import library
            from .bibliography import lookup
            try:
                if foundations.kind(question):foundational=foundations.lookup(question,library())
                else:literature=lookup(question,library())
            except Exception:
                from flask import current_app
                current_app.logger.warning('ArgiloClay public bibliography lookup unavailable')
    community=[]
    if (not ids or foundational) and not literature and community_sources.DEFINITION.search(community_sources.fold(question)):
        try:
            community=community_sources.select('O que são argilominerais?' if foundational else question,community_sources.public_sources())
            if foundational:community=[s for s in community if s.get('community_slug') in community_sources.GENERAL_SLUGS[:3]]
        except Exception:
            # This optional editorial source cannot take down the catalog/DRX.
            from flask import current_app,has_app_context
            if has_app_context():current_app.logger.warning('ArgiloClay community descriptions unavailable')
    if foundational:
        data={'schema_version':'1.0','available':True,'sources':foundational+community,'tools_used':['get_reviewed_definitions','get_public_community_about'],'limitations':[]}
    elif literature:
        data={'schema_version':'1.0','available':True,'sources':literature,'tools_used':['lookup_public_library'],'limitations':[]}
    elif community:
        data={'schema_version':'1.0','available':True,'sources':community,
              'tools_used':['get_public_community_about'],'limitations':[]}
    else:
        data = client.call("/api/v1/chat/query", {"question": question.strip(), "context": context})
    if data.get("schema_version") != "1.0" or not isinstance(data.get("sources"), list) or len(data["sources"]) > 12:
        raise Unavailable("Resposta inválida do assistente.")
    if data.get('tools_used')==['get_public_record'] and len(checked)==1:
        rid=next(iter(checked));current=checked.get(rid)
        source=record_source(current,rid,question) if current else None
        if source:data['sources']=[source]
    data = revalidate_response(data, resolver, context["language"], checked, question=question)
    if literature and data['sources']:
        en=context['language']=='en'
        data['answer']='\n\n'.join(s['title']+' — '+s.get('authors','')+(' ('+str(s['year'])+')' if s.get('year') else '')+(' is available in Argiloteca’s reviewed library.' if en else ' está disponível na biblioteca revisada da Argiloteca.')+' ['+('Source' if en else 'Fonte')+' '+str(i)+']' for i,s in enumerate(data['sources'],1))
        data.update(generation_mode='bibliographic_lookup',response_kind='grounded_bibliography')
    if community and any(s.get('derivation')=='live_community_about' for s in data['sources']):
        from . import research_context
        try:
            research=research_context.collect(question,resolver)
            if research['sources']:
                data['sources'].extend(research['sources'])
                data=revalidate_response(data,resolver,context['language'],checked,question=question)
            statistics=research.get('statistics')
            if statistics:
                data['research_context']=statistics
                prose=research_context.describe(statistics,context['language'])
                if prose:data['answer']=community_sources.answer(data['sources'],context['language'],question,trend=prose)
            data['tools_used'].append('search_public_publications')
        except Exception:
            from flask import current_app,has_app_context
            if has_app_context():current_app.logger.warning('ArgiloClay related public publications unavailable')
    if foundational:
        prose=research_context.describe(data.get('research_context'),context['language']) if data.get('research_context') else ''
        direct=foundations.answer(data['sources'],question,context['language'],prose)
        if direct:data.update(answer=direct,generation_mode='verified_foundations',response_kind='grounded_foundations')
    if not re.search(r'\b(amostra|sample|drx|xrd|pico|peak|identific|teor|curva|curve)\w*',question.lower()):
        boilerplate=('Evidência documental auxiliar;','Busca lexical com aliases','Trechos são extraídos das fontes. Textos recuperados','Documentary evidence only;','Source excerpts keep their original language.','The page and selected items provide session context,')
        data['limitations']=[note for note in data.get('limitations',[]) if not note.startswith(boilerplate)]
    data["page_context"] = context
    return data


def revalidate_response(data, resolver=public_record, language="pt", checked=None, question=None):
    """Shared by chat and legacy RAG: a snapshot never grants current access."""
    checked = {} if checked is None else checked
    sources = []; removed = 0; seen_records=set()
    for source in data["sources"]:
        if not isinstance(source, dict) or not isinstance(source.get("excerpt"), str) or len(source["excerpt"]) > 6000:
            raise Unavailable("Fonte inválida do assistente.")
        source = dict(source)
        if source.get('community_id') or source.get('tipo_fonte')=='comunidade_invenio':
            from .community_sources import verify as verify_community
            fresh=verify_community(source)
            if not fresh:
                removed+=1
                continue
            sources.append(fresh)
            continue
        if source.get('library_id'):
            from .admin import library
            try:
                allowed = library().source_allowed(source)
            except Exception:
                allowed = False
            if not allowed:
                removed += 1
                continue
            source['url'] = '/argiloclay/library/{}/{}/{}'.format(source['library_id'],source['library_version'],source['page'])
            source['visibility_verified'] = True
        if source.get("record_id"):
            rid = source["record_id"]
            if not isinstance(rid, str) or not RID.fullmatch(rid): raise Unavailable("Fonte inválida.")
            if rid not in checked: checked[rid] = resolver(rid)
            current = checked[rid]
            if not current or not source.get("updated") or source["updated"] != current.get("updated"):
                removed += 1; continue
            if source.get('derivation') in ('indexed_mineral_catalog','live_mineral_catalog'):
                fresh=catalog_source(current,rid,question)
                if not fresh or fresh['catalog_slug']!=source.get('catalog_slug'):
                    removed+=1;continue
                source=fresh
            elif question and source.get('tipo_fonte')=='registro_invenio':
                fresh=record_source(current,rid,question)
                if fresh:source=fresh
            if rid in seen_records:continue
            seen_records.add(rid)
            source["url"] = "/records/" + rid  # Never trust a source-supplied destination.
            source["visibility_verified"] = True
        elif not source.get('library_id'):
            source.pop("url", None)
        sources.append(source)
    en = language == "en"
    refusal = "Inconclusive: there is not enough evidence in Argiloteca to answer." if en else "Não conclusivo: não há evidência suficiente na Argiloteca para responder."
    intro = "Evidence retrieved from Argiloteca. Check its relevance to your question." if en else "Evidências recuperadas da Argiloteca. Confira sua relação com a pergunta."
    paragraphs = [f"[{'Source' if en else 'Fonte'} {i}] {s.get('title', s.get('document_id', ''))}" + (f", p. {s['page']}" if s.get('page') else '') + f"\n{s['excerpt']}" for i, s in enumerate(sources, 1)]
    data.update(answer=intro + "\n\n" + "\n\n".join(paragraphs) if sources else refusal,
                sources=sources, response_kind="evidence" if sources else "insufficient_evidence")
    if any(s.get('derivation')=='live_community_about' for s in sources):
        from .community_sources import answer as community_answer
        data.update(answer=community_answer(sources,language,question or ''),response_kind='grounded_community',generation_mode='metadata_template')
    elif question is not None and not en and sources:
        readable=didactic_answer(question,sources)
        if readable:data.update(answer=readable,response_kind='grounded_metadata',generation_mode='metadata_template')
    if removed:
        data.setdefault("limitations", []).append("A fonte foi alterada, removida ou perdeu acesso público; atualize o índice." if not en else "A source changed, was removed or is no longer public; refresh the index.")
    return data
