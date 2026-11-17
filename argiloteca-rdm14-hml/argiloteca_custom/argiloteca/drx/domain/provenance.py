from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Provenance:
    source: str
    reference: str | None = None
    rule_id: str | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict:
        return {key: value for key, value in asdict(self).items() if value is not None}
