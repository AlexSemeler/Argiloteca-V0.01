import re
from flask import jsonify, request

from ..services.rag_client import (
    RagInvalidResponseError, RagUnavailableError, RagUpstreamError, RagValidationError,
    UNAVAILABLE_MESSAGE,
)


def _error(exc):
    if isinstance(exc, RagValidationError):
        return jsonify({"error": str(exc)}), 400
    if isinstance(exc, RagUnavailableError):
        return jsonify({"available": False, "error": UNAVAILABLE_MESSAGE}), 503
    if isinstance(exc, RagInvalidResponseError):
        return jsonify(exc.payload), 502
    if isinstance(exc, RagUpstreamError):
        return jsonify(exc.payload), exc.status
    return jsonify({"error": "Falha inesperada ao consultar o serviço RAG."}), 502


def register_rag_routes(blueprint, deps):
    @blueprint.route("/argiloteca/drx/rag/status", endpoint="api_drx_rag_status")
    def api_drx_rag_status():
        try:
            return jsonify(deps.rag_client_factory().status())
        except Exception as exc:
            return _error(exc)

    @blueprint.route("/argiloteca/drx/rag/query", methods=["POST"], endpoint="api_drx_rag_query")
    def api_drx_rag_query():
        payload = request.get_json(silent=True) or {}
        try:
            from ...argiloclay.presentation import fold
            question=str(payload.get('question') or '').strip()
            if not question or len(question)>2000:raise RagValidationError('Pergunta vazia ou acima de 2000 caracteres.')
            if not payload.get('filters') and re.search(r'\b(o que|what is|what are|defina|definicao|explique|formula|estrutura|ocorrencia|onde ocorre|ficha|catalogo)\b',fold(question)):
                from ...argiloclay.service import ChatClient, query as chat_query, revalidate_response, Unavailable
                from ..services.rag_client import _bounded_top_k
                limit=_bounded_top_k(payload.get('top_k') or 5)
                try:result=chat_query({'question':question,'context':{'path':'/drx/comparacao','language':'pt'}},ChatClient())
                except Unavailable:raise RagUnavailableError(UNAVAILABLE_MESSAGE)
                result['sources']=result['sources'][:limit]
                result=revalidate_response(result,question=question)
                result['context_filters']={}
                return jsonify(result)
            result = deps.rag_client_factory().query(
                payload.get("question"), filters=payload.get("filters"), top_k=payload.get("top_k") or 5,
            )
            if any(isinstance(source, dict) and source.get("tipo_fonte") == "registro_invenio"
                   for source in result.get("sources", [])):
                from ...argiloclay.service import revalidate_response
                result = revalidate_response(result)
                from ...argiloclay.presentation import didactic_answer
                readable=didactic_answer(payload.get('question'),result.get('sources',[]))
                if readable:result.update(answer=readable,response_kind='grounded_metadata',generation_mode='metadata_template')
            return jsonify(result)
        except Exception as exc:
            return _error(exc)
