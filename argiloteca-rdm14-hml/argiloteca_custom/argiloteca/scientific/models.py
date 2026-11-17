"""The supplied schemas are preserved, resolved offline and never inferred from examples."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource
from . import PROFILE_FIELD, PROFILE_VERSION, SEARCH_FIELD

SCHEMA_DIR = Path(__file__).parent / 'schemas'
FORMAT_CHECKER=FormatChecker()
if 'uri' not in FORMAT_CHECKER.checkers:
    raise RuntimeError('Scientific schemas require the declared rfc3986-validator dependency.')
# Existing canonical blocks are retained. The independent reference schema gets
# an explicit optional reference block; it is not a new operational entity.
BINDINGS = {
    'arg:termo_catalogo': ('arg_termo_catalogo.schema.json', False),
    'arg:pesquisas_campo': ('arg_pesquisa_campo.schema.json', True),
    'arg:amostras': ('arg_amostra.schema.json', True),
    'arg:analises': ('arg_analise.schema.json', True),
    'arg:composicao_quimica_global': ('arg_geoquimica.schema.json', False),
    'arg:argilominerais': ('arg_argilomineral.schema.json', True),
    'arg:publicacoes_relacionadas': ('arg_publicacao.schema.json', True),
    'arg:pacotes_analiticos': ('arg_pacote_analitico.schema.json', True),
    'arg:referencias_drx_webmineral': ('arg_referencia_drx_webmineral.schema.json', True),
    'arg:conexoes_cientificas': ('arg_conexao_cientifica.schema.json', True),
}


def _no_remote(uri):
    raise NoSuchResource(ref=uri)


@lru_cache(maxsize=1)
def schema_bundle():
    schemas = {p.name: json.loads(p.read_text()) for p in SCHEMA_DIR.glob('*.schema.json')}
    registry = Registry(retrieve=_no_remote)
    for name, schema in schemas.items():
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
    return schemas, registry


def validator(name):
    schemas, registry = schema_bundle()
    return Draft202012Validator(schemas[name], registry=registry, format_checker=FORMAT_CHECKER)


def pointer(parts):
    return ''.join('/'+str(p).replace('~','~0').replace('/','~1') for p in parts)


def validate_model(name, value):
    return [{'path':pointer(e.absolute_path),'rule':e.validator,'message':e.message}
            for e in sorted(validator(name).iter_errors(value),key=lambda e:tuple(map(str,e.absolute_path)))]


def scientific_errors(custom_fields):
    """Strict publish validation for explicitly versioned records only.

    Drafts keep their values and receive errors; the native publish service
    invokes the same schema strictly. Legacy records are never auto-promoted.
    """
    connection_errors = []
    if 'arg:conexoes_cientificas' in custom_fields and PROFILE_FIELD not in custom_fields:
        links = custom_fields['arg:conexoes_cientificas']
        if not isinstance(links, list):
            connection_errors.append({'parts':['arg:conexoes_cientificas'], 'message':'Expected a list / Esperada uma lista.'})
        else:
            for index, link in enumerate(links):
                for error in validator('arg_conexao_cientifica.schema.json').iter_errors(link):
                    connection_errors.append({'parts':['arg:conexoes_cientificas', index, *error.absolute_path], 'message':error.message})
    if 'arg:termo_catalogo' in custom_fields and PROFILE_FIELD not in custom_fields:
        return [{'parts':[PROFILE_FIELD], 'message':'Catalog terms require a versioned scientific profile / Termos do catálogo exigem perfil científico versionado.'}]
    if PROFILE_FIELD not in custom_fields:
        return connection_errors
    errors = []
    if custom_fields.get(PROFILE_FIELD) != PROFILE_VERSION:
        errors.append({'parts':[PROFILE_FIELD],'message':'Unsupported scientific profile version / Versão do perfil não suportada.'})
    for field, (schema_name, multiple) in BINDINGS.items():
        if field not in custom_fields:
            continue
        values = custom_fields[field]
        if multiple and not isinstance(values,list):
            errors.append({'parts':[field],'message':'Expected a list / Esperada uma lista.'});continue
        if not multiple:values=[values]
        for index,value in enumerate(values):
            prefix=[field,index] if multiple else [field]
            for error in validator(schema_name).iter_errors(value):
                errors.append({'parts':prefix+list(error.absolute_path),'message':error.message})
    # Relations already represented in the existing local scientific model.
    # They are profile rules, not assertions made by the JSON Schema standard.
    def rows(field):
        value=custom_fields.get(field,[])
        return [r for r in value if isinstance(r,dict)] if isinstance(value,list) else []
    def identifiers(field,key):
        result=set()
        for n,row in enumerate(rows(field)):
            value=row.get(key)
            if isinstance(value,str) and value:
                if value in result:errors.append({'parts':[field,n,key],'message':'Duplicate identifier / Identificador duplicado.'})
                result.add(value)
        return result
    campaigns=identifiers('arg:pesquisas_campo','campanha_id')
    samples=identifiers('arg:amostras','codigo_amostra')
    analyses=identifiers('arg:analises','analise_id')
    for index,sample in enumerate(rows('arg:amostras')):
        if isinstance(sample.get('campanha_id'),str) and sample['campanha_id'] and sample['campanha_id'] not in campaigns:
            errors.append({'parts':['arg:amostras',index,'campanha_id'],'message':'Unknown campaign in this record / Campanha não encontrada neste registro.'})
    for field in ['arg:analises','arg:argilominerais']:
        for index,row in enumerate(rows(field)):
            if isinstance(row.get('codigo_amostra'),str) and row['codigo_amostra'] and row['codigo_amostra'] not in samples:
                errors.append({'parts':[field,index,'codigo_amostra'],'message':'Unknown sample in this record / Amostra não encontrada neste registro.'})
    chemistry=custom_fields.get('arg:composicao_quimica_global')
    if isinstance(chemistry,dict):
        for key,known in [('codigo_amostra',samples),('analise_id',analyses)]:
            if isinstance(chemistry.get(key),str) and chemistry[key] and chemistry[key] not in known:
                errors.append({'parts':['arg:composicao_quimica_global',key],'message':'Unknown local reference / Referência local não encontrada.'})
    return errors


def marshmallow_errors(custom_fields):
    result={}
    for error in scientific_errors(custom_fields):
        target=result.setdefault('custom_fields',{})
        for part in error['parts'][:-1]:target=target.setdefault(part,{})
        target.setdefault(error['parts'][-1],[]).append(error['message'])
    return result


def projection(custom_fields):
    """Index-only projection: original blocks remain the sole persisted source."""
    result={'profile_version':custom_fields.get(PROFILE_FIELD) if isinstance(custom_fields.get(PROFILE_FIELD),str) else None,'samples':[],'analyses':[],'minerals':[],'chemistry':[]}
    term = custom_fields.get('arg:termo_catalogo')
    if isinstance(term, dict):
        result['catalog_slug'] = term.get('slug')
        result['catalog_status'] = term.get('situacao')
    def rows(field):
        value=custom_fields.get(field,[])
        return [r for r in value if isinstance(r,dict)] if isinstance(value,list) else []
    def select(row,names):
        return {target:row[source] for source,target in names if source in row and
                ((target in {'latitude','longitude'} and isinstance(row[source],(int,float)) and not isinstance(row[source],bool)) or
                 (target not in {'latitude','longitude'} and isinstance(row[source],str)))}
    for row in rows('arg:amostras'):
        result['samples'].append(select(row,[('codigo_amostra','code'),('campanha_id','campaign'),('latitude','latitude'),('longitude','longitude')]))
    for row in rows('arg:analises'):
        result['analyses'].append(select(row,[('analise_id','id'),('codigo_amostra','sample'),('metodo','method'),('laboratorio','laboratory')]))
    for row in rows('arg:argilominerais'):
        value=select(row,[('codigo_amostra','sample'),('grupo','group'),('latitude','latitude'),('longitude','longitude')])
        name=row.get('nome_cientifico_padronizado') or row.get('nome')
        if isinstance(name,str):value['name']=name
        result['minerals'].append(value)
    chemistry=custom_fields.get('arg:composicao_quimica_global')
    if isinstance(chemistry,dict):
        for oxide in ['SiO2','Al2O3','Fe2O3','FeO','MgO','CaO','K2O','Na2O','TiO2','MnO','P2O5','PF','LOI']:
            value=chemistry.get(oxide)
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                result['chemistry'].append({'sample':chemistry.get('codigo_amostra') if isinstance(chemistry.get('codigo_amostra'),str) else None,'oxide':oxide,'value':value})
    return result


def public_scientific(custom_fields):
    """Named schema properties are public; undeclared enrichments are not exported.

    Explicitly free-form schema objects retain structured contents. Confidential
    data must use the record access controls; the supplied models define no
    private fields. No names, values, identifiers or units are normalized here.
    """
    schemas,_=schema_bundle()
    def clean(value,schema):
        if '$ref' in schema:schema=schemas[schema['$ref'].split('#')[0]]
        if isinstance(value,list):
            item=schema.get('items',{})
            if 'anyOf' in item:
                return [clean(v,next((candidate for candidate in schema['items']['anyOf'] if _valid_candidate(candidate,v)),schema['items']['anyOf'][-1])) for v in value]
            return [clean(v,item) for v in value]
        if isinstance(value,dict):
            properties=schema.get('properties')
            if properties is None:return deepcopy(value)
            return {key:clean(val,properties[key]) for key,val in value.items() if key in properties and not properties[key].get('writeOnly')}
        return deepcopy(value)
    def _valid_candidate(candidate,value):
        if '$ref' in candidate:return validator(candidate['$ref']).is_valid(value)
        return Draft202012Validator(candidate).is_valid(value)
    return {field:([clean(row,schemas[name]) for row in value] if multiple and isinstance(value,list) else clean(value,schemas[name]))
            for field,(name,multiple) in BINDINGS.items() if field in custom_fields for value in [custom_fields[field]]}
