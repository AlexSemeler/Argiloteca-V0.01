"""HTTP adapters for versioned DRX analysis-run artifacts."""

import traceback

from flask import jsonify, request

from .legacy import bounded_int_arg


def register_run_routes(blueprint, deps):
    @blueprint.route("/api/argiloteca/drx/runs", methods=["GET", "POST"], endpoint="api_drx_runs")
    @blueprint.route("/argiloteca/drx/runs", methods=["GET", "POST"])
    def api_drx_runs():
        try:
            if request.method == "GET":
                return jsonify(deps.list_drx_runs(
                    record_id=request.args.get("record_id") or None,
                    sample_code=request.args.get("sample_code") or None,
                    limit=bounded_int_arg("limit", 50, 1, 250),
                ))
            body = request.get_json(silent=True) or {}
            diffractogram_id = body.get("diffractogram_id") or request.form.get("diffractogram_id")
            analysis_run = body.get("analysis_run") if isinstance(body.get("analysis_run"), dict) else None
            technical_report = body.get("technical_report") if isinstance(body.get("technical_report"), dict) else None
            selection_report = body.get("selection_report") if isinstance(body.get("selection_report"), dict) else None
            inputs = body.get("inputs") if isinstance(body.get("inputs"), dict) else {}
            outputs = body.get("outputs") if isinstance(body.get("outputs"), dict) else {}
            parameters = body.get("parameters") if isinstance(body.get("parameters"), dict) else {}
            if diffractogram_id and not analysis_run:
                curve_payload = deps.load_diffractogram_data(diffractogram_id)
                if curve_payload is None:
                    return jsonify({"success": False, "error": "Difratograma nao encontrado"}), 404
                report_payload = deps.build_technical_report_for_curve(
                    diffractogram_id,
                    curve_payload,
                    max_points=bounded_int_arg("max_points", 3000, 1, 5000),
                    include_processing=True,
                )
                if report_payload is None:
                    return jsonify({"success": False, "error": "Curva sem pontos para run DRX."}), 404
                analysis_run = report_payload.get("analysis_run")
                technical_report = report_payload.get("technical_report")
                metadata = curve_payload.get("metadata") or {}
                inputs = {**inputs, "diffractogram_id": diffractogram_id, "metadata": {
                    key: metadata.get(key)
                    for key in ("sample_code", "original_filename", "filename", "source_sha256", "record_id")
                    if metadata.get(key) is not None
                }}
                outputs = {
                    **outputs,
                    "peak_count": len((report_payload.get("advanced_processing") or {}).get("peaks") or []),
                    "fit_count": len((report_payload.get("advanced_processing") or {}).get("fit_results") or []),
                }
            if not (analysis_run or technical_report or selection_report):
                return jsonify({"success": False, "error": "Informe diffractogram_id, analysis_run, technical_report ou selection_report."}), 400
            payload = deps.persist_drx_run(
                analysis_run=analysis_run,
                technical_report=technical_report,
                selection_report=selection_report,
                inputs=inputs,
                outputs=outputs,
                parameters=parameters,
                record_id=body.get("record_id") or request.form.get("record_id"),
                sample_code=body.get("sample_code") or request.form.get("sample_code"),
                run_id=body.get("run_id") or request.form.get("run_id"),
            )
            return jsonify(payload), 201
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500

    @blueprint.route("/api/argiloteca/drx/runs/<run_id>", endpoint="api_drx_run_detail")
    @blueprint.route("/argiloteca/drx/runs/<run_id>")
    def api_drx_run_detail(run_id):
        payload = deps.get_drx_run(run_id)
        return jsonify(payload), 200 if payload.get("success") else 404
