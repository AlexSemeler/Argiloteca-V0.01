"""Offline builder: explicitly authorized inputs, page provenance, atomic index."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath


def fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value).lower()) if not unicodedata.combining(c))


def words(value):
    return re.findall(r"[a-z0-9_]+", fold(value))


def chunks(text, width=1000, overlap=100):
    # Never cross a PDF page. Preserve extracted characters, including suspicious ones.
    text = re.sub(r"[ \t]+", " ", text).strip()
    start = 0
    while start < len(text):
        end = min(start + width, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + width // 2, end)
            if boundary > start:
                end = boundary
        yield text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)


def build(destination, vocab_dir, pdf_zip=None, records=None, *, rights_note=None):
    if pdf_zip and not rights_note:
        raise ValueError("PDF exige registro explícito de autorização (--rights-note).")
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_suffix(".building.sqlite3")
    if staging.exists():
        staging.unlink()
    conn = sqlite3.connect(staging)
    conn.executescript("""
    CREATE TABLE docs(id TEXT PRIMARY KEY,title TEXT,text TEXT,metadata TEXT);
    CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,title,text, tokenize='unicode61 remove_diacritics 2');
    CREATE TABLE aliases(alias TEXT,canonical TEXT,PRIMARY KEY(alias,canonical));
    CREATE TABLE manifest(key TEXT PRIMARY KEY,value TEXT);
    """)
    counts = {}; sources = []; aliases = {}; vocab_rows = {}; preferred_labels = {}

    def add(identifier, title, text, meta):
        conn.execute("INSERT INTO docs VALUES(?,?,?,?)", (identifier, title, text, json.dumps(meta, ensure_ascii=False)))
        conn.execute("INSERT INTO search VALUES(?,?,?)", (identifier, title, text))
        kind = meta["tipo_fonte"]; counts[kind] = counts.get(kind, 0) + 1

    try:
        for name in ("argilominerais", "grupo_mineralogico"):
            path = Path(vocab_dir) / (name + ".jsonl"); raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest(); sources.append({"file": path.name, "sha256": digest})
            ids = set()
            vocab_rows[name] = []
            for line in raw.decode().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line); identifier = row["id"]
                if identifier in ids:
                    raise ValueError("ID duplicado no vocabulário: " + identifier)
                ids.add(identifier)
                vocab_rows[name].append(row)
                names = row.get("title", {}); props = row.get("props", {})
                label = names.get("pt") or names.get("en") or identifier
                preferred_labels[identifier] = label
                text = f"Nome preferido: {label}. ID: {identifier}. Nome em inglês: {names.get('en', '')}."
                for key, caption in (("category", "Categoria"), ("family", "Família"), ("broader", "Termo mais amplo"), ("source", "Fonte declarada"), ("status", "Status")):
                    if props.get(key):
                        text += f" {caption}: {props[key]}."
                meta = {"tipo_fonte": "vocabulario", "vocabulary": name, "term_id": identifier,
                        "sha256": digest, "source_relative_path": "vocabularies/" + path.name,
                        "category": props.get("category"), "family": props.get("family"), "record_id": None}
                add("vocab:" + name + ":" + identifier, label, text, meta)
                for alias in [identifier, *names.values()]:
                    normalized = " ".join(words(alias))
                    aliases.setdefault(normalized, set()).add(identifier)
                    conn.execute("INSERT OR IGNORE INTO aliases VALUES(?,?)", (normalized, identifier))
        terms = vocab_rows["argilominerais"]; groups = vocab_rows["grupo_mineralogico"]
        overview = (f"Na Argiloteca, o vocabulário argilominerais contém {len(terms)} termos com nomes preferidos em português e inglês. "
                    "Ele distingue categorias como espécies, grupos, interestratificados e materiais; nem todo termo representa uma espécie mineral. "
                    f"O vocabulário grupo_mineralogico contém {len(groups)} entradas: " +
                    "; ".join(r["title"].get("pt", r["id"]) for r in groups) + ". "
                    "Esta é uma descrição da organização dos vocabulários fornecidos, não uma definição mineralógica universal. "
                    "Para propriedades e ocorrência de uma espécie, consulte sua ficha PDF e sua proveniência.")
        overview_hash = hashlib.sha256(overview.encode()).hexdigest()
        add("vocab:overview:argilominerais", "Argilominerais na Argiloteca: organização dos vocabulários", overview,
            {"tipo_fonte": "vocabulario", "term_id": "argilominerais", "sha256": overview_hash,
             "source_relative_path": "vocabularies/overview", "references": sources.copy(), "record_id": None,
             "derivation": "deterministic_vocabulary_overview"})
        conn.execute("INSERT OR IGNORE INTO aliases VALUES('argilominerais','argilominerais')")
        if pdf_zip:
            from pypdf import PdfReader
            with zipfile.ZipFile(pdf_zip) as archive:
                for entry in archive.infolist():
                    name = entry.filename; path = PurePosixPath(name)
                    if not name.lower().endswith(".pdf") or name.startswith("__MACOSX/"):
                        continue
                    if path.is_absolute() or ".." in path.parts or entry.file_size > 20_000_000:
                        raise ValueError("Entrada ZIP inválida ou grande demais.")
                    raw = archive.read(entry); digest = hashlib.sha256(raw).hexdigest()
                    sources.append({"file": name, "sha256": digest})
                    canonical = sorted(aliases.get(" ".join(words(path.stem)), {path.stem}))
                    for page, content in enumerate(PdfReader(BytesIO(raw)).pages, 1):
                        text = content.extract_text() or ""
                        if len(text.strip()) < 100:
                            raise ValueError("Página sem texto legível: " + name)
                        for n, excerpt in enumerate(chunks(text)):
                            meta = {"tipo_fonte": "literatura_pdf", "source_relative_path": name, "filename": path.name,
                                    "page": page, "sha256": digest, "term_ids": canonical, "record_id": None,
                                    "chunk_index": n, "contains_header": page == 1 and n == 0,
                                    "rights": rights_note, "numeric_validation": "pending_visual_review",
                                    "extraction_warning": "Símbolos, fórmulas e tabelas exigem conferência no PDF."}
                            add(f"pdf:{digest}:p{page}:c{n}", preferred_labels.get(canonical[0], path.stem), excerpt, meta)
        if records:
            seen = set()
            for line in Path(records).read_text().splitlines():
                row = json.loads(line)
                if row.get("access") != "public" or row.get("source_type") != "registro_invenio":
                    raise ValueError("Snapshot contém registro sem proveniência pública.")
                rid = row["record_id"]
                if rid in seen:
                    raise ValueError("Registro duplicado no snapshot.")
                seen.add(rid)
                for n, excerpt in enumerate(chunks(row["text"])):
                    meta = {"tipo_fonte": "registro_invenio", "record_id": rid, "updated": row.get("updated"),
                            "url": row.get("url"), "sha256": row["sha256"], "source_relative_path": "records/" + rid + ".json",
                            "access": "public", "snapshot": True}
                    add(f"record:{rid}:c{n}", row["title"], excerpt, meta)
        manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "counts": counts,
                    "sources": sources, "rights_note": rights_note, "retrieval": "fts5_bm25_bilingual_aliases"}
        conn.execute("INSERT INTO manifest VALUES('corpus',?)", (json.dumps(manifest, ensure_ascii=False),))
        conn.commit(); conn.close(); os.replace(staging, destination)
        return manifest
    except BaseException:
        conn.close(); staging.unlink(missing_ok=True); raise


def main():
    p = argparse.ArgumentParser(); p.add_argument("--index", default="storage/knowledge.sqlite3")
    p.add_argument("--vocab-dir", default="data/vocabularies"); p.add_argument("--pdf-zip")
    p.add_argument("--records"); p.add_argument("--rights-note")
    args = p.parse_args()
    print(json.dumps(build(args.index, args.vocab_dir, args.pdf_zip, args.records, rights_note=args.rights_note), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
