from flask import current_app, jsonify, request

from argiloteca.drx.services.reference_pilot_service import evaluate_reference_pilot, pilot_status


def reference_pilot_config():
    return {"enabled": current_app.config.get("ARGILOTECA_DRX_REFERENCE_PILOT_ENABLED", False),
            "index_path": current_app.config.get("ARGILOTECA_DRX_REFERENCE_PILOT_INDEX")}


def evaluate_configured_pilot(*args, **kwargs):
    return evaluate_reference_pilot(*args, **kwargs, **reference_pilot_config())

from .errors import json_service_error
from .legacy import bounded_int_arg


def register_reference_routes(blueprint, deps):
    @blueprint.route("/api/argiloteca/drx/references/pilot", methods=["GET", "POST"])
    @blueprint.route("/argiloteca/drx/references/pilot", methods=["GET", "POST"])
    def api_drx_reference_pilot():
        if request.method in {"GET", "HEAD"}:
            return jsonify(pilot_status(**reference_pilot_config()))
        if request.content_length is None:
            return jsonify({"success": False, "error": "Expected a JSON object."}), 400
        if request.content_length > 64 * 1024 * 1024:
            return jsonify({"success": False, "error": "Pilot request exceeds the 64 MiB limit."}), 413
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"success": False, "error": "Expected a JSON object."}), 400
        try:
            payload = evaluate_configured_pilot(body.get("two_theta"), body.get("intensity"),
                         wavelength_angstrom=body.get("wavelength_angstrom"),
                         preparation=body.get("preparation", "unknown"))
            return jsonify(payload), 200 if payload.get("available") else 503
        except (ValueError, TypeError, OverflowError):
            return jsonify({"success": False, "error": "Invalid curve or wavelength for reference comparison."}), 400
        except Exception:
            return jsonify({"success": False, "status": "unavailable", "reason": "pilot_analysis_failed"}), 503

    @blueprint.route("/api/argiloteca/drx/references", endpoint="api_drx_references")
    @blueprint.route("/argiloteca/drx/references")
    def api_drx_references():
        try:
            return jsonify(deps.search_reference_index(
                query=request.args.get("q") or request.args.get("query"), source=request.args.get("source"),
                limit=bounded_int_arg("limit", 25, 1, 100),
            ))
        except Exception as exc:
            return json_service_error(exc)

    @blueprint.route("/api/argiloteca/drx/neural-evidence/<diffractogram_id>", endpoint="api_drx_neural_evidence")
    @blueprint.route("/argiloteca/drx/neural-evidence/<diffractogram_id>")
    def api_drx_neural_evidence(diffractogram_id):
        try:
            curve = deps.load_diffractogram_data(diffractogram_id) or {}
            payload = deps.neural_evidence_for_diffractogram(diffractogram_id, metadata=curve.get("metadata") or {})
            status = 200 if payload.get("success") else 404
            if payload.get("available") and not payload.get("matched"):
                status = 404
            if not payload.get("available"):
                status = 503
            return jsonify(payload), status
        except Exception as exc:
            return json_service_error(exc)
