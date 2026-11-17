"""Authenticated authoring through native services, public schemas/search/XML."""
import json
from copy import deepcopy
from functools import wraps
from flask import Blueprint,Response,abort,current_app,g,jsonify,render_template,request
from flask_babel import get_locale
from flask_login import current_user,login_required
from flask_wtf.csrf import generate_csrf,validate_csrf,CSRFError
from wtforms.validators import ValidationError as CSRFValidationError
from invenio_rdm_records.proxies import current_rdm_records_service as service
from invenio_records_resources.services.errors import PermissionDenied,RevisionIdMismatchError
from invenio_pidstore.errors import PIDDoesNotExistError
from marshmallow import ValidationError
from . import PROFILE_FIELD,PROFILE_VERSION,SEARCH_FIELD
from .models import BINDINGS,schema_bundle,validate_model
from .xml import build_xsd,configured_xml
from lxml import etree


def _text(en,pt):return pt if get_locale().language=='pt' else en


def _body():
    data=request.get_json()
    if not isinstance(data,dict):raise ValidationError({'_schema':['Expected a JSON object.']})
    return data


def _result(result):
    data=result.to_dict()
    return {'record':data,'revision_id':result._record.revision_id,'errors':data.get('errors',[])}


def _endpoint(func):
    @wraps(func)
    def call(*args,**kwargs):
        try:return func(*args,**kwargs)
        except ValidationError as error:return jsonify({'errors':error.messages,'message':_text('Validation failed.','Falha de validação.')}),422
        except PermissionDenied:return jsonify({'message':_text('Permission denied.','Permissão negada.')}),403
        except RevisionIdMismatchError:return jsonify({'message':_text('This draft changed. Reload before saving.','Este rascunho mudou. Recarregue antes de salvar.')}),409
        except PIDDoesNotExistError:return jsonify({'message':_text('Record not found.','Registro não encontrado.')}),404
    return call


