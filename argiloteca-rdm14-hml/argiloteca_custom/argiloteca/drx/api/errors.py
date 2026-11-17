import traceback

from flask import jsonify


def json_service_error(exc, **fallback):
    """Preserve the legacy diagnostic error shape for extracted read routes."""
    return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc(), **fallback}), 500
