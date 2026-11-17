"""Bounded page hints; client context never grants record access."""
import re
from urllib.parse import urlsplit

SECTIONS = {"repository", "home", "catalog", "search", "map", "vocabulary", "mineral", "record",
            "analyses", "drx", "package", "deposit", "communities", "help", "administration", "geochemistry"}
RID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$")


def section_for(path):
    if path == "/": return "home"
    for prefix, section in (("/drx/comparacao", "drx"), ("/drx", "help"), ("/analises/", "analyses"),
        ("/records/", "record"), ("/uploads", "deposit"), ("/me/", "deposit"), ("/deposit", "deposit"),
        ("/administration", "administration"), ("/admin", "administration"), ("/search", "search"),
        ("/mapa", "map"), ("/geoquimica", "geochemistry"), ("/communities", "communities"),
        ("/catalogo", "catalog"), ("/argilominerais/", "mineral"), ("/argilominerais", "vocabulary"),
        ("/sobre", "help")):
        if path.startswith(prefix):
            if section == "analyses" and re.fullmatch(r"/analises/[^/]+/?", path): return "package"
            if section == "mineral" and path.rstrip("/") == "/argilominerais": return "vocabulary"
            return section
    return "repository"


def validate_context(value):
    if value is None: value = {}
    if not isinstance(value, dict) or set(value) - {"section", "path", "language", "record_ids", "term_id", "selection"}:
        raise ValueError("Contexto da página inválido.")
    path = value.get("path", "/")
    if not isinstance(path, str) or len(path) > 300 or not path.startswith("/") or path.startswith("//") or urlsplit(path).query or urlsplit(path).fragment or "\\" in path:
        raise ValueError("Caminho de contexto inválido.")
    language = value.get("language", "pt")
    if language not in {"pt", "en"}: raise ValueError("Idioma inválido.")
    ids = value.get("record_ids", [])
    if not isinstance(ids, list) or len(ids) > 4 or any(not isinstance(i, str) or not RID.fullmatch(i) for i in ids):
        raise ValueError("IDs de contexto inválidos.")
    section = section_for(path)  # Ignore an invented client section.
    # A launcher may supply only its source path. These are bounded hints,
    # subsequently checked under the current Invenio identity by the gateway.
    if not ids and section in {'record','package'}:
        matched=re.fullmatch(r'/(?:records|analises)/([A-Za-z0-9][A-Za-z0-9_-]{0,99})/?',path)
        if matched:ids=[matched[1]]
    term = value.get("term_id", "")
    if not term and section=='mineral':
        matched=re.fullmatch(r'/argilominerais/([a-z0-9_-]{1,100})/?',path)
        if matched:term=matched[1]
    if not isinstance(term, str) or len(term) > 100 or (term and not re.fullmatch(r"[a-z0-9_-]+", term)):
        raise ValueError("Termo de contexto inválido.")
    selection = value.get("selection", [])
    if not isinstance(selection, list) or len(selection) > 6: raise ValueError("Seleção acima do limite.")
    compact = []
    for row in selection:
        if not isinstance(row, dict) or set(row) - {"id", "record_id", "sample_code", "preparation", "temporary"}:
            raise ValueError("Seleção inválida.")
        item = {}
        for key in ("id", "record_id", "sample_code", "preparation"):
            field = row.get(key, "")
            if not isinstance(field, str) or len(field) > 120: raise ValueError("Campo de seleção inválido.")
            item[key] = field
        if item["record_id"] and not RID.fullmatch(item["record_id"]): raise ValueError("Registro de seleção inválido.")
        if not isinstance(row.get("temporary", False), bool): raise ValueError("Origem temporária inválida.")
        item["temporary"] = row.get("temporary", False); compact.append(item)
    return {"section": section, "path": path, "language": language,
            "record_ids": list(dict.fromkeys(ids)), "term_id": term, "selection": compact}
