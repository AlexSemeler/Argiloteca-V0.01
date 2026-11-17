"""Idempotent atomic storage for DRX uploads needed by offline workers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from argiloteca.drx.services.upload_service import validate_filename


class TemporaryUploadRepository:
    def __init__(self, root: Path):
        self.root = Path(root)

    def persist(self, content: bytes, *, filename: str, sha256: str) -> Path:
        safe_name, _ = validate_filename(filename)
        actual_hash = hashlib.sha256(content).hexdigest()
        if actual_hash != sha256 or len(sha256) != 64:
            raise ValueError("Hash do upload temporario invalido.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self.root / f"{sha256[:16]}_{safe_name}"
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                raise FileExistsError("Colisao no artefato temporario.")
            return target
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.root, prefix=f".{sha256[:16]}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                os.chmod(temporary, 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                if hashlib.sha256(target.read_bytes()).hexdigest() != sha256:
                    raise
            temporary.unlink()
            temporary = None
            return target
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
