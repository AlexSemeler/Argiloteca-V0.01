"""Deterministic routing through real MCP tools. No autonomous tool loops."""
import re
import os
import time
from .corpus import fold, words
from .engine import REFUSAL
from .public_metadata import field_requests


def query(payload, bridge):
    started = time.monotonic()
    if not isinstance(payload, dict) or set(payload) - {"question", "context"}: raise ValueError("Payload inválido.")
    question = payload.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000: raise ValueError("Pergunta inválida.")
    context = payload.get("context", {})
    if not isinstance(context, dict) or len(str(context)) > 4000: raise ValueError("Contexto inválido.")
    language = context.get("language", "pt")
    if language not in {"pt", "en"}: raise ValueError("Idioma inválido.")
    ids = context.get("record_ids", [])
    if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", i) for i in ids):
        raise ValueError("Registro inválido.")
    if not ids:
        selection = context.get("selection", [])
        if not isinstance(selection, list) or len(selection) > 6 or any(not isinstance(row, dict) for row in selection):
            raise ValueError("Seleção inválida.")
        selected_ids = list(dict.fromkeys(row.get("record_id") for row in selection if row.get("record_id") and not row.get("temporary")))
        if len(selected_ids) == 1 and isinstance(selected_ids[0], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", selected_ids[0]): ids = selected_ids
    normalized = fold(question); tool = "search_evidence"
    overview_words=set('a o e de do da deste desse este esse esta essa desta dessa um uma por favor me explique explicar resuma resumir resumo apresente apresentar descreva descrever qual que tema titulo conteudo assunto registro pacote trabalho estudo em portugues linguagem simples forma didatica com acessivel publicado publicacao data the this that record explain summarize summarise title topic'.split())
    record_overview = not (set(words(question)) - overview_words)
    arguments = {"question": question.strip(), "top_k": 3}
    deictic = bool(re.search(r"\b((este|esse|deste|desse) (registro|mineral|painel|pacote)|(esta|essa) (pagina|secao|curva|amostra|selecao)|this (page|record|mineral|sample|selection)|selected (curve|sample))\b", normalized))
    help_question = bool(re.search(r"\b(como usar (?:esta|este|o painel)|o que posso fazer aqui|ajuda (?:da|nesta)|how to use (?:this|the panel)|what can i do here|help with this|como comparar (?:difratogramas|curvas|amostras))\b", normalized))
    if help_question or (deictic and not ids and not context.get("term_id")):
        tool = "get_section_guide"; arguments = {"section": context.get("section", "repository"), "language": language}
    elif deictic and ids and record_overview and re.search(r"\b(explique|resuma|resumo|apresente|tema|titulo|conteudo|assunto|descreva|explain|summari[sz]e)\b",normalized):
        tool = "get_public_record"; arguments = {"record_id": ids[0]}
    elif deictic and context.get("term_id"):
        term = context["term_id"]
        if not isinstance(term, str) or not re.fullmatch(r"[a-z0-9_-]{1,100}", term): raise ValueError("Termo inválido.")
        arguments["question"] = re.sub(r"\b(?:este|esse|deste|desse|this) mineral\b",term,question.strip(),flags=re.I)
    if len(ids)==1 and field_requests(question):
        tool='get_public_record';arguments={'record_id':ids[0]}
    if tool == 'search_evidence' and re.search(r'\b(o que e|what is|onde ocorre|onde ocorrem|explique|defina|diferenca|compare|especie|serie|pertence|nome (?:em )?ingles|nome preferido|identificador (?:do|da)|qual[^?]{0,40}(?:familia|categoria|grupo|formula|estrutura|composicao|ocorrencia|dureza|densidade|propriedades|caracteristicas))\b',normalized) and not re.search(r'\b(registro|amostra)\b',normalized):
        tool = 'lookup_vocabulary';arguments = {'term':arguments['question']}
    # Production can federate the existing DRX service without replacing it.
    # Mineral definitions remain in the authorized vocabulary/PDF corpus.
    drx_question = bool(re.search(r"\b(drx|xrd|difrat\w*|picos?|peaks?|bragg|interplanares?|interplanar|espacamento(?:s)?|d.spacing|reflexoes|reflexao|angstrom|preparacao glicolada|ngc|am[-_. ]?\d+[\w.-]*|cf[-_. ]?\d+[\w.-]*|cs[-_. ]?\d+[\w.-]*)\b", normalized))
    if tool in {"search_evidence", "lookup_vocabulary"} and drx_question and os.getenv("ARGILOCLAY_LEGACY_URL"):
        tool = "search_drx"
        arguments={"question":question.strip(),"top_k":3}
        if len(ids) == 1: arguments["record_id"] = ids[0]
    if tool == "search_evidence" and len(ids)==1: arguments["record_id"]=ids[0]
    result = bridge.call(tool, arguments)
    result.setdefault("schema_version", "1.0"); result.setdefault("available", True)
    result.setdefault("sources", []); result.setdefault("answer", REFUSAL)
    result.setdefault("model", "extractive-index"); result.setdefault("generation_mode", "extractive")
    result.setdefault("limitations", []); result.setdefault("context_filters", {})
    result.update(tools_used=[tool], transport="mcp_stdio", language=language,
                  elapsed_ms=round((time.monotonic()-started)*1000, 2))
    if context.get("selection"):
        result["limitations"].append("Browser selection is session context, not validated mineral identification." if language == "en" else
                                     "A seleção do navegador é contexto de sessão, não identificação mineralógica validada.")
    if language == "en":
        result["limitations"] = ["Documentary evidence only; it does not confirm mineral identification.",
            "Source excerpts keep their original language. Check the original PDF for formulas, symbols and numerical values.",
            "The page and selected items provide session context, not a new scientific analysis."]
    return result
