#!/usr/bin/env python3
# =============================================================================
# Projeto...........: Argiloteca – Painel de DRX
# Módulo............: organizar_trios_drx_por_argilomineral.py
#
# Descrição.........:
# Executa tarefas operacionais de processamento, indexação, validação ou organização de dados DRX.
#
# Autor.............:
# Alexandre Ribas Semeler
# alexandre.semeler@ufrgs.br
#
# Última atualização:
# 2026-06-25
#
# =============================================================================

"""Organize classified DRX N/G/C trios by rule-based clay-mineral result.

The script reads analytical package manifests and their
``classificacao_mineralogica_ngc_groups.json`` files, then creates a new output
tree grouped by the clay mineral found for each N/G/C sample base. Original RAW
files are not modified; by default the output contains symbolic links plus JSON
metadata preserving the original folder and classification provenance.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PACKAGES_DIR = PROJECT_ROOT / "argiloteca-local" / "instance" / "argiloteca_analytical_packages"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "argiloteca-local" / "data" / "drx" / "trios_por_argilomineral"
PREPARATION_ALIASES = {
    "natural": "N",
    "air_dried": "N",
    "n": "N",
    "glicolado": "G",
    "glicolada": "G",
    "glycolated": "G",
    "g": "G",
    "calcinado": "C",
    "calcinada": "C",
    "calcined": "C",
    "c": "C",
}


def slugify(value: str, fallback: str = "sem_nome") -> str:
    """Return a stable ASCII folder name."""
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._-").lower()
    return text or fallback


def load_json(path: Path) -> dict:
    """Load a JSON object, returning an empty object when the file is absent."""
    try:
        with path.open("r", encoding="utf-8") as fp:
            payload = json.load(fp)
    except FileNotFoundError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def normalized_preparation(value: str | None) -> str:
    """Normalize preparation labels to N, G, C or I."""
    key = str(value or "").strip().lower()
    return PREPARATION_ALIASES.get(key, "I")


def complete_ngc(items: list[dict]) -> bool:
    """Return True when the item list contains natural, glycolated and calcined RAWs."""
    preps = {normalized_preparation(item.get("preparation")) for item in items}
    return {"N", "G", "C"}.issubset(preps)


def candidate_lists_for_group(group: dict, levels: set[str]) -> list[tuple[str, dict]]:
    """Collect mineral candidates from the requested confidence levels."""
    mapping = [
        ("confirmed", "confirmed_minerals"),
        ("probable", "probable_minerals"),
        ("possible", "possible_minerals"),
    ]
    rows: list[tuple[str, dict]] = []
    for level, field in mapping:
        if level not in levels:
            continue
        for candidate in group.get(field) or []:
            if not isinstance(candidate, dict):
                continue
            mineral = str(candidate.get("mineral") or "").strip()
            status = str(candidate.get("status") or candidate.get("confidence") or "").strip().lower()
            score = candidate.get("ngc_group_score", candidate.get("score"))
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                score_value = None
            if not mineral or status == "descartado" or mineral.lower().startswith("inconclusivo"):
                continue
            if score_value is not None and score_value <= 0:
                continue
            rows.append((level, candidate))
    return rows


def primary_destinations(group: dict, levels: set[str], include_uncertain: bool) -> list[tuple[str, str, dict | None]]:
    """Return output mineral folders for one classified group."""
    candidates = candidate_lists_for_group(group, levels)
    unique: list[tuple[str, str, dict]] = []
    seen = set()
    for level, candidate in candidates:
        mineral = str(candidate.get("mineral") or "").strip()
        key = slugify(mineral)
        if key in seen:
            continue
        seen.add(key)
        unique.append((key, level, candidate))
    if unique:
        return unique
    if include_uncertain:
        return [("_sem_confirmacao_por_regras", "none", None)]
    return []


def package_dirs(root: Path) -> list[Path]:
    """List package directories containing both manifest and N/G/C classification JSON."""
    dirs = []
    for manifest in sorted(root.glob("*/drx_manifest.json")):
        package = manifest.parent
        if (package / "classificacao_mineralogica_ngc_groups.json").exists():
            dirs.append(package)
    return dirs


def items_by_sample_base(manifest: dict) -> dict[str, list[dict]]:
    """Group manifest items by sample_base/sample_code."""
    grouped: dict[str, list[dict]] = {}
    for item in manifest.get("items") or []:
        if not isinstance(item, dict):
            continue
        base = str(item.get("sample_base") or item.get("sample_code") or "").strip()
        if not base:
            continue
        grouped.setdefault(base, []).append(item)
    return grouped


def link_or_copy_file(source: Path, destination: Path, copy_files: bool) -> str:
    """Create a symlink or copy for one RAW file and return the operation used."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    if copy_files:
        shutil.copy2(source, destination)
        return "copy"
    try:
        destination.symlink_to(source)
        return "symlink"
    except OSError:
        shutil.copy2(source, destination)
        return "copy_fallback"


