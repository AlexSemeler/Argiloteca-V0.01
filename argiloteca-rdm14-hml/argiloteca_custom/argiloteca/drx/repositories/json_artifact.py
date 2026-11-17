"""Bounded, atomic JSON artifact persistence for DRX jobs and runs."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class InvalidArtifactId(ValueError):
    pass


class JsonArtifactRepository:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def validate_id(value: Any) -> str:
        identifier = str(value or "")
        if not VALID_ID.fullmatch(identifier):
            raise InvalidArtifactId("Identificador de artefato invalido.")
        return identifier

    def directory(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def path(self, identifier: Any) -> Path:
        return self.directory() / f"{self.validate_id(identifier)}.json"

    def read(self, identifier: Any) -> dict:
        payload = json.loads(self.path(identifier).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("JSON root is not an object", "", 0)
        return payload

    def write(self, identifier: Any, payload: dict) -> Path:
        target = self.path(identifier)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}.", suffix=".tmp", delete=False) as stream:
                temporary_path = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, target)
            temporary_path = None
            return target
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def list_payloads(self, *, reverse: bool = False):
        for path in sorted(self.directory().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=reverse):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                yield payload
