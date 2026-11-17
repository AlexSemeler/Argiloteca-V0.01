"""HTTP adapters for transactional external DRX jobs."""

from flask import jsonify, request

from .legacy import bounded_int_arg


def register_job_routes(blueprint, deps):
    @blueprint.route(
        "/api/argiloteca/drx/jobs/external",
        methods=["GET", "POST"],
        endpoint="api_drx_external_job_submit",
    )
    @blueprint.route("/argiloteca/drx/jobs/external", methods=["GET", "POST"])
    def api_drx_external_job_submit():
        if request.method == "GET":
            return jsonify(deps.list_external_jobs(
                status=request.args.get("status") or None,
                limit=bounded_int_arg("limit", 50, 1, 250),
            ))
        payload = request.get_json(silent=True) or request.form.to_dict(flat=True) or {}
        result = deps.submit_external_job(payload.get("engine") or request.args.get("engine"), payload=payload)
        return jsonify(result), 202 if result.get("success") else 400

    @blueprint.route(
        "/api/argiloteca/drx/jobs/external/<job_id>",
        endpoint="api_drx_external_job_status",
    )
    @blueprint.route("/argiloteca/drx/jobs/external/<job_id>")
    def api_drx_external_job_status(job_id):
        result = deps.get_external_job(job_id)
        return jsonify(result), 200 if result.get("success") else 404