def safe_relative_or_absolute(path: Path) -> str:
    """Return a readable path for metadata."""
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def create_origin_reference(output_dir: Path, record_id: str, package_dir: Path, raw_dirs: set[str]) -> None:
    """Create reference files and symlinks to original package/raw folders."""
    refs = output_dir / "_referencias_origem" / slugify(record_id, "registro")
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "origem.txt").write_text(
        "\n".join(
            [
                f"record_id={record_id}",
                f"package_dir={safe_relative_or_absolute(package_dir)}",
                *[f"raw_dir={raw_dir}" for raw_dir in sorted(raw_dirs)],
                "",
            ]
        ),
        encoding="utf-8",
    )
    package_link = refs / "pacote_original"
    if not package_link.exists() and not package_link.is_symlink():
        try:
            package_link.symlink_to(package_dir.resolve())
        except OSError:
            pass


def write_metadata(path: Path, payload: dict) -> None:
    """Write a deterministic JSON metadata file."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def organize(args: argparse.Namespace) -> dict:
    """Run the complete organization process."""
    packages_root = Path(args.packages_dir).expanduser().resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path(args.output_dir or (Path(args.output_root) / f"trios_argilominerais_{timestamp}"))
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    levels = {level.strip().lower() for level in args.levels.split(",") if level.strip()}
    index_rows: list[dict] = []
    packages_processed = 0
    groups_processed = 0
    groups_skipped_incomplete = 0
    groups_without_destination = 0
    files_linked = 0

    for package_dir in package_dirs(packages_root):
        packages_processed += 1
        manifest = load_json(package_dir / "drx_manifest.json")
        classification = load_json(package_dir / "classificacao_mineralogica_ngc_groups.json")
        record_id = str(classification.get("record_id") or manifest.get("record_id") or package_dir.name)
        by_base = items_by_sample_base(manifest)
        raw_dirs: set[str] = set()
        for item in manifest.get("items") or []:
            raw_path = Path(str(item.get("raw_path") or ""))
            if raw_path.parent and str(raw_path) not in {"", "."}:
                raw_dirs.add(safe_relative_or_absolute(raw_path.parent))
        create_origin_reference(output_dir, record_id, package_dir, raw_dirs)

        for group in classification.get("groups") or []:
            if not isinstance(group, dict):
                continue
            sample_id = str(group.get("sample_id") or "").strip()
            if not sample_id:
                continue
            items = by_base.get(sample_id) or []
            if not items:
                continue
            is_complete = complete_ngc(items)
            if args.only_complete and not is_complete:
                groups_skipped_incomplete += 1
                continue
            destinations = primary_destinations(group, levels, args.include_uncertain)
            if not destinations:
                groups_without_destination += 1
                continue
            groups_processed += 1

            for mineral_slug, level, candidate in destinations:
                trio_dir = output_dir / mineral_slug / slugify(record_id, "registro") / slugify(sample_id, "amostra")
                trio_dir.mkdir(parents=True, exist_ok=True)
                linked_files = []
                for item in sorted(items, key=lambda row: (normalized_preparation(row.get("preparation")), str(row.get("filename") or ""))):
                    raw_path = Path(str(item.get("raw_path") or ""))
                    if not raw_path.is_file():
                        continue
                    prep = normalized_preparation(item.get("preparation"))
                    dest_name = f"{prep}__{raw_path.name}"
                    output_file = trio_dir / dest_name
                    operation = link_or_copy_file(raw_path.resolve(), output_file, args.copy_files)
                    files_linked += 1
                    linked_files.append(
                        {
                            "operation": operation,
                            "output_file": str(output_file),
                            "original_file": safe_relative_or_absolute(raw_path),
                            "original_folder": safe_relative_or_absolute(raw_path.parent),
                            "preparation": item.get("preparation"),
                            "preparation_code": prep,
                            "sample_code": item.get("sample_code"),
                            "filename": item.get("filename"),
                        }
                    )
                metadata = {
                    "record_id": record_id,
                    "sample_id": sample_id,
                    "complete_ngc_trio": is_complete,
                    "available_treatments": group.get("available_treatments"),
                    "mineral_folder": mineral_slug,
                    "candidate_level": level,
                    "selected_candidate": candidate,
                    "classification_policy": group.get("policy") or classification.get("interpretation_policy"),
                    "classification_file": safe_relative_or_absolute(package_dir / "classificacao_mineralogica_ngc_groups.json"),
                    "manifest_file": safe_relative_or_absolute(package_dir / "drx_manifest.json"),
                    "original_package_dir": safe_relative_or_absolute(package_dir),
                    "files": linked_files,
                    "group_classification": group,
                }
                write_metadata(trio_dir / "trio_metadata.json", metadata)
                index_rows.append(
                    {
                        "record_id": record_id,
                        "sample_id": sample_id,
                        "complete_ngc_trio": is_complete,
                        "mineral_folder": mineral_slug,
                        "candidate_level": level,
                        "mineral": (candidate or {}).get("mineral") if candidate else "",
                        "policy": metadata["classification_policy"],
                        "trio_dir": str(trio_dir),
                        "files_count": len(linked_files),
                        "original_package_dir": safe_relative_or_absolute(package_dir),
                    }
                )

    index_json = output_dir / "indice_trios_por_argilomineral.json"
    index_csv = output_dir / "indice_trios_por_argilomineral.csv"
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "packages_root": safe_relative_or_absolute(packages_root),
        "output_dir": safe_relative_or_absolute(output_dir),
        "levels": sorted(levels),
        "only_complete": args.only_complete,
        "include_uncertain": args.include_uncertain,
        "copy_files": args.copy_files,
        "packages_processed": packages_processed,
        "groups_processed": groups_processed,
        "groups_skipped_incomplete": groups_skipped_incomplete,
        "groups_without_destination": groups_without_destination,
        "files_linked_or_copied": files_linked,
        "rows": index_rows,
    }
    write_metadata(index_json, summary)
    with index_csv.open("w", encoding="utf-8", newline="") as fp:
        fieldnames = [
            "record_id",
            "sample_id",
            "complete_ngc_trio",
            "mineral_folder",
            "candidate_level",
            "mineral",
            "policy",
            "trio_dir",
            "files_count",
            "original_package_dir",
        ]
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(index_rows)
    (output_dir / "README.txt").write_text(
        "\n".join(
            [
                "Trios DRX organizados por argilomineral encontrado nas regras N/G/C.",
                "Os arquivos RAW originais nao foram movidos.",
                "Por padrao, os arquivos nesta pasta sao links simbolicos para a pasta original.",
                "Cada trio contem trio_metadata.json com record_id, sample_id, candidato, politica e caminhos originais.",
                f"Indice JSON: {index_json.name}",
                f"Indice CSV: {index_csv.name}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(description="Organiza trios DRX N/G/C por argilomineral classificado.")
    parser.add_argument("--packages-dir", default=os.environ.get("ARGILOTECA_ANALYTICAL_PACKAGES_DIR", str(DEFAULT_PACKAGES_DIR)))
    parser.add_argument("--output-root", default=os.environ.get("ARGILOTECA_DRX_TRIOS_OUTPUT_ROOT", str(DEFAULT_OUTPUT_ROOT)))
    parser.add_argument("--output-dir", default=os.environ.get("ARGILOTECA_DRX_TRIOS_OUTPUT_DIR"))
    parser.add_argument("--levels", default=os.environ.get("ARGILOTECA_DRX_TRIOS_LEVELS", "confirmed,probable"))
    parser.add_argument("--include-incomplete", action="store_true", default=os.environ.get("INCLUDE_INCOMPLETE", "0") == "1")
    parser.add_argument("--include-uncertain", action="store_true", default=os.environ.get("INCLUDE_UNCERTAIN", "1") != "0")
    parser.add_argument("--copy-files", action="store_true", default=os.environ.get("COPY_FILES", "0") == "1")
    parser.add_argument("--json", action="store_true", help="Imprime o resumo completo em JSON.")
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    args.only_complete = not args.include_incomplete
    summary = organize(args)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("== Trios DRX organizados por argilomineral ==")
        print(f"Saida: {summary['output_dir']}")
        print(f"Pacotes processados: {summary['packages_processed']}")
        print(f"Trios/amostras processados: {summary['groups_processed']}")
        print(f"Trios incompletos ignorados: {summary['groups_skipped_incomplete']}")
        print(f"Sem destino mineral: {summary['groups_without_destination']}")
        print(f"Arquivos vinculados/copiados: {summary['files_linked_or_copied']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
