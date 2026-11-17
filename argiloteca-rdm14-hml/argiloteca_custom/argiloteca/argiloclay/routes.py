"""Same-origin, CSRF protected read-only conversation endpoints."""
from urllib.parse import urlsplit
from flask import jsonify, request
from flask_wtf.csrf import validate_csrf
from wtforms.validators import ValidationError
from .service import ChatClient, Unavailable, query, verify_records, PublicContextUnavailable
from . import async_service
import re


def guard():
    # Flask 2.2 in production exposes a read-only property; Flask 3.1 allows
    # a per-request override. The Content-Length guard applies to both.
    if getattr(type(request._get_current_object()), "max_content_length").fset:
        request.max_content_length = 16000
    if request.content_length and request.content_length > 16000:
        return jsonify(error="Requisição acima do limite."), 413
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return jsonify(error="Origem não autorizada."), 403
    try: validate_csrf(request.headers.get("X-CSRFToken"))
    except ValidationError: return jsonify(error="Sessão expirada. Recarregue a conversa."), 400


def register(blueprint):
    def scope():
        from flask_login import current_user
        return str(current_user.get_id()) if current_user.is_authenticated else 'anonymous'

    def owned(key):
        from flask import session
        return bool(re.fullmatch(r'[a-f0-9]{32}',key) and session.get('argiloclay_job_scope')==scope()
                    and key in session.get('argiloclay_job_ids',[]))

    @blueprint.post('/argiloclay/api/jobs',endpoint='argiloclay_jobs')
    def start_job():
        from flask import session
        blocked=guard()
        if blocked:return blocked
        try:
            data=async_service.start(request.get_json(silent=True),ChatClient())
            job=data.get('generation',{});key=job.get('job_id')
            if key:
                if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key):raise Unavailable('Job inválido.')
                previous=session.get('argiloclay_job_ids',[]) if session.get('argiloclay_job_scope')==scope() else []
                session['argiloclay_job_scope']=scope();session['argiloclay_job_ids']=(previous+[key])[-4:]
                session['argiloclay_job_language']=data['page_context']['language']
            response=jsonify(data);response.headers['Cache-Control']='no-store';return response
        except PublicContextUnavailable as exc:return jsonify(available=False,error=str(exc),response_kind="access_unavailable",sources=[]),400
        except ValueError as exc:return jsonify(error=str(exc)),400
        except Unavailable as exc:return jsonify(available=False,error=str(exc),response_kind="tool_unavailable"),503

    @blueprint.route('/argiloclay/api/jobs/<key>',methods=['GET','POST'],endpoint='argiloclay_job')
    def read_job(key):
        blocked=guard()
        if blocked:return blocked
        if not owned(key):return jsonify(error='Job inexistente ou de outra sessão.'),404
        try:
            if request.method=='POST':
                data=ChatClient().call('/api/v1/chat/generation/'+key,method='DELETE')
            else:
                from flask import session
                language=session.get('argiloclay_job_language','pt')
                data=async_service.poll(key,ChatClient(),language)
            response=jsonify(data);response.headers['Cache-Control']='no-store';return response
        except Unavailable as exc:return jsonify(available=False,error=str(exc),response_kind="tool_unavailable"),503

    @blueprint.get("/argiloclay/api/status", endpoint="argiloclay_status")
    def status():
        try: return jsonify(ChatClient().call("/api/v1/chat/status"))
        except Unavailable as exc:
            from .community_sources import public_sources
            try:count=len(public_sources())
            except Exception:count=0
            if count:return jsonify(available=True,partial=True,source_scope='community_about',public_communities=count)
            return jsonify(available=False, error=str(exc),response_kind="tool_unavailable"),503

    @blueprint.post("/argiloclay/api/query", endpoint="argiloclay_query")
    def chat_query():
        blocked = guard()
        if blocked: return blocked
        try: return jsonify(query(request.get_json(silent=True), ChatClient()))
        except PublicContextUnavailable as exc:return jsonify(available=False,error=str(exc),response_kind="access_unavailable",sources=[]),400
        except ValueError as exc: return jsonify(error=str(exc)), 400
        except Unavailable as exc: return jsonify(available=False, error=str(exc),response_kind="tool_unavailable"), 503

    @blueprint.post("/argiloclay/api/verify", endpoint="argiloclay_verify")
    def verify():
        blocked = guard()
        if blocked: return blocked
        try: return jsonify(verify_records(request.get_json(silent=True)))
        except Unavailable as exc:return jsonify(available=False,error=str(exc)),503
        except PublicContextUnavailable as exc:return jsonify(available=False,error=str(exc),response_kind="access_unavailable",sources=[]),400
        except ValueError as exc: return jsonify(error=str(exc)), 400
