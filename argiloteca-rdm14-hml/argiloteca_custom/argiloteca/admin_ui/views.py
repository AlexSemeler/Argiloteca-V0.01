"""Read-only ontology browsing through the existing native metadata tables."""
import math
from flask import Blueprint, abort, render_template, request, current_app, jsonify
from invenio_db import db
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from ..openalex.views import admin_only, private
from .ontology import ENTITIES, EFFECTIVE, predicate
from .navigation import tr, tools

blueprint = Blueprint('argiloteca_admin_ui', __name__, url_prefix='/administration/argiloteca')
blueprint.before_request(admin_only(lambda: None))
blueprint.after_request(private)


def counts():
    params={}; selections=[]
    for key in ENTITIES:
        selections.append('count(*) FILTER (WHERE '+predicate(key,params)+') AS '+key)
    row=db.session.execute(text(EFFECTIVE+'SELECT '+','.join(selections)+',count(*) total FROM effective'),params).mappings().one()
    return dict(row)


def safe_counts():
    try: return counts()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning('Ontology administration counts unavailable')
        return None


@blueprint.get('/fontes/')
def sources():
    return render_template('semantic-ui/argiloteca/admin_sources.html',title=tr('Fontes de povoamento','Import data sources'))


@blueprint.get('/entidades/<entity>/')
def entity(entity):
    if entity not in ENTITIES: abort(404)
    spec=ENTITIES[entity]
    q=request.args.get('q','').strip()[:150];stage=request.args.get('stage','')
    if stage not in ('','published','draft','editing'):abort(400)
    try:page=int(request.args.get('page',1))
    except ValueError:abort(400)
    if page<1:abort(400)
    params={};where=predicate(entity,params)
    if q:
        where+=" AND ((body->'metadata'->>'title') ILIKE :query OR rid ILIKE :query OR (body->'custom_fields')::text ILIKE :query)"
        params['query']='%'+q+'%'
    if stage=='published':where+=' AND published=1'
    elif stage=='draft':where+=' AND draft=1 AND published=0'
    elif stage=='editing':where+=' AND draft=1 AND published=1'
    total=db.session.execute(text(EFFECTIVE+'SELECT count(*) FROM effective WHERE '+where),params).scalar_one()
    pages=max(1,math.ceil(total/20));page=min(page,pages);params.update(limit=20,offset=(page-1)*20)
    sql="SELECT rid,published,draft,body->'metadata'->>'title' title,body->'metadata'->>'publication_date' date FROM effective WHERE "+where+" ORDER BY lower(body->'metadata'->>'title'),rid LIMIT :limit OFFSET :offset"
    rows=[dict(r) for r in db.session.execute(text(EFFECTIVE+sql),params).mappings()]
    catalogue={row['id']:row for row in tools()}
    return render_template('semantic-ui/argiloteca/admin_entity.html',title=tr(*spec['label']),entity=entity,spec=spec,
                           rows=rows,total=total,page=page,pages=pages,q=q,stage=stage,
                           entity_tools=[catalogue[key] for key in spec['tools'] if key in catalogue])


@blueprint.post('/geocode')
def geocode():
    """Only an explicitly submitted place name leaves this private UI."""
    from pathlib import Path
    import sqlite3
    from flask_wtf.csrf import validate_csrf, ValidationError, CSRFError
    from .geocoding import lookup, LookupError
    try:
        validate_csrf(request.headers.get('X-CSRFToken') or request.form.get('csrf_token'))
    except ValidationError as error:
        raise CSRFError(error.args[0])
    try:
        if request.content_length and request.content_length > 4096: abort(413)
        result = lookup(request.form.get('place', ''),
            current_app.config.get('ARGILOTECA_GEOCODER_URL', 'https://photon.komoot.io/api/'),
            Path(current_app.config.get('ARGILOTECA_OPENALEX_QUEUE', Path(current_app.instance_path)/'data'))/'geocoding')
        return jsonify(result)
    except LookupError as error:
        response = jsonify(error=error.code)
        if error.status == 429: response.headers['Retry-After'] = '2'
        return response, error.status
    except (OSError, sqlite3.Error):
        current_app.logger.warning('Coordinate place lookup cache unavailable')
        return jsonify(error='unavailable'), 503
