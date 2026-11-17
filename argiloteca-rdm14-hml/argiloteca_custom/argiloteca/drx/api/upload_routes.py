"""HTTP boundary for temporary and persistent DRX uploads."""

import traceback
from pathlib import Path

from flask import current_app, jsonify, request

from argiloteca.services.drx import RawParseError
from argiloteca.drx.contracts.external_curve import ExternalCurveRequest
from argiloteca.drx.services.temporary_curve_service import ExternalCurveValidationError
from .legacy import bounded_int_arg


def register_upload_routes(blueprint, deps):
    @blueprint.route("/api/argiloteca/drx/externo/curva", methods=["POST"], endpoint="api_drx_externo_curva")
    @blueprint.route("/argiloteca/drx/externo/curva", methods=["POST"])
    def api_drx_externo_curva():
        limit = int(deps.temp_upload_limit())
        if request.content_length is not None and request.content_length > limit:
            return _too_large(limit)
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"success": False, "error": "Envie um arquivo .raw, .csv, .txt, .xy ou .dat para comparação temporária."}), 400
        filename = uploaded.filename or "arquivo_externo.raw"
        if Path(filename).suffix.lower() not in {".raw", ".csv", ".txt", ".xy", ".dat"}:
            return jsonify({"success": False, "error": "O arquivo externo precisa ter extensão .raw, .csv, .txt, .xy ou .dat."}), 400
        content = uploaded.read(limit + 1)
        if len(content) > limit:
            return _too_large(limit)
        try:
            result = deps.external_curve_service_factory().analyze(ExternalCurveRequest(
                content=content,
                filename=filename,
                sample_code=request.form.get("sample_code") or None,
                record_id=(request.form.get("record_id") or request.args.get("record_id") or "").strip() or None,
                similarity_scope=(request.form.get("similarity_scope") or request.args.get("similarity_scope") or "all").strip().lower(),
                max_points=bounded_int_arg("max_points", 3000, 1, 5000),
                wavelength_angstrom=_bounded_float("wavelength_angstrom", 1.5406, 0.1, 5.0),
                wavelength_assumed=not bool(request.args.get("wavelength_angstrom") or request.form.get("wavelength_angstrom")),
            ))
            return jsonify(result)
        except (RawParseError, ExternalCurveValidationError) as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        except Exception as exc:
            payload = {"success": False, "error": str(exc)}
            if current_app.config.get("DEBUG"):
                payload["traceback"] = traceback.format_exc()
            return jsonify(payload), 500

    @blueprint.route("/api/argiloteca/drx/importar", methods=["POST"], endpoint="api_drx_importar")
    @blueprint.route("/argiloteca/drx/importar", methods=["POST"])
    def api_drx_importar():
        if current_app.config.get('ARGILOTECA_DRX_ANONYMOUS_POLICY', False):
            return jsonify({'success': False, 'error': 'Use o depósito de trios N/G/C anonimizados / Use the anonymous N/G/C trio deposit.'}), 403
        body = request.get_json(silent=True) or {}
        record_id = (request.form.get("record_id") or body.get("record_id") or "").strip()
        sample_code = request.form.get("sample_code") or body.get("sample_code")
        local_path = request.form.get("path") or body.get("path")
        uploaded = request.files.get("file")
        if not record_id:
            return jsonify({"success": False, "error": "Informe o record_id do registro de argila."}), 400
        if not uploaded and not local_path:
            return jsonify({"success": False, "error": "Envie um arquivo .raw ou informe um caminho local autorizado."}), 400
        try:
            if not deps.record_exists(record_id, size=bounded_int_arg("record_lookup_size", 5000, 1, 10000)):
                return jsonify({
                    "success": False,
                    "error": "Registro de argila nao encontrado. Informe um record_id publicado da Argiloteca.",
                }), 404
            item = (
                deps.import_raw_upload(record_id=record_id, storage=uploaded, sample_code=sample_code)
                if uploaded
                else deps.import_raw_path(record_id=record_id, path=local_path, sample_code=sample_code)
            )
            return jsonify({"success": True, "diffractogram": item}), 201
        except RawParseError as exc:
            original_name = uploaded.filename if uploaded else Path(local_path or "arquivo.raw").name
            item = deps.record_import_error(record_id, original_name, str(exc), sample_code=sample_code)
            return jsonify({"success": False, "error": str(exc), "diffractogram": item}), 422
        except Exception as exc:
            return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


def _too_large(limit):
    return jsonify({"success": False, "error": "Arquivo excede o limite de %.1f MB para upload temporario DRX." % (limit / (1024 * 1024))}), 413


def _bounded_float(name, default, minimum, maximum):
    try:
        value = float(request.args.get(name) or request.form.get(name) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(float(value), maximum))
