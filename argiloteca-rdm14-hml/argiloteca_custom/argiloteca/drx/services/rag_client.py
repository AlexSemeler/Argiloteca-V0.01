"""HTTP client for the isolated ArgiloClay RAG service.

This module deliberately has no Flask or Invenio dependency and never loads an
LLM. Questions, answers and HTTP headers are not logged here.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Callable, Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..contracts.common import ContractValidationError
from ..contracts.rag import validate_rag_response

DEFAULT_BASE_URL = "http://127.0.0.1:7860"
DEFAULT_TIMEOUT = 8.0
ALLOWED_FILTERS = frozenset({
    "record_id", "sample_code", "sample_base", "preparation", "sha256",
    "source_relative_path", "tipo_fonte",
})
UNAVAILABLE_MESSAGE = "Assistente RAG indisponível; o painel DRX continua operacional."


class RagClientError(Exception):
    """Base class for errors safe to map at the HTTP boundary."""


class RagValidationError(RagClientError):
    """Invalid local request; maps to HTTP 400."""


class RagUnavailableError(RagClientError):
    """Connection or timeout failure; maps to HTTP 503."""


class RagUpstreamError(RagClientError):
    """An HTTP error returned by the RAG service."""

    def __init__(self, status: int, payload: Mapping[str, Any] | None = None):
        super().__init__("Serviço RAG recusou a solicitação.")
        self.status = status if 400 <= int(status) <= 599 else 502
        self.payload = dict(payload or {"error": str(self)})


class RagInvalidResponseError(RagUpstreamError):
    """Malformed upstream JSON; maps to HTTP 502."""

    def __init__(self):
        super().__init__(502, {"error": "Serviço RAG retornou uma resposta inválida."})


def _bounded_timeout(value: Any) -> float:
    try:
        return min(max(float(value), 1.0), 30.0)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def _bounded_top_k(value: Any) -> int:
    if isinstance(value, bool):
        raise RagValidationError("top_k deve ser um número inteiro entre 1 e 12.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise RagValidationError("top_k deve ser um número inteiro entre 1 e 12.") from exc
    return min(max(parsed, 1), 12)


def clean_filters(filters: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(filters, Mapping):
        return {}
    return {
        key: str(value)[:300]
        for key, value in filters.items()
        if key in ALLOWED_FILTERS and value not in (None, "", [], {})
    }


class RagClient:
    """Small injectable client preserving the existing ArgiloClay endpoints."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Callable[..., Any] = urlopen,
    ):
        self.base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = _bounded_timeout(timeout)
        self._opener = opener

    @classmethod
    def from_env(cls, *, opener: Callable[..., Any] = urlopen) -> "RagClient":
        return cls(
            base_url=os.getenv("ARGILOTECA_DRX_RAG_URL", DEFAULT_BASE_URL),
            timeout=os.getenv("ARGILOTECA_DRX_RAG_TIMEOUT", str(DEFAULT_TIMEOUT)),
            opener=opener,
        )

    def status(self) -> dict[str, Any]:
        payload, _ = self._request("/api/v1/drx/status")
        result = dict(payload)
        result.setdefault("available", True)
        return result

    def query(self, question: Any, filters: Mapping[str, Any] | None = None, top_k: Any = 5) -> dict[str, Any]:
        text = str(question or "").strip()
        if not text or len(text) > 2000:
            raise RagValidationError("Pergunta vazia ou acima de 2000 caracteres.")
        cleaned = clean_filters(filters)
        payload, _ = self._request(
            "/api/v1/drx/query",
            method="POST",
            payload={"question": text, "filters": cleaned, "top_k": _bounded_top_k(top_k)},
        )
        result = dict(payload)
        result.setdefault("schema_version", "1.0")
        result.setdefault("available", True)
        result.setdefault("answer", "Sem resposta.")
        result.setdefault("sources", [])
        result.setdefault("model", None)
        result.setdefault("elapsed_ms", None)
        result.setdefault("context_filters", cleaned)
        result.setdefault("limitations", ["Evidência auxiliar; não confirma identificação mineralógica."])
        try:
            return validate_rag_response(result)
        except ContractValidationError as exc:
            raise RagInvalidResponseError() from exc

    def _request(
        self, path: str, *, method: str = "GET", payload: Mapping[str, Any] | None = None
    ) -> tuple[dict[str, Any], int]:
        body = json.dumps(dict(payload or {}), ensure_ascii=False).encode("utf-8") if method == "POST" else None
        request = Request(
            f"{self.base_url}{path}", data=body, method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = int(getattr(response, "status", 200))
                return self._decode(response.read()), status
        except HTTPError as exc:
            try:
                error_payload = self._decode(exc.read())
            except RagInvalidResponseError:
                error_payload = {"error": "Serviço RAG recusou a solicitação."}
            raise RagUpstreamError(exc.code, error_payload) from exc
        except (URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise RagUnavailableError(UNAVAILABLE_MESSAGE) from exc

    @staticmethod
    def _decode(raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
            raise RagInvalidResponseError() from exc
        if not isinstance(payload, dict):
            raise RagInvalidResponseError()
        return payload
