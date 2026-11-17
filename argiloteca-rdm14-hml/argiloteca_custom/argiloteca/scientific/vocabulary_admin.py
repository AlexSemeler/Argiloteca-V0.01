"""Read native vocabulary entries from the vocabulary-type administration link."""
from flask import abort, current_app, g, make_response, render_template, request, url_for
from flask_babel import get_locale
from invenio_vocabularies.proxies import current_service
from invenio_vocabularies.records.models import VocabularyType
from marshmallow import ValidationError
from invenio_search.engine import search

from .restricted_review import can_review


def text(pt, en):
    return pt if get_locale().language == 'pt' else en


def register_vocabularies(bp):
    @bp.after_request
    def private_vocabulary(response):
        if request.endpoint == 'argiloteca_scientific.vocabulary_entries':
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @bp.get('/administration/vocabulary-types/<type_id>')
    @bp.get('/administration/vocabulary-types/<type_id>/')
    def vocabulary_entries(type_id):
        if not can_review():
            abort(403)
        if VocabularyType.query.filter_by(id=type_id).first() is None:
            abort(404)
        try:
            page = int(request.args.get('page', 1))
            if not 1 <= page <= 500:
                raise ValueError()
        except ValueError:
            abort(400)
        q = request.args.get('q', '').strip()
        if len(q) > 100:
            abort(400)
        error = None
        status = 200
        rows = []
        total = 0
        try:
            result = current_service.search(g.identity, type=type_id,
                params={'q':q, 'page':page, 'size':20}).to_dict()
            rows = result['hits']['hits']
            total = result['hits']['total']
            if isinstance(total, dict):
                total = total['value']
        except (ValidationError, search.RequestError):
            error = text('Busca inválida. Revise os termos e tente novamente.',
                         'Invalid search. Check the terms and try again.')
            status = 400
        except search.ConnectionError:
            current_app.logger.warning('Vocabulary administration search unavailable')
            error = text('A busca está indisponível. Tente atualizar a página.',
                         'Search is unavailable. Try refreshing the page.')
            status = 503
        language = get_locale().language
        for row in rows:
            title = row.get('title') or {}
            row['display_title'] = (title.get(language) or title.get('pt') or title.get('en') or row['id']) if isinstance(title, dict) else str(title)
        pages = max(1, (total + 19)//20)
        page_url = lambda p: url_for('.vocabulary_entries', type_id=type_id, page=p, q=q, ln=language)
        return make_response(render_template('semantic-ui/argiloteca/admin_vocabulary_entries.html',
            vt=text, type_id=type_id, rows=rows, total=total, page=page, pages=pages,
            q=q, error=error, page_url=page_url, language=language,
            clear_url=url_for('.vocabulary_entries',type_id=type_id,ln=language)), status)
