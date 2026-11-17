#!/usr/bin/env python3
"""Validate/compile the instance catalogs and its plain-JavaScript messages."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import re

from babel.messages.extract import extract
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po


def ui_messages(root):
    """Extract actual marked messages; never scan data, vendor code or snapshots."""
    messages = set()
    folders = [root / "templates", root / "argiloteca_custom/argiloteca/templates"]
    for folder in folders:
        for path in folder.rglob("*.html"):
            source = path.read_bytes()
            for _, message, _, _ in extract("jinja2", BytesIO(source)):
                if message:
                    messages.add(message[0] if isinstance(message, tuple) else message)
            for script in re.findall(rb"<script\b[^>]*>(.*?)</script\s*>", source, re.S | re.I):
                script = re.sub(rb"{{.*?}}|{%.*?%}", b"JINJA_EXPRESSION", script, flags=re.S)
                for _, message, _, _ in extract("javascript", BytesIO(script), keywords={"argiloT": None}):
                    if message:
                        messages.add(message)
    for path in (root / "argiloteca_custom/argiloteca/static/js").glob("*.js"):
        for _, message, _, _ in extract("javascript", BytesIO(path.read_bytes()), keywords={"argiloT": None}):
            if message:
                messages.add(message)
    return messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["check", "compile"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalogs-only", action="store_true", help="Do not check source coverage or generate static JS")
    args = parser.parse_args()
    expected = set() if args.catalogs_only else ui_messages(args.root)
    jinja_messages = set()
    if not args.catalogs_only:
        for folder in [args.root / "templates", args.root / "argiloteca_custom/argiloteca/templates"]:
            for path in folder.rglob("*.html"):
                for _, value, _, _ in extract("jinja2", BytesIO(path.read_bytes())):
                    if isinstance(value, str):
                        jinja_messages.add(value)
    # Configured site title is also translated by native templates.
    if not args.catalogs_only:
        expected.add("Banco de Dados de Pesquisa sobre Argilas e Argilominerais")
    errors = []
    counts = {}
    for locale in ["en", "pt"]:
        path = args.root / "translations" / locale / "LC_MESSAGES/messages.po"
        with path.open(encoding="utf-8") as source:
            catalog = read_po(source, locale=locale)
        available = set()
        for message in catalog:
            if not message.id:
                continue
            key = message.id[0] if isinstance(message.id, tuple) else message.id
            available.add(key)
            if message.fuzzy or not message.string or (isinstance(message.string, tuple) and not all(message.string)):
                errors.append(f"{locale}: empty/fuzzy message: {key!r}")
            # "10% de N" is a literal scientific percentage, not Python's "% d".
            if re.search(r"\d% (?:de|do|da)\b", key):
                message.flags.discard("python-format")
            for problem in message.check(catalog):
                errors.append(f"{locale}: {key!r}: {problem}")
            if "▁" in str(message.string):
                errors.append(f"{locale}: tokenizer marker in translation: {key!r}")
            if key in jinja_messages and "%" in key and "%(" not in key:
                try:
                    message.string % {}
                except (ValueError, TypeError):
                    errors.append(f"{locale}: literal Jinja percentage must be escaped as %%: {key!r}")
            # Custom JS placeholders must remain available after translation.
            if isinstance(message.id, str) and isinstance(message.string, str):
                for placeholder in re.findall(r"\{\d+\}", message.id):
                    if placeholder not in message.string:
                        errors.append(f"{locale}: missing {placeholder}: {key!r}")
        for missing in sorted(expected - available):
            errors.append(f"{locale}: source message missing from catalog: {missing!r}")
        counts[locale] = len(catalog)
        if args.mode == "compile" and not errors:
            with path.with_suffix(".mo").open("wb") as target:
                write_mo(target, catalog)
            if not args.catalogs_only:
                messages = {m.id: m.string for m in catalog if m.id and isinstance(m.id, str)}
                output = args.root / "argiloteca_custom/argiloteca/static/i18n" / f"{locale}.js"
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("window.ArgilotecaMessages = " + json.dumps(messages, ensure_ascii=False, sort_keys=True) + ";\n")
    if errors:
        for error in errors:
            print(error)
        return 1
    print(json.dumps({"catalogs": counts, "marked_ui_messages": len(expected), "status": "ok"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
