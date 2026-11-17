"""Bounded HTTP federation with the preserved DRX service; never writes its indices."""
import json
import os
import re
from contextlib import closing
from urllib.request import Request, urlopen
from .engine import connect, STOP, REFUSAL
from .corpus import words, fold


def search(question, record_id="", top_k=3, opener=urlopen):
    base = os.environ.get("ARGILOCLAY_LEGACY_URL", "")
    if base not in {"http://127.0.0.1:7860", "http://localhost:7860", "http://drx:7860", "http://argiloclay-drx-hml:7860"}:
        raise ValueError("Serviço DRX legado não configurado no loopback.")
    # Curated terminology equivalents, applied to retrieval and its relevance
    # check alike. Sources remain the original, cited DRX excerpts.
    question=fold(question)
    for pattern,term in [(r'\b(?:equacao|relacao|law) (?:de )?bragg\b','lei de bragg'),
                         (r'\b(?:distancia|espacamento) interplanar\b','d-spacing'),
                         (r'\bdiffr(?:action|actogram)\b','difratograma')]:
        question=re.sub(pattern,term,question)
    filters = {"record_id": record_id} if record_id else {}
    request = Request(base + "/api/v1/drx/query", data=json.dumps({"question": question, "filters": filters, "top_k": min(max(top_k, 1), 3)}).encode(), headers={"Content-Type": "application/json"})
    with opener(request, timeout=2) as response:
        raw = response.read(100001)
    if len(raw) > 100000: raise ValueError("Resposta DRX acima do limite.")
    result = json.loads(raw)
    if not isinstance(result, dict) or result.get("schema_version") != "1.0" or not isinstance(result.get("sources"), list) or len(result["sources"]) > 3:
        raise ValueError("Resposta DRX inválida.")
    # Legacy RAW responses place exact indexed text in numbered answer blocks.
    # Accept only a complete, ordered marker sequence matching its source list.
    sources = result["sources"]
    if sources and all(s.get("tipo_fonte") == "drx_raw" for s in sources):
        blocks = re.split(r"\n\n(?=\[Fonte \d+\] )", result.get("answer", ""))[1:]
        if len(blocks) != len(sources): raise ValueError("Citações DRX inconsistentes.")
        for i, (source, block) in enumerate(zip(sources, blocks), 1):
            prefix = f"[Fonte {i}] {source.get('filename')}\nTrecho do índice: "
            if not block.startswith(prefix): raise ValueError("Citação DRX inconsistente.")
            source.update(title=source["filename"], excerpt=block[len(prefix):][:6000], corpus_origin="preserved_drx_service")
    tokens = {t for t in words(question) if len(t) > 1 and t not in STOP}
    accepted = []
    for source in sources:
        if not isinstance(source.get("excerpt"), str): raise ValueError("Trecho DRX ausente.")
        source.setdefault("title", source.get("filename", source.get("document_id", "Fonte DRX")))
        bag = set(words(source["title"] + " " + source["excerpt"]))
        if not tokens or len(tokens & bag) / len(tokens) < 0.55:
            continue
        source["corpus_origin"] = "preserved_drx_service"
        if source.get("record_id"):
            # Associate the immutable DRX document with public metadata snapshot
            # freshness. The Invenio gateway still rechecks current visibility.
            with closing(connect(os.environ["ARGILOCLAY_INDEX"])) as conn:
                row = conn.execute("SELECT json_extract(metadata,'$.updated') FROM docs WHERE json_extract(metadata,'$.record_id')=? AND json_extract(metadata,'$.access')='public' LIMIT 1", (source["record_id"],)).fetchone()
            source["updated"] = row[0] if row else None
        accepted.append(source)
    result["sources"] = accepted
    result["answer"] = "\n\n".join(f"[Fonte {i}] {s['title']}\n{s['excerpt']}" for i, s in enumerate(accepted, 1)) if accepted else REFUSAL
    result.setdefault("limitations", []).append("Corpus DRX preservado, consultado por HTTP; evidência documental não confirma identificação mineralógica.")
    return result