def create_blueprint(app):
    bp=Blueprint('argiloteca_scientific',__name__,template_folder='../templates')
    from .restricted_review import register_review
    register_review(bp, app)
    from .drx_link_views import register_links
    register_links(bp)
    from .catalog_views import register_catalog
    register_catalog(bp)
    from .connections_views import register_connections
    register_connections(bp)
    from .vocabulary_admin import register_vocabularies
    register_vocabularies(bp)

    @app.before_request
    def protect_replaced_manifests():
        # Once a package is migrated, the old static manifest cannot bypass its
        # SQL link/access policy or expose pre-anonymization names and paths.
        prefix = '/argiloteca/static/data/analytical_packages/'
        if request.path.startswith(prefix):
            pid = request.path.removeprefix(prefix).split('/', 1)[0]
            from .drx_links import DRXRecordLink
            from .restricted_review import can_review
            if DRXRecordLink.query.filter_by(record_id=pid).first() and not can_review():
                abort(404)
            g.drx_legacy_manifest = True

    @app.after_request
    def prevent_manifest_cache(response):
        if getattr(g, 'drx_legacy_manifest', False):
            response.headers['Cache-Control'] = 'private, no-store'
            response.vary.add('Cookie')
        return response

    @bp.before_request
    def protect_writes():
        # Invenio disables Flask-WTF's global default check. These session-based
        # form endpoints must invoke it explicitly, just like native resources.
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            try:validate_csrf(request.headers.get('X-CSRFToken') or request.form.get('csrf_token'))
            except CSRFValidationError as error:raise CSRFError(error.args[0])

    def page(record=None,read_only=False):
        initial=record.to_dict() if record else {'metadata':{'title':'','publication_date':'','resource_type':{'id':'dataset'},'creators':[{'person_or_org':{'type':'personal','family_name':'','given_name':''}}]},'access':{'record':'public','files':'public'},'files':{'enabled':False},'custom_fields':{PROFILE_FIELD:PROFILE_VERSION}}
        from invenio_vocabularies.proxies import current_service as vocabularies
        from .install import METHODS
        resource_types=vocabularies.search(g.identity,type='resourcetypes',params={'size':100}).to_dict()['hits']['hits']
        config={'resource_types':[{ 'id':r['id'],'label':r.get('title',{}).get(get_locale().language,r['id'])} for r in resource_types], 'method_labels':{key:title[1 if get_locale().language=='pt' else 0] for key,title in METHODS.items()},'record':initial,'revision_id':record._record.revision_id if record else None,'read_only':read_only,'can_edit':bool(read_only and record and current_user.is_authenticated and service.check_permission(g.identity,'edit',record=record._record)),'profile_version':PROFILE_VERSION,'profile_field':PROFILE_FIELD,'bindings':BINDINGS,'schemas':schema_bundle()[0],'save_url':('/scientific/drafts/'+initial['id']) if record else '/scientific/drafts','csrf_token':generate_csrf(),'language':get_locale().language}
        return render_template('semantic-ui/argiloteca/scientific_deposit.html',science_config=config,st=_text)

    @bp.route('/scientific/deposit')
    @login_required
    def new():return page()

    @bp.route('/scientific/deposit/<id_>')
    @login_required
    @_endpoint
    def edit(id_):
        try:return page(service.read_draft(g.identity,id_))
        except PIDDoesNotExistError:return page(service.read(g.identity,id_),read_only=True)

    @bp.route('/scientific/records/<id_>')
    @_endpoint
    def detail(id_):return page(service.read(g.identity,id_),read_only=True)

    @bp.route('/scientific/records/<id_>/edit',methods=['POST'])
    @login_required
    @_endpoint
    def begin_edit(id_):return jsonify(_result(service.edit(g.identity,id_)))

    @bp.route('/scientific/drafts',methods=['POST'])
    @login_required
    @_endpoint
    def create():
        data=_body();payload={k:deepcopy(data[k]) for k in ['metadata','access','files','custom_fields'] if k in data}
        return jsonify(_result(service.create(g.identity,payload))),201

    @bp.route('/scientific/drafts/<id_>',methods=['PUT'])
    @login_required
    @_endpoint
    def save(id_):
        body=_body();draft=service.read_draft(g.identity,id_);data=draft.to_dict()
        payload={k:deepcopy(data[k]) for k in ['metadata','access','files','pids','custom_fields'] if k in data}
        # A scientific edit never replaces unrelated extension fields. Deletion
        # is explicit, restricted to these scientific blocks and visible in UI.
        allowed={*BINDINGS,PROFILE_FIELD}
        patch=body.get('custom_fields',{})
        if not isinstance(patch,dict) or set(patch)-allowed:raise ValidationError({'custom_fields':['Unknown field in scientific edit.']})
        payload.setdefault('custom_fields',{}).update(deepcopy(patch))
        removed=body.get('remove_fields',[])
        if not isinstance(removed,list):raise ValidationError({'remove_fields':['Expected a list.']})
        for key in removed:
            if key not in allowed:raise ValidationError({'remove_fields':['Only scientific fields may be removed.']})
            payload['custom_fields'].pop(key,None)
        if 'metadata' in body:payload['metadata']=deepcopy(body['metadata'])
        return jsonify(_result(service.update_draft(g.identity,id_,payload,revision_id=body.get('revision_id'))))

    @bp.route('/scientific/drafts/<id_>/publish',methods=['POST'])
    @login_required
    @_endpoint
    def publish(id_):
        body=_body()
        draft=service.read_draft(g.identity,id_)
        # RDM 32.3's publish override has no revision_id parameter. Use its
        # native revision check before invoking the native publication method.
        service.check_revision_id(draft._record,body.get('revision_id'))
        return jsonify(_result(service.publish(g.identity,id_)))

    @bp.route('/scientific/models')
    def models():return jsonify({'profile_version':PROFILE_VERSION,'schemas':schema_bundle()[0],'bindings':BINDINGS})

    @bp.route('/scientific/validate/<name>',methods=['POST'])
    @login_required
    def validate(name):
        if name not in schema_bundle()[0]:abort(404)
        errors=validate_model(name,request.get_json())
        return jsonify({'valid':not errors,'errors':errors}),422 if errors else 200

    @bp.route('/schemas/argiloteca/v1/')
    def profile():return jsonify({'profile_version':PROFILE_VERSION,'namespace':current_app.config['ARGILOTECA_XML_NAMESPACE'],'schema':current_app.config['ARGILOTECA_XML_SCHEMA_URL'],'status':'homologation; external publication not established'})

    @bp.route('/schemas/argiloteca/v1/argiloteca.xsd')
    def xsd():return Response(build_xsd(current_app.config['ARGILOTECA_XML_NAMESPACE']),mimetype='application/xml')

    @bp.route('/scientific/records/<id_>/export')
    @_endpoint
    def export(id_):
        record=service.read(g.identity,id_)
        return Response(etree.tostring(configured_xml(record.to_dict()),encoding='utf-8',xml_declaration=True,pretty_print=True),mimetype='application/xml',headers={'Content-Disposition':f'attachment; filename="{id_}-argiloteca.xml"'})

    @bp.route('/scientific/search')
    def search():return render_template('semantic-ui/argiloteca/scientific_search.html',st=_text)

    @bp.route('/scientific/search.json')
    @_endpoint
    def search_json():
        params={key:request.args[key] for key in ['q','p','size','arg_profile','arg_sample','arg_campaign','arg_method','arg_laboratory','arg_mineral','arg_mineral_sample','arg_mineral_latitude'] if key in request.args}
        result=service.search(g.identity,params=params)
        data=result.to_dict()
        data['scientific_facets']={key:value for key,value in result._results.aggregations.to_dict().items() if key.startswith('arg_')}
        return Response(json.dumps(data,default=str,ensure_ascii=False),mimetype='application/json')

    return bp
