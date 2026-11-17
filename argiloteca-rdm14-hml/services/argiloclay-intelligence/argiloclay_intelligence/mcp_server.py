"""Local stdio MCP. Tool annotations are hints; read-only behavior is enforced here."""
import os
import json
import re
import hashlib
from contextlib import closing
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from .engine import from_env, retrieve, connect
from .invenio import Invenio

mcp = FastMCP("ArgiloClay evidence tools")
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)


@mcp.tool(annotations=READ)
def search_evidence(question: str, record_id: str = "", top_k: int = 3) -> dict:
    """Retrieve cited evidence from the authorized local corpus. No writes."""
    return from_env().query(question, {"record_id": record_id} if record_id else {}, top_k)


@mcp.tool(annotations=READ)
def search_drx(question: str, record_id: str = "", top_k: int = 3) -> dict:
    """Read evidence from the existing DRX corpus through its unchanged HTTP API."""
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000: raise ValueError("Pergunta inválida.")
    if record_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record_id): raise ValueError("ID inválido.")
    # Curated method literature can answer general DRX questions. A selected
    # record/sample keeps the existing scientific service as its authority.
    if not record_id and not re.search(r'\b(?:am|cf|cs)[-_. ]?\d+',question,re.I):
        local=from_env().query(question,{'tipo_fonte':'literatura_pdf'},top_k)
        if local['sources']:return local
    from .legacy import search
    return search(question.strip(), record_id, top_k)


@mcp.tool(annotations=READ)
def lookup_vocabulary(term: str) -> dict:
    """Read native catalog definitions/properties or controlled PT/EN vocabulary labels."""
    engine = from_env()
    from .taxonomy import vocabulary_sources
    from .mineral_catalog import catalog_sources
    catalog=catalog_sources(engine.index,term)
    vocabulary=vocabulary_sources(engine.index, term)
    if vocabulary:
        return {"sources":catalog or vocabulary,"limitations":["Classificação documental; não confirma a identificação de uma amostra."]}
    literature=engine.query(term,{'tipo_fonte':'literatura_pdf'},3)
    if literature['sources']:return literature
    return {"sources":catalog,
            "limitations": ["Esta resposta descreve a classificação do vocabulário; não confirma a identificação de uma amostra."]}


@mcp.tool(annotations=READ)
def get_public_record(record_id: str) -> dict:
    """Read a public record. Snapshot sources must be revalidated by the Invenio gateway."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", record_id): raise ValueError("ID inválido.")
    base = os.getenv("ARGILOCLAY_INVENIO_URL")
    if not base:
        with closing(connect(from_env().index)) as conn:
            rows = conn.execute("SELECT * FROM docs WHERE json_extract(metadata,'$.record_id')=? AND json_extract(metadata,'$.access')='public' ORDER BY id LIMIT 3", (record_id,)).fetchall()
        return {"sources": [{"document_id": r["id"], "title": r["title"], "excerpt": r["text"], **json.loads(r["metadata"])} for r in rows],
                "limitations": ["Snapshot de metadados; a visibilidade e a atualização são verificadas novamente no Invenio."]}
    row = Invenio(base).record(record_id)
    return {"sources": [{"document_id": "live:" + record_id, "title": row["title"], "excerpt": row["text"][:3000],
        "tipo_fonte": "registro_invenio", "record_id": record_id, "updated": row["updated"], "sha256": row["sha256"]}]}


@mcp.tool(annotations=READ)
def get_section_guide(section: str, language: str = "pt") -> dict:
    """Read documented page capabilities; never process curves or mutate records."""
    if language not in {"pt", "en"}: raise ValueError("Idioma inválido.")
    path = Path(__file__).resolve().parents[1] / "data/section_guides.json"
    guides = json.loads(path.read_text())
    if len(section) > 32 or section not in guides: raise ValueError("Seção inválida.")
    guide = guides.get(section, guides["repository"])
    return {"sources": [{"document_id": "guide:" + section, "title": guide["title"][language],
                         "excerpt": guide["text"][language], "tipo_fonte": "documentacao_tecnica",
                         "source_relative_path": "data/section_guides.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "derivation": guide["derivation"], "references": [{"source_relative_path": guide["source_relative_path"], "sha256": guide["sha256"]}]}],
            "limitations": ["Guia de uso da interface; não analisa amostras nem confirma identificação mineralógica."]}


@mcp.tool(annotations=READ)
def corpus_status() -> dict:
    """Return corpus age, coverage and limitations for freshness checks."""
    return from_env().status()


if __name__ == "__main__":
    mcp.run(transport="stdio")
