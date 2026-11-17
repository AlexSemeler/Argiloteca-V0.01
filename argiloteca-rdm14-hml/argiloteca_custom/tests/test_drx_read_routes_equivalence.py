from __future__ import annotations

from unittest import mock

from flask import Flask, url_for

import argiloteca.views as views
from argiloteca.drx.api import create_drx_blueprint
from argiloteca.drx.services.rag_client import RagUnavailableError


def app():
    instance = Flask(__name__)
    instance.register_blueprint(views.create_blueprint(instance))
    return instance


def test_read_route_contracts_have_no_duplicate_rule_method_pairs():
    instance = app()
    pairs = [(rule.rule, tuple(sorted(rule.methods - {"HEAD", "OPTIONS"}))) for rule in instance.url_map.iter_rules()]
    assert len(pairs) == len(set(pairs))


def test_public_endpoint_names_and_url_for_are_preserved():
    instance = app()
    with instance.test_request_context():
        assert url_for("argiloteca.drx_comparacao") == "/drx/comparacao"
        assert url_for("argiloteca.api_drx_registros") == "/argiloteca/drx/registros"
        assert url_for("argiloteca.api_drx_raw_snapshot") == "/argiloteca/drx/raw-snapshot"
        assert url_for("argiloteca.api_drx_rag_status") == "/argiloteca/drx/rag/status"
        assert url_for("argiloteca.drx_selection_report_html", run_id="r1") == "/argiloteca/drx/reports/selection/r1"
        assert url_for("argiloteca.api_drx_runs") == "/argiloteca/drx/runs"
        assert url_for("argiloteca.api_drx_run_detail", run_id="r1") == "/argiloteca/drx/runs/r1"
        assert url_for("argiloteca.api_drx_external_job_submit") == "/argiloteca/drx/jobs/external"
        assert url_for("argiloteca.api_drx_external_job_status", job_id="j1") == "/argiloteca/drx/jobs/external/j1"
        assert url_for("argiloteca.api_drx_externo_curva") == "/argiloteca/drx/externo/curva"


def test_comparison_without_context_preserves_template_contract():
    instance = app()
    with mock.patch.object(views, "build_authorized_mineral_catalog", return_value=[]), mock.patch.object(
        views, "render_template", return_value="comparison||"
    ) as renderer:
        response = instance.test_client().get("/drx/comparacao")
    assert response.status_code == 200
    assert renderer.call_args.args[0].endswith("drx_comparacao.html")
    assert renderer.call_args.kwargs["context_record_id"] == ""


def test_rag_available_query_and_unavailable_status_keep_http_contracts():
    instance = app()
    rag = mock.Mock()
    rag.query.return_value = {"answer": "ok", "available": True, "sources": []}
    with mock.patch.object(views.RagClient, "from_env", return_value=rag):
        query = instance.test_client().post("/argiloteca/drx/rag/query", json={"question": "evidências"})
    with mock.patch.object(views.RagClient, "from_env", side_effect=RagUnavailableError("offline")):
        status = instance.test_client().get("/argiloteca/drx/rag/status")
    assert query.status_code == 200 and query.get_json()["answer"] == "ok"
    assert status.status_code == 503 and status.get_json()["available"] is False


def test_records_snapshot_suggestions_and_curve_reads_preserve_payloads():
    instance = app()
    with mock.patch.object(views, "list_records_with_drx", return_value={"success": True, "records": []}):
        records = instance.test_client().get("/api/argiloteca/drx/registros")
    with mock.patch.object(views, "list_raw_snapshot_items", return_value={"success": True, "items": []}):
        snapshot = instance.test_client().get("/api/argiloteca/drx/raw-snapshot")
    with mock.patch.object(views, "build_raw_snapshot_comparison_suggestions", return_value={"success": True, "suggestions": []}):
        suggestions = instance.test_client().get("/api/argiloteca/drx/raw-snapshot/sugestoes")
    curve_data = {"metadata": {"sample_code": "A"}, "two_theta": [2.0, 3.0], "intensity": [1.0, 2.0]}
    with mock.patch.object(views, "load_diffractogram_data", return_value=curve_data):
        curve = instance.test_client().get("/api/argiloteca/drx/difratogramas/d1")
    assert all(response.status_code == 200 for response in (records, snapshot, suggestions, curve))
    assert curve.get_json()["total_points"] == 2


