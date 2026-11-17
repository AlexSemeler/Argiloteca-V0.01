"""Incremental indexing and processing pipeline for local DRX files."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.database.schema import connect, init_db

from .comparison_ngc import infer_preparation_from_name
from .export_results import save_curve_csv
from .mineral_identification import identify_mineral_candidates
from .parser_raw import RawParseError, parse_raw
from .preprocessing import sha256_file


LOGGER = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def collect_raw_files(input_path: str | Path) -> list[Path]:
    input_path = Path(input_path)
    if input_path.is_file():
        return [input_path] if input_path.suffix.lower() == ".raw" else []
    return sorted(
        list(input_path.glob("*.RAW"))
        + list(input_path.glob("*.raw"))
        + list(input_path.glob("*.Raw"))
    )


def index_raw_files(input_path: str | Path, db_path: str | Path) -> dict:
    """Index RAW files into SQLite without modifying the raw data."""
    init_db(db_path)
    files = collect_raw_files(input_path)
    inserted = 0
    updated = 0
    unchanged = 0
    with connect(db_path) as conn:
        for path in files:
            stat = path.stat()
            digest = sha256_file(path)
            prep = infer_preparation_from_name(path)
            existing = conn.execute(
                "SELECT id, sha256, mtime FROM raw_files WHERE raw_path = ?",
                (str(path),),
            ).fetchone()
            payload = {
                "raw_path": str(path),
                "filename": path.name,
                "sample_code": path.stem,
                "sample_base": prep["sample_base"],
                "preparation": prep["preparation"],
                "preparation_confidence": prep["confidence"],
                "preparation_evidence": prep["evidence"],
                "sha256": digest,
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
            }
            if not existing:
                conn.execute(
                    """
                    INSERT INTO raw_files (
                        raw_path, filename, sample_code, sample_base, preparation,
                        preparation_confidence, preparation_evidence, sha256,
                        size_bytes, mtime, status
                    ) VALUES (
                        :raw_path, :filename, :sample_code, :sample_base, :preparation,
                        :preparation_confidence, :preparation_evidence, :sha256,
                        :size_bytes, :mtime, 'indexed'
                    )
                    """,
                    payload,
                )
                inserted += 1
            elif existing["sha256"] != digest or float(existing["mtime"]) != float(stat.st_mtime):
                conn.execute(
                    """
                    UPDATE raw_files
                    SET filename=:filename, sample_code=:sample_code, sample_base=:sample_base,
                        preparation=:preparation, preparation_confidence=:preparation_confidence,
                        preparation_evidence=:preparation_evidence, sha256=:sha256,
                        size_bytes=:size_bytes, mtime=:mtime, status='indexed',
                        error_message=NULL, curve_path=NULL, metadata_json=NULL, processed_at=NULL
                    WHERE raw_path=:raw_path
                    """,
                    payload,
                )
                updated += 1
            else:
                unchanged += 1
        conn.commit()
    return {"files_seen": len(files), "inserted": inserted, "updated": updated, "unchanged": unchanged}


def process_pending(
    db_path: str | Path,
    output_dir: str | Path,
    limit: int = 0,
    force: bool = False,
) -> dict:
    """Process indexed RAW files, skipping already processed unchanged files."""
    init_db(db_path)
    output_dir = Path(output_dir)
    curve_dir = output_dir / "curves"
    processed = 0
    skipped = 0
    errors = 0
    with connect(db_path) as conn:
        status_clause = "" if force else "WHERE status != 'processed'"
        rows = conn.execute(
            f"SELECT * FROM raw_files {status_clause} ORDER BY filename"
        ).fetchall()
        if limit and limit > 0:
            rows = rows[:limit]

        for row in rows:
            raw_id = row["id"]
            raw_path = Path(row["raw_path"])
            if not force and row["status"] == "processed":
                skipped += 1
                continue
            try:
                curve = parse_raw(raw_path)
                identification = identify_mineral_candidates(curve.two_theta, curve.intensity)
                curve_path = curve_dir / f"{raw_id}_{raw_path.stem}.csv"
                save_curve_csv(curve_path, curve.two_theta, curve.intensity)
                conn.execute("DELETE FROM peaks WHERE raw_file_id = ?", (raw_id,))
                conn.execute("DELETE FROM mineral_candidates WHERE raw_file_id = ?", (raw_id,))
                for peak in identification["peaks"]:
                    conn.execute(
                        """
                        INSERT INTO peaks (
                            raw_file_id, two_theta, d_spacing, intensity, relative_intensity
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            raw_id,
                            peak.get("two_theta"),
                            peak.get("d"),
                            peak.get("intensity"),
                            peak.get("relative_intensity"),
                        ),
                    )
                for candidate in identification["candidates"]:
                    conn.execute(
                        """
                        INSERT INTO mineral_candidates (
                            raw_file_id, mineral, formula, mineral_group, score,
                            confidence, evidence_json, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            raw_id,
                            candidate.get("mineral"),
                            candidate.get("formula"),
                            candidate.get("group"),
                            candidate.get("score"),
                            candidate.get("confidence"),
                            json.dumps(candidate.get("matches") or [], ensure_ascii=False),
                            candidate.get("source"),
                        ),
                    )
                conn.execute(
                    """
                    UPDATE raw_files
                    SET status='processed', error_message=NULL, curve_path=?,
                        metadata_json=?, processed_at=?
                    WHERE id=?
                    """,
                    (
                        str(curve_path),
                        json.dumps(curve.metadata, ensure_ascii=False),
                        utc_now_iso(),
                        raw_id,
                    ),
                )
                processed += 1
            except (RawParseError, OSError, ValueError) as exc:
                LOGGER.exception("Falha ao processar RAW %s", raw_path)
                conn.execute(
                    "UPDATE raw_files SET status='error', error_message=? WHERE id=?",
                    (str(exc), raw_id),
                )
                errors += 1
            conn.commit()
    return {"processed": processed, "skipped": skipped, "errors": errors}


def summarize_database(db_path: str | Path) -> dict:
    init_db(db_path)
    with connect(db_path) as conn:
        raw_total = conn.execute("SELECT COUNT(*) AS count FROM raw_files").fetchone()["count"]
        samples = conn.execute("SELECT COUNT(DISTINCT sample_base) AS count FROM raw_files").fetchone()["count"]
        processed = conn.execute("SELECT COUNT(*) AS count FROM raw_files WHERE status='processed'").fetchone()["count"]
        errors = conn.execute("SELECT COUNT(*) AS count FROM raw_files WHERE status='error'").fetchone()["count"]
        pending = raw_total - processed - errors
        mineral_rows = conn.execute(
            """
            SELECT mineral, COUNT(*) AS count, MAX(score) AS best_score
            FROM mineral_candidates
            GROUP BY mineral
            ORDER BY count DESC, best_score DESC
            LIMIT 20
            """
        ).fetchall()
    return {
        "raw_total": raw_total,
        "samples": samples,
        "processed": processed,
        "pending": pending,
        "errors": errors,
        "top_minerals": [dict(row) for row in mineral_rows],
    }
