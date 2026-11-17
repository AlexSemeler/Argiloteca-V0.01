"""Schema-derived, versioned XML with typed scientific elements and native adapters."""
from decimal import Decimal
from functools import lru_cache
from copy import deepcopy
from lxml import etree
from flask import current_app, g
from invenio_pidstore.errors import PIDDoesNotExistError
from . import PROFILE_FIELD, PROFILE_VERSION, SEARCH_FIELD
from .models import BINDINGS, schema_bundle, validator, public_scientific

XS='http://www.w3.org/2001/XMLSchema'
XSI='http://www.w3.org/2001/XMLSchema-instance'
DEFAULT_NAMESPACE='https://127.0.0.1:5101/schemas/argiloteca/v1/'
DEFAULT_SCHEMA_URL=DEFAULT_NAMESPACE+'argiloteca.xsd'


def _type_name(filename):return filename.removeprefix('arg_').removesuffix('.schema.json')+'Type'


def _resolved(schema):
    return schema_bundle()[0][schema['$ref']] if '$ref' in schema else schema


def _alternatives(schema):
    candidates=schema.get('anyOf',[])
    if candidates and all(set(candidate)=={'required'} for candidate in candidates):
        return [candidate['required'] for candidate in candidates]
    return []


def _ordered_keys(schema,value):
    """Factor presence alternatives into a deterministic, XSD-1.0-valid order."""
    groups=_alternatives(schema);conditional=[]
    for group in groups:
        for key in group:
            if key not in conditional:conditional.append(key)
    selected=next((group for group in groups if all(key in value for key in group)),[])
    # For supplied models the first alternative is a name/identifier, the last
    # may be a coordinate pair. All present conditional properties remain intact.
    ordered=[key for key in conditional if key in value]
    return ordered+[key for key in schema.get('properties',{}) if key not in conditional and key in value]


