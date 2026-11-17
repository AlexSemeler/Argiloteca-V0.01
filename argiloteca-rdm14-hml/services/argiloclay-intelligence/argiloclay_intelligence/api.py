"""Compatible RAG HTTP boundary; run behind the Invenio proxy on loopback."""
import sqlite3
from flask import Flask, jsonify, request
from .engine import from_env
from .mcp_bridge import MCPBridge, MCPUnavailable
from .workflow import query as chat_workflow
from .generation import Jobs


def create_app(engine=None, bridge=None, jobs=None):
    app = Flask(__name__); app.config["MAX_CONTENT_LENGTH"] = 16384
    engine = engine or from_env()
    bridge = bridge or MCPBridge()
    jobs = jobs or Jobs()

    @app.get("/api/v1/chat/status")
    def chat_status():
        try:
            bridge.start()
            status = engine.status()
            status.update(mcp={"available": True, "transport": "stdio", "tools": bridge.tools})
            status['async_generation'] = {'enabled':jobs.enabled,'model':'qwen3:0.6b','maximum_seconds':jobs.budget,'concurrency':1}
            return jsonify(status)
        except (MCPUnavailable, OSError, sqlite3.Error, ValueError):
            return jsonify(available=False, error="RAG/MCP indisponível."), 503

    @app.post("/api/v1/chat/query")
    def chat_query():
        try: return jsonify(chat_workflow(request.get_json(silent=True), bridge))
        except ValueError as exc: return jsonify(error=str(exc)), 400
        except MCPUnavailable: return jsonify(available=False, error="RAG/MCP indisponível."), 503

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error="Requisição acima do limite."), 413

    @app.post('/api/v1/chat/generation')
    def generation_start():
        try: return jsonify(jobs.submit(request.get_json(silent=True)))
        except ValueError as exc: return jsonify(error=str(exc)),400

    @app.route('/api/v1/chat/generation/<key>',methods=['GET','DELETE'])
    def generation_get(key):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}',key): return jsonify(error='Job inexistente.'),404
        try:
            result = jobs.cancel(key) if request.method=='DELETE' else jobs.get(key)
            response = jsonify(result);response.headers['Cache-Control']='no-store';return response
        except KeyError: return jsonify(error='Job inexistente ou expirado.'),404

    @app.get("/api/v1/drx/status")
    def status():
        try:
            return jsonify(engine.status())
        except (OSError, sqlite3.Error, ValueError):
            return jsonify(available=False, error="Índice RAG indisponível."), 503

    @app.post("/api/v1/drx/query")
    def query():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="Envie um objeto JSON."), 400
        try:
            return jsonify(engine.query(payload.get("question"), payload.get("filters", {}), payload.get("top_k", 5)))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except (OSError, sqlite3.Error):
            return jsonify(available=False, error="Assistente RAG indisponível; o painel DRX continua operacional."), 503

    return app


app = create_app()
