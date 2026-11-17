#!/usr/bin/env python3
"""Overlay instance React translations into generated assets, not dependencies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile


def detach_path(path, root):
    """Materialize linked generated folders before writing an override."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            source = current.resolve()
            with tempfile.TemporaryDirectory(dir=root) as staging:
                copied = Path(staging) / "copy"
                if source.is_dir():
                    shutil.copytree(source, copied, symlinks=False)
                else:
                    shutil.copy2(source, copied)
                current.unlink()
                shutil.move(str(copied), current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("assets", type=Path)
    args = parser.parse_args()
    for source in sorted(args.source.glob("*.json")):
        package, locale = source.stem.rsplit(".", 1)
        if locale not in {"en", "pt"}:
            continue
        messages = args.assets / "translations" / package / "messages"
        if not messages.is_dir():
            raise RuntimeError(f"Generated translation assets missing for {package}: {messages}")
        detach_path(messages, args.assets)
        target = messages / locale / "translations.json"
        target.parent.mkdir(exist_ok=True)
        detach_path(target, args.assets)
        overrides = json.loads(source.read_text())
        if not overrides or not all(isinstance(value, str) and value for value in overrides.values()):
            raise RuntimeError(f"Empty frontend translations in {source}")
        translations = json.loads(target.read_text()) if target.exists() else {}
        translations.update(overrides)
        target.write_text(json.dumps(translations, ensure_ascii=False, indent=2) + "\n")
        # Only enabled locales; English terminology is overridden alongside Portuguese.
        generated = messages / "_generatedTranslations.js"
        detach_path(generated, args.assets)
        generated.write_text('import EN from "./en/translations.json";\nimport PT from "./pt/translations.json";\nexport const translations = {en: {translation: EN}, pt: {translation: PT}};\n')
        print(f"{package}: {len(translations)} {locale} React messages")


if __name__ == "__main__":
    main()
