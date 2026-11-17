from flask import jsonify, url_for

from .errors import json_service_error
from .legacy import bounded_int_arg


def register_report_routes(blueprint, deps):
    @blueprint.route("/api/argiloteca/drx/technical-report/<diffractogram_id>", endpoint="api_drx_technical_report")
    @blueprint.route("/argiloteca/drx/technical-report/<diffractogram_id>")
    @blueprint.route("/argiloteca/drx/technical-report/<diffractogram_id>.json")
    def api_drx_technical_report(diffractogram_id):
        try:
            curve = deps.load_diffractogram_data(diffractogram_id)
            if curve is None:
                return jsonify({"success": False, "error": "Difratograma nao encontrado"}), 404
            payload = deps.build_technical_report_for_curve(
                diffractogram_id, curve, max_points=bounded_int_arg("max_points", 3000, maximum=5000),
            )
            if payload is None:
                return jsonify({"success": False, "error": "Curva sem pontos para relatorio tecnico."}), 404
            return jsonify(payload)
        except Exception as exc:
            return json_service_error(exc)

    @blueprint.route("/argiloteca/drx/reports/technical/<diffractogram_id>", endpoint="drx_technical_report_html")
    @blueprint.route("/argiloteca/drx/reports/technical/<diffractogram_id>.html")
    def drx_technical_report_html(diffractogram_id):
        try:
            curve = deps.load_diffractogram_data(diffractogram_id)
            if curve is None:
                return "Difratograma nao encontrado", 404
            payload = deps.build_technical_report_for_curve(
                diffractogram_id, curve, max_points=bounded_int_arg("max_points", 3000, maximum=5000),
            )
            if payload is None:
                return "Curva sem pontos para relatorio tecnico.", 404
            return deps.render_technical_report_html(payload["technical_report"]), 200, {"Content-Type": "text/html; charset=utf-8"}
        except Exception as exc:
            return f"Erro ao gerar relatorio tecnico DRX: {exc}", 500

    @blueprint.route("/argiloteca/drx/reports/selection/<run_id>.html")
    @blueprint.route("/argiloteca/drx/reports/selection/<run_id>", endpoint="drx_selection_report_html")
    def drx_selection_report_html(run_id):
        payload = deps.get_drx_run(run_id)
        if not payload.get("success"):
            return payload.get("error") or "Run DRX nao encontrado.", 404
        report = payload.get("selection_report") or payload.get("technical_report") or {}
        html = (deps.render_selection_report_html(report)
                if report.get("schema_version") == "argiloteca.drx.selection_report.v1"
                else deps.render_technical_report_html(report))
        return html, 200, {"Content-Type": "text/html; charset=utf-8"}

    @blueprint.route("/argiloteca/drx/reports/selection/<run_id>.pdf", endpoint="drx_selection_report_pdf")
    def drx_selection_report_pdf(run_id):
        payload = deps.get_drx_run(run_id)
        if not payload.get("success"):
            return payload.get("error") or "Run DRX nao encontrado.", 404
        return jsonify({"success": False, "error": "Geracao PDF backend indisponivel neste ambiente; use o HTML imprimivel.",
                        "html_url": url_for("argiloteca.drx_selection_report_html", run_id=run_id), "run_id": run_id}), 501

    @blueprint.route("/api/argiloteca/drx/science-engine/status", endpoint="api_drx_science_engine_status")
    @blueprint.route("/argiloteca/drx/science-engine/status")
    def api_drx_science_engine_status():
        payload = deps.science_engine_status()
        return jsonify({"success": bool(payload.get("available")), "engine": payload})

    @blueprint.route("/api/argiloteca/drx/gsas2/status", endpoint="api_drx_gsas2_status")
    @blueprint.route("/argiloteca/drx/gsas2/status")
    def api_drx_gsas2_status():
        payload = deps.gsas2_status()
        return jsonify({"success": bool(payload.get("available")), "engine": payload})

    @blueprint.route("/api/argiloteca/drx/gsas2/compare-job/<job_id>", endpoint="api_drx_gsas2_compare_job")
    @blueprint.route("/argiloteca/drx/gsas2/compare-job/<job_id>")
    def api_drx_gsas2_compare_job(job_id):
        payload = deps.compare_completed_job(job_id)
        return jsonify(payload), 200 if payload.get("success") else 404