def build_xsd(namespace=DEFAULT_NAMESPACE):
    schemas,_=schema_bundle()
    def x(tag,**attrs):return etree.Element('{'+XS+'}'+tag,**{k:str(v) for k,v in attrs.items()})
    document=x('schema',targetNamespace=namespace,elementFormDefault='qualified')
    document.nsmap  # namespace bindings are supplied on the outer element below.
    document=etree.Element('{'+XS+'}schema',nsmap={'xs':XS,'a':namespace},targetNamespace=namespace,elementFormDefault='qualified')
    generic=etree.SubElement(document,'{'+XS+'}complexType',name='GenericValue',mixed='true')
    choice=etree.SubElement(generic,'{'+XS+'}choice',minOccurs='0',maxOccurs='unbounded')
    for name in ['property','item']:etree.SubElement(choice,'{'+XS+'}element',name=name,type='a:GenericValue')
    etree.SubElement(generic,'{'+XS+'}attribute',name='name',type='xs:string')
    attr=etree.SubElement(generic,'{'+XS+'}attribute',name='kind',use='required')
    simple=etree.SubElement(attr,'{'+XS+'}simpleType');restriction=etree.SubElement(simple,'{'+XS+'}restriction',base='xs:string')
    for kind in ['object','array','string','number','boolean','null']:etree.SubElement(restriction,'{'+XS+'}enumeration',value=kind)

    def element(name,definition,required=False):
        node=x('element',name=name,minOccurs='1' if required else '0')
        type_value=definition.get('type')
        if isinstance(type_value,list) and 'null' in type_value:node.set('nillable','true')
        if '$ref' in definition:
            node.set('type','a:'+_type_name(definition['$ref']));return node
        if isinstance(type_value,list):type_value=next((v for v in type_value if v!='null'),'string')
        if type_value=='object' or 'properties' in definition:
            properties=definition.get('properties')
            if properties is None:
                node.set('type','a:GenericValue');return node
            node.append(object_type(definition));return node
        if type_value=='array':
            compound=x('complexType');sequence=x('sequence');compound.append(sequence);node.append(compound)
            item=definition.get('items',{})
            if 'anyOf' in item and any('$ref' in option for option in item['anyOf']):
                entry=x('element',name='item',minOccurs=definition.get('minItems',0),maxOccurs=definition.get('maxItems','unbounded'))
                subtype=x('complexType');option=x('choice');subtype.append(option);entry.append(subtype)
                for candidate in item['anyOf']:
                    branch=element('drx' if '$ref' in candidate else 'generic',candidate,True);option.append(branch)
            else:
                entry=element('item',item,False);entry.set('minOccurs',str(definition.get('minItems',0)));entry.set('maxOccurs',str(definition.get('maxItems','unbounded')))
            sequence.append(entry);return node
        if not type_value:
            node.set('type','a:GenericValue');return node
        base={'string':'xs:string','integer':'xs:integer','number':'xs:decimal','boolean':'xs:boolean'}.get(type_value,'xs:string')
        if definition.get('format')=='date':base='xs:date'
        restrictions=[]
        for key,target in [('minLength','minLength'),('maxLength','maxLength'),('minimum','minInclusive'),('maximum','maxInclusive'),('exclusiveMinimum','minExclusive'),('exclusiveMaximum','maxExclusive')]:
            if key in definition:restrictions.append((target,definition[key]))
        if 'pattern' in definition:restrictions.append(('pattern',definition['pattern'].removeprefix('^').removesuffix('$')))
        for value in definition.get('enum',[]):restrictions.append(('enumeration',value))
        if 'const' in definition:restrictions.append(('enumeration',definition['const']))
        if restrictions:
            simple=x('simpleType');restriction=x('restriction',base=base);simple.append(restriction);node.append(simple)
            for kind,value in restrictions:restriction.append(x(kind,value=value))
        else:node.set('type',base)
        return node

    def object_type(definition,name=None):
        node=x('complexType',**({'name':name} if name else {}));sequence=x('sequence');node.append(sequence)
        properties=definition.get('properties',{});groups=_alternatives(definition)
        conditional=[]
        for group in groups:
            for key in group:
                if key not in conditional:conditional.append(key)
        if groups:
            choice=x('choice');sequence.append(choice)
            for index,group in enumerate(groups):
                branch=x('sequence');choice.append(branch)
                # Earlier alternatives are excluded by branch ordering; the
                # remaining alternatives may coexist, matching JSON anyOf.
                earlier={key for prior in groups[:index] for key in prior}
                for key in conditional:
                    if key not in earlier:branch.append(element(key,properties[key],key in group))
        for key,value in properties.items():
            if key not in conditional:sequence.append(element(key,value,key in definition.get('required',[])))
        # Additional properties have a structured representation where explicitly
        # exported (native metadata and legacy blocks); named scientific fields
        # use a public allowlist and do not emit undeclared enrichments.
        if definition.get('additionalProperties',True):
            extra=x('element',name='extensions',type='a:GenericValue',minOccurs='0');sequence.append(extra)
        return node

    for filename,definition in schemas.items():
        if filename=='arg_payload_publicacao.schema.json':continue
        document.append(object_type(definition,_type_name(filename)))
    metadata=schemas['arg_payload_publicacao.schema.json']['properties']['metadata']
    document.append(object_type(metadata,'NativeMetadataType'))
    root=x('element',name='argiloteca');compound=x('complexType');sequence=x('sequence');compound.append(sequence);root.append(compound)
    sequence.append(x('element',name='metadata',type='a:NativeMetadataType'))
    for field,(filename,multiple) in BINDINGS.items():
        definition={'type':'array','items':{'$ref':filename}} if multiple else {'$ref':filename}
        sequence.append(element(field.removeprefix('arg:'),definition))
    sequence.append(x('element',name='legacy',type='a:GenericValue',minOccurs='0'))
    for name,kind in [('recordId','xs:string'),('profileVersion','xs:string'),('profiled','xs:boolean')]:
        compound.append(x('attribute',name=name,type=kind,use='required'))
    document.append(root)
    return etree.tostring(document,encoding='utf-8',xml_declaration=True,pretty_print=True)


def _scalar(value):
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(int,float,Decimal)):return format(Decimal(str(value)),'f')
    return str(value)


def _generic(element,value,namespace):
    if value is None:element.set('kind','null')
    elif isinstance(value,dict):
        element.set('kind','object')
        for key,item in value.items():
            child=etree.SubElement(element,'{'+namespace+'}property',name=str(key));_generic(child,item,namespace)
    elif isinstance(value,list):
        element.set('kind','array')
        for item in value:_generic(etree.SubElement(element,'{'+namespace+'}item'),item,namespace)
    else:
        element.set('kind','boolean' if isinstance(value,bool) else 'number' if isinstance(value,(int,float,Decimal)) else 'string')
        element.text=_scalar(value)


