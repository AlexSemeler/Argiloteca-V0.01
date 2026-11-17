"""Atomic persistence for already validated DRX source bytes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from argiloteca.drx.services.upload_service import validate_filename


class RawRepository:
    def __init__(self, root: Path):
        self.root = Path(root)

    def write_new(self, identifier: str, filename: str, content: bytes) -> Path:
        safe_name, _ = validate_filename(filename)
        if not identifier or not identifier.isalnum():
            raise ValueError("Identificador RAW invalido.")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{identifier}_{safe_name}"
        if target.exists():
            raise FileExistsError(target)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=f".{identifier}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
            temporary.unlink()
            temporary = None
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
