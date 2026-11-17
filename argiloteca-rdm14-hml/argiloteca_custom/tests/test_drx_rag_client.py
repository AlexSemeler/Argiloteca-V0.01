from __future__ import annotations

import json
import socket
from io import BytesIO
from urllib.error import HTTPError, URLError
from unittest import mock

import pytest
from flask import Flask

import argiloteca.views as views
from argiloteca.drx.services.rag_client import (
    DEFAULT_BASE_URL,
    RagClient,
    RagInvalidResponseError,
    RagUnavailableError,
    RagUpstreamError,
    RagValidationError,
)


class FakeResponse:
    def __init__(self, payload, status=200, raw=False):
        self.status = status
        self.body = payload if raw else json.dumps(payload).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def capturing_opener(payload, status=200):
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.method
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data) if request.data else None
        return FakeResponse(payload, status)

    return opener, captured


def test_default_configuration(monkeypatch):
    monkeypatch.delenv("ARGILOTECA_DRX_RAG_URL", raising=False)
    monkeypatch.delenv("ARGILOTECA_DRX_RAG_TIMEOUT", raising=False)
    client = RagClient.from_env()
    assert client.base_url == DEFAULT_BASE_URL
    assert client.timeout == 8.0


def test_environment_configuration(monkeypatch):
    monkeypatch.setenv("ARGILOTECA_DRX_RAG_URL", "http://rag.internal:9000/")
    monkeypatch.setenv("ARGILOTECA_DRX_RAG_TIMEOUT", "12.5")
    client = RagClient.from_env()
    assert client.base_url == "http://rag.internal:9000"
    assert client.timeout == 12.5


@pytest.mark.parametrize(("given", "expected"), [(0, 1.0), (99, 30.0), ("inválido", 8.0)])
def test_timeout_is_bounded(given, expected):
    assert RagClient(timeout=given).timeout == expected


def test_status_available():
    opener, captured = capturing_opener({"indexed_documents": 9000})
    result = RagClient(opener=opener).status()
    assert result == {"indexed_documents": 9000, "available": True}
    assert captured["url"].endswith("/api/v1/drx/status")


@pytest.mark.parametrize("error", [URLError("offline"), OSError("offline"), TimeoutError(), socket.timeout()])
def test_status_unavailable(error):
    def opener(*_, **__):
        raise error
    with pytest.raises(RagUnavailableError):
        RagClient(opener=opener).status()


def test_valid_query_is_normalized_and_preserves_extra_fields():
    opener, captured = capturing_opener({"answer": "Resposta", "sources": [], "custom_safe": 1})
    result = RagClient(opener=opener).query("Quais evidências?", {"sample_code": "AM-1"}, 5)
    assert result["schema_version"] == "1.0"
    assert result["available"] is True
    assert result["custom_safe"] == 1
    assert captured["payload"]["question"] == "Quais evidências?"


@pytest.mark.parametrize("question", ["", " ", None, "x" * 2001])
def test_invalid_question(question):
    with pytest.raises(RagValidationError):
        RagClient().query(question)


@pytest.mark.parametrize("top_k", ["muitos", None, True])
def test_invalid_top_k(top_k):
    with pytest.raises(RagValidationError):
        RagClient().query("Pergunta", top_k=top_k)


@pytest.mark.parametrize(("given", "expected"), [(-4, 1), (0, 1), (8, 8), (100, 12)])
def test_top_k_is_bounded(given, expected):
    opener, captured = capturing_opener({"answer": "ok"})
    RagClient(opener=opener).query("Pergunta", top_k=given)
    assert captured["payload"]["top_k"] == expected


def test_filters_are_allowlisted_and_truncated():
    opener, captured = capturing_opener({"answer": "ok"})
    RagClient(opener=opener).query("Pergunta", filters={
        "tipo_fonte": "skill_drx_painel", "sample_code": "x" * 400,
        "remote_url": "http://malicioso", "empty": "", "record_id": None,
    })
    filters = captured["payload"]["filters"]
    assert filters["tipo_fonte"] == "skill_drx_painel"
    assert len(filters["sample_code"]) == 300
    assert "remote_url" not in filters


def test_http_400_payload_is_preserved():
    def opener(*_, **__):
        raise HTTPError("url", 400, "bad", {}, BytesIO(b'{"error":"pergunta invalida"}'))
    with pytest.raises(RagUpstreamError) as raised:
        RagClient(opener=opener).query("Pergunta")
    assert raised.value.status == 400
    assert raised.value.payload["error"] == "pergunta invalida"


def test_http_500_payload_is_preserved():
    def opener(*_, **__):
        raise HTTPError("url", 500, "bad", {}, BytesIO(b'{"error":"falha interna"}'))
    with pytest.raises(RagUpstreamError) as raised:
        RagClient(opener=opener).status()
    assert raised.value.status == 500


def test_invalid_json_maps_to_502():
    with pytest.raises(RagInvalidResponseError) as raised:
        RagClient(opener=lambda *_, **__: FakeResponse(b"not-json", raw=True)).status()
    assert raised.value.status == 502


def test_invalid_success_contract_maps_to_502():
    opener, _ = capturing_opener({"answer": "ok", "sources": "não é uma lista"})
    with pytest.raises(RagInvalidResponseError) as raised:
        RagClient(opener=opener).query("Pergunta")
    assert raised.value.status == 502


def flask_app():
    app = Flask(__name__)
    app.register_blueprint(views.create_blueprint(app))
    return app


def test_legacy_flask_endpoints_keep_names_and_paths():
    app = flask_app()
    rules = {rule.endpoint: rule.rule for rule in app.url_map.iter_rules()}
    assert rules["argiloteca.api_drx_rag_status"] == "/argiloteca/drx/rag/status"
    assert rules["argiloteca.api_drx_rag_query"] == "/argiloteca/drx/rag/query"


def test_legacy_query_accepts_skill_source_filter():
    app = flask_app()
    client = mock.Mock()
    client.query.return_value = {"answer": "ok", "available": True, "sources": []}
    with mock.patch.object(views.RagClient, "from_env", return_value=client):
        response = app.test_client().post("/argiloteca/drx/rag/query", json={
            "question": "Quais regras?", "filters": {"tipo_fonte": "skill_drx_painel"}, "top_k": 5,
        })
    assert response.status_code == 200
    assert client.query.call_args.kwargs["filters"]["tipo_fonte"] == "skill_drx_painel"


def test_rag_failure_does_not_break_comparison_page():
    app = flask_app()
    unavailable = RagUnavailableError("offline")
    with mock.patch.object(views.RagClient, "from_env", side_effect=unavailable), mock.patch.object(
        views, "build_authorized_mineral_catalog", return_value=[]
    ):
        status = app.test_client().get("/argiloteca/drx/rag/status")
        with mock.patch.object(views, "render_template", return_value="painel"):
            panel = app.test_client().get("/drx/comparacao")
    assert status.status_code == 503
    assert status.get_json()["available"] is False
    assert panel.status_code == 200
    assert panel.get_data(as_text=True) == "painel"