def _emit(parent,name,value,schema,namespace,extras=False):
    node=etree.SubElement(parent,'{'+namespace+'}'+name)
    if value is None:
        if not schema.get('type') and '$ref' not in schema:_generic(node,value,namespace)
        else:node.set('{'+XSI+'}nil','true')
        return node
    schema=_resolved(schema);kind=schema.get('type')
    if isinstance(kind,list):kind=next((k for k in kind if k!='null'),None)
    if isinstance(value,dict):
        if 'properties' not in schema:_generic(node,value,namespace);return node
        for key in _ordered_keys(schema,value):_emit(node,key,value[key],schema['properties'][key],namespace,extras)
        unknown={key:val for key,val in value.items() if key not in schema['properties']}
        if extras and unknown:_generic(etree.SubElement(node,'{'+namespace+'}extensions'),unknown,namespace)
    elif isinstance(value,list):
        item=schema.get('items',{})
        for row in value:
            if 'anyOf' in item and any('$ref' in choice for choice in item['anyOf']):
                wrapper=etree.SubElement(node,'{'+namespace+'}item')
                reference=next(choice for choice in item['anyOf'] if '$ref' in choice)
                is_drx=validator(reference['$ref']).is_valid(row)
                _emit(wrapper,'drx' if is_drx else 'generic',row,reference if is_drx else {'type':'object'},namespace,extras)
            else:_emit(node,'item',row,item,namespace,extras)
    elif not kind:_generic(node,value,namespace)
    else:node.text=_scalar(value)
    return node


@lru_cache(maxsize=4)
def compiled_xsd(namespace=DEFAULT_NAMESPACE):
    return etree.XMLSchema(etree.fromstring(build_xsd(namespace)))


def record_to_xml(data,namespace=None,schema_url=None):
    namespace=namespace or DEFAULT_NAMESPACE;schema_url=schema_url or DEFAULT_SCHEMA_URL
    custom=data.get('custom_fields') or {};profiled=custom.get(PROFILE_FIELD)==PROFILE_VERSION
    root=etree.Element('{'+namespace+'}argiloteca',nsmap={None:namespace,'xsi':XSI},recordId=str(data.get('id','')),profileVersion=PROFILE_VERSION,profiled='true' if profiled else 'false')
    root.set('{'+XSI+'}schemaLocation',namespace+' '+schema_url)
    metadata=schema_bundle()[0]['arg_payload_publicacao.schema.json']['properties']['metadata']
    _emit(root,'metadata',data.get('metadata',{}),metadata,namespace,True)
    if profiled:
        for field,value in public_scientific(custom).items():
            filename,multiple=BINDINGS[field]
            definition={'type':'array','items':{'$ref':filename}} if multiple else {'$ref':filename}
            _emit(root,field.removeprefix('arg:'),value,definition,namespace)
    else:
        from ..custom_fields import TEXT_FIELDS,DOUBLE_FIELDS,LIST_OBJECT_FIELDS,OBJECT_FIELDS
        legacy={key:deepcopy(value) for key,value in custom.items() if key in {*TEXT_FIELDS,*DOUBLE_FIELDS,*LIST_OBJECT_FIELDS,*OBJECT_FIELDS}}
        # A legacy record need not migrate all fourteen models merely to expose
        # its validated, persisted DRX bundle. Keep the historical blocks intact.
        packages = [p for p in custom.get('arg:pacotes_analiticos', [])
                    if p.get('pacote_id') == 'drx-links-' + str(data.get('id', ''))]
        if packages:
            for package in packages:
                validator('arg_pacote_analitico.schema.json').validate(package)
            _emit(root, 'pacotes_analiticos', packages,
                  {'type': 'array', 'items': {'$ref': 'arg_pacote_analitico.schema.json'}}, namespace)
            remaining = [p for p in legacy.get('arg:pacotes_analiticos', []) if p not in packages]
            if remaining:
                legacy['arg:pacotes_analiticos'] = remaining
            else:
                legacy.pop('arg:pacotes_analiticos', None)
        connections = public_scientific(custom).get('arg:conexoes_cientificas')
        if connections is not None:
            _emit(root, 'conexoes_cientificas', connections,
                  {'type':'array','items':{'$ref':'arg_conexao_cientifica.schema.json'}}, namespace)
        if legacy:_generic(etree.SubElement(root,'{'+namespace+'}legacy'),legacy,namespace)
    compiled_xsd(namespace).assertValid(root)
    return root


def configured_xml(data):
    return record_to_xml(data,current_app.config['ARGILOTECA_XML_NAMESPACE'],current_app.config['ARGILOTECA_XML_SCHEMA_URL'])


def argiloteca_etree(pid,record):
    from invenio_rdm_records.proxies import current_rdm_records_service
    source=record['_source']
    if source.get('access',{}).get('record')!='public':raise PIDDoesNotExistError('recid',None)
    # Read the canonical persisted record for both GetRecord and ListRecords.
    # Index-only projections never substitute for the original scientific data.
    item=current_rdm_records_service.read(g.identity,source['id'])
    return configured_xml(item.to_dict())


class ArgilotecaXMLSerializer:
    def __init__(self,**kwargs):pass
    def serialize_object(self,obj):
        return etree.tostring(configured_xml(obj),encoding='utf-8',xml_declaration=True,pretty_print=True).decode('utf-8')