def test_curve_and_service_errors_preserve_404_and_500_shapes():
    instance = app()
    with mock.patch.object(views, "load_diffractogram_data", return_value=None):
        missing = instance.test_client().get("/api/argiloteca/drx/difratogramas/missing")
    with mock.patch.object(views, "list_records_with_drx", side_effect=RuntimeError("falha controlada")):
        failed = instance.test_client().get("/api/argiloteca/drx/registros")
    assert missing.status_code == 404
    assert failed.status_code == 500
    assert failed.get_json()["records"] == []


def test_report_selection_status_reference_and_neural_reads():
    instance = app()
    report = {"schema_version": "argiloteca.drx.selection_report.v1"}
    with mock.patch.object(views, "get_drx_run", return_value={"success": True, "selection_report": report}), mock.patch.object(
        views, "render_drx_selection_report_html", return_value="<html>selection</html>"
    ):
        selection = instance.test_client().get("/argiloteca/drx/reports/selection/r1")
    with mock.patch.object(views, "science_engine_status", return_value={"available": True}):
        science = instance.test_client().get("/api/argiloteca/drx/science-engine/status")
    with mock.patch.object(views, "gsas2_status", return_value={"available": False}):
        gsas = instance.test_client().get("/api/argiloteca/drx/gsas2/status")
    with mock.patch.object(views, "search_reference_index", return_value={"success": True, "references": []}):
        references = instance.test_client().get("/api/argiloteca/drx/references")
    neural_payload = {"success": True, "available": True, "matched": True}
    with mock.patch.object(views, "load_diffractogram_data", return_value={"metadata": {}}), mock.patch.object(
        views, "neural_evidence_for_diffractogram", return_value=neural_payload
    ):
        neural = instance.test_client().get("/api/argiloteca/drx/neural-evidence/d1")
    assert selection.status_code == 200 and selection.mimetype == "text/html"
    assert science.get_json()["success"] is True
    assert gsas.get_json()["success"] is False
    assert references.status_code == 200 and neural.status_code == 200


def test_read_route_factory_does_not_register_twice():
    instance = Flask(__name__)
    public_blueprint = views.create_blueprint(instance)
    deferred_before = len(public_blueprint.deferred_functions)
    assert create_drx_blueprint(public_blueprint, None) is public_blueprint
    assert len(public_blueprint.deferred_functions) == deferred_before
    instance.register_blueprint(public_blueprint)
    rules = list(instance.url_map.iter_rules())
    assert len([rule for rule in rules if rule.endpoint == "argiloteca.api_drx_registros"]) == 2


def test_job_and_run_query_command_routes_preserve_status_contracts():
    instance = app()
    client = instance.test_client()
    with mock.patch.object(views, "list_external_jobs", return_value={"success": True, "jobs": [], "total": 0}):
        jobs = client.get("/api/argiloteca/drx/jobs/external")
    with mock.patch.object(views, "submit_external_job", return_value={"success": True, "job": {"job_id": "j1"}}):
        submitted = client.post("/api/argiloteca/drx/jobs/external", json={"engine": "gsas2"})
    with mock.patch.object(views, "get_external_job", return_value={"success": False, "error": "missing"}):
        missing_job = client.get("/api/argiloteca/drx/jobs/external/missing")
    with mock.patch.object(views, "list_drx_runs", return_value={"success": True, "runs": [], "total": 0}):
        runs = client.get("/api/argiloteca/drx/runs")
    with mock.patch.object(views, "persist_drx_run", return_value={"success": True, "run_id": "r1"}):
        created_run = client.post("/api/argiloteca/drx/runs", json={"analysis_run": {"input": {}}})
    with mock.patch.object(views, "get_drx_run", return_value={"success": False, "error": "missing"}):
        missing_run = client.get("/api/argiloteca/drx/runs/missing")

    assert jobs.status_code == 200
    assert submitted.status_code == 202
    assert missing_job.status_code == 404
    assert runs.status_code == 200
    assert created_run.status_code == 201
    assert missing_run.status_code == 404
