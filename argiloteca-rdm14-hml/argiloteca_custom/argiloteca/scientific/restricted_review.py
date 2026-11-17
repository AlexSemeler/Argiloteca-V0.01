"""Administrative consultation of anonymous recovery evidence; no write routes."""
import json
from pathlib import Path

from flask import abort, current_app, make_response, render_template, request, url_for
from flask_login import current_user
from flask_babel import get_locale

ISSUES = {
    'missing_n': ('Natural (N) ausente', 'Natural (N) missing'),
    'missing_g': ('Glicolado (G) ausente', 'Glycolated (G) missing'),
    'missing_c': ('Calcinado (C) ausente', 'Calcined (C) missing'),
    'unknown_preparation': ('Preparo não identificado', 'Unidentified preparation'),
    'distinct_versions': ('Versões com dados diferentes', 'Versions with different data'),
    'mixed_wavelengths': ('Comprimentos de onda diferentes', 'Different wavelengths'),
    'unknown_wavelength': ('Comprimento de onda não informado', 'Wavelength not reported'),
    'unverified_axis_unit': ('Unidade do eixo não confirmada', 'Axis unit unconfirmed'),
    'link_unconfirmed': ('Vínculo de preparo não confirmado', 'Preparation link unconfirmed'),
}


def can_review():
    """Use the same full-access permission as native administration resource views."""
    from invenio_administration.permissions import administration_permission
    return bool(current_user.is_authenticated and administration_permission.can())


def load_catalogue():
    path = Path(current_app.config.get('ARGILOTECA_DRX_REVIEW_CATALOGUE',
        str(Path(current_app.instance_path) / 'app_data/drx-review/catalog.json')))
    data = json.loads(path.read_text())
    if (data['schema_version'] != 1 or data['mode'] != 'read_only'
            or len(data['groups']) != data['summary']['groups']
            or sum(len(g['files']) for g in data['groups']) != data['summary']['files']):
        raise ValueError('Invalid review catalogue')
    return data


def review_context(data, args):
    q = str(args.get('q', '')).strip()[:100]
    issue = args.get('issue', '')
    candidate = args.get('candidate', '')
    if issue and issue not in ISSUES:
        abort(400)
    if candidate and candidate not in {c['candidate_id'] for c in data['candidates']}:
        abort(400)
    try:
        page = max(1, min(10000, int(args.get('page', 1))))
    except (ValueError, TypeError):
        abort(400)
    rows = [g for g in data['groups']
            if (not q or q.casefold() in g['code'].casefold()
                or any(q.casefold() in f['filename'].casefold() for f in g['files']))
            and (not issue or issue in g['issues'])
            and (not candidate or candidate in g['candidate_ids'])]
    pages = max(1, (len(rows) + 19) // 20)
    page = min(page, pages)
    return dict(catalogue=data, groups=rows[(page-1)*20:page*20], total=len(rows),
                page=page, pages=pages, q=q, issue=issue, candidate=candidate, issue_labels=ISSUES)


def register_review(bp, app):
    from .admin_raw_views import register_library
    register_library(bp)
    @app.context_processor
    def review_navigation():
        return {'argilo_can_review_raws': can_review,
                'review_text': lambda pt, en: pt if get_locale().language == 'pt' else en}

    @bp.after_request
    def prevent_review_caching(response):
        if request.endpoint == 'argiloteca_scientific.restricted_raw_review':
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
        return response

    @bp.route('/administration/drx-review/', endpoint='restricted_raw_review')
    def review():
        if not can_review():
            abort(403)
        try:
            data = load_catalogue()
        except (OSError, ValueError, KeyError, TypeError):
            current_app.logger.warning('DRX review catalogue unavailable or invalid')
            return make_response(render_template('semantic-ui/argiloteca/restricted_raw_review.html',
                                                 unavailable=True), 503)
        context = review_context(data, request.args)
        context['page_url'] = lambda page: url_for('.restricted_raw_review', page=page,
            q=context['q'], issue=context['issue'], candidate=context['candidate'])
        return render_template('semantic-ui/argiloteca/restricted_raw_review.html', **context)
