from flask import jsonify, request, send_file
from flask_babel import gettext as _

from .errors import json_service_error
from .legacy import bounded_int_arg


def register_curve_routes(blueprint, deps):
    @blueprint.route("/api/argiloteca/drx/registros", endpoint="api_drx_registros")
    @blueprint.route("/argiloteca/drx/registros")
    def api_drx_registros():
        try:
            filters = {key: request.args.get(key) or None for key in ("q", "sample_code", "argilomineral", "mineral_group")}
            return jsonify(deps.list_records_with_drx(filters=filters, size=bounded_int_arg("size", 500, maximum=5000)))
        except Exception as exc:
            return json_service_error(exc, records=[])

    @blueprint.route("/api/argiloteca/drx/raw-snapshot", endpoint="api_drx_raw_snapshot")
    @blueprint.route("/argiloteca/drx/raw-snapshot")
    def api_drx_raw_snapshot():
        try:
            keys = ("q", "sample_code", "preparation", "argilomineral", "mineral_group", "status")
            filters = {key: request.args.get(key) or None for key in keys}
            payload = deps.list_raw_snapshot_items(
                filters=filters, limit=bounded_int_arg("limit", 80, 1, 500), offset=bounded_int_arg("offset", 0, 0, 1000000),
            )
            from ...scientific.drx_link_views import decorate_public_items
            decorate_public_items(payload.get('items') or [])
            response = jsonify(payload)
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
            return response
        except Exception as exc:
            return json_service_error(exc, items=[])

    @blueprint.route("/api/argiloteca/drx/raw-snapshot/<diffractogram_id>/download", endpoint="api_drx_raw_download")
    @blueprint.route("/argiloteca/drx/raw-snapshot/<diffractogram_id>/download")
    def api_drx_raw_download(diffractogram_id):
        resolved = deps.resolve_snapshot_raw_download(diffractogram_id) if deps.resolve_snapshot_raw_download else None
        if resolved is None:
            return jsonify({"success": False, "error": _("Arquivo RAW não encontrado.")}), 404
        path, filename = resolved
        response = send_file(path, as_attachment=True, download_name=filename,
                             mimetype="application/octet-stream", conditional=True)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @blueprint.route("/api/argiloteca/drx/raw-snapshot/sugestoes", endpoint="api_drx_raw_snapshot_sugestoes")
    @blueprint.route("/argiloteca/drx/raw-snapshot/sugestoes")
    def api_drx_raw_snapshot_sugestoes():
        try:
            keys = ("q", "sample_code", "preparation", "argilomineral", "mineral_group", "status")
            filters = {key: request.args.get(key) or None for key in keys}
            return jsonify(deps.build_snapshot_suggestions(filters=filters, limit=bounded_int_arg("limit", 1000, 1, 5000)))
        except Exception as exc:
            return json_service_error(exc, suggestions=[])

    @blueprint.route("/api/argiloteca/drx/difratogramas/<diffractogram_id>", endpoint="api_drx_difratograma")
    @blueprint.route("/argiloteca/drx/difratogramas/<diffractogram_id>")
    def api_drx_difratograma(diffractogram_id):
        if diffractogram_id.startswith('linked:'):
            from ...scientific.drx_link_views import linked_curve
            response = jsonify(linked_curve(diffractogram_id.removeprefix('linked:')))
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
            return response
        try:
            payload = deps.load_diffractogram_data(diffractogram_id)
            if payload is None:
                return jsonify({"success": False, "error": "Difratograma nao encontrado"}), 404
            x, y = deps.decimate_series(payload.get("two_theta") or [], payload.get("intensity") or [])
            metadata = dict(payload.get("metadata") or {})
            from ...scientific.drx_link_views import decorate_public_items
            decorated = decorate_public_items([metadata])[0]
            metadata.update({key: decorated[key] for key in ('record_links', 'record_id') if key in decorated})
            # Read-only evidence is calculated from the full curve, never persisted.
            from .reference_routes import evaluate_configured_pilot, reference_pilot_config
            if reference_pilot_config()["enabled"]:
                try:
                    metadata["reference_pilot"] = evaluate_configured_pilot(
                        payload.get("two_theta") or [], payload.get("intensity") or [],
                        wavelength_angstrom=metadata.get("wavelength_angstrom") or metadata.get("wavelength_A") or 1.5406,
                        preparation=metadata.get("preparation", "unknown"),
                        source_sha256=metadata.get("source_sha256"),
                    )
                    metadata["reference_pilot"]["wavelength_assumed"] = not bool(metadata.get("wavelength_angstrom") or metadata.get("wavelength_A"))
                except Exception:
                    metadata["reference_pilot"] = {"available": False, "status": "unavailable", "reason": "pilot_analysis_failed"}
            response = jsonify({"success": True, "metadata": metadata, "two_theta": x, "intensity": y,
                                "render_points": len(x), "total_points": len(payload.get("two_theta") or [])})
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
            return response
        except Exception as exc:
            return json_service_error(exc)
