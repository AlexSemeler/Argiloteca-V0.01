"""Validated adapter for temporary GSAS-II pattern validation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable


def validate_with_gsas2(*, temporary_path: Path, temporary_root: Path, original_filename: str,
                        detected_peaks: list, seed_builder: Callable, submit: Callable) -> dict:
    path = Path(temporary_path).resolve()
    root = Path(temporary_root).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("Artefato temporario fora da raiz autorizada.") from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return submit(
        path,
        original_filename=original_filename,
        seed_peaks=seed_builder(detected_peaks or []),
    )
