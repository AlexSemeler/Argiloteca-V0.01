"""Synthetic data only. All declared scientific properties are exercised."""
from copy import deepcopy
from argiloteca.scientific.models import schema_bundle,BINDINGS
from argiloteca.scientific import PROFILE_FIELD,PROFILE_VERSION

def example(schema,key=''):
    schemas,_=schema_bundle()
    if '$ref' in schema:return example(schemas[schema['$ref']],key)
    if 'const' in schema:return schema['const']
    if 'enum' in schema:return schema['enum'][0]
    kind=schema.get('type')
    if isinstance(kind,list):kind=next(k for k in kind if k!='null')
    if kind=='object':return {k:example(v,k) for k,v in schema.get('properties',{}).items()} if 'properties' in schema else {'synthetic':False,'zero':0,'unicode':'ação < & >','nullable':None,'empty':'','values':[0,False,None]}
    if kind=='array':
        item=schema.get('items',{})
        if 'anyOf' in item:item=item['anyOf'][0]
        return [example(item,key)] if item else [0,False,None,{'value':'ação & < >'}]
    if kind=='boolean':return False
    if kind in {'integer','number'}:
        return schema.get('exclusiveMinimum',0)+1 if 'exclusiveMinimum' in schema else max(0,schema.get('minimum',0))
    if schema.get('format')=='date':return '2026-01-01'
    if schema.get('format')=='uri':return 'https://example.invalid/fixture'
    if key=='ano':return '2026'
    if key=='doi':return '10.1234/fixture'
    if schema.get('pattern'):
        return 'a'*64 if '64' in schema['pattern'] else 'fixture-0001'
    return 'SINTÉTICO — ação & < >'

def models():return {name:example(schema) for name,schema in schema_bundle()[0].items()}

def publication():
    cf={PROFILE_FIELD:PROFILE_VERSION,'arg:usos_descricao':'Unrelated field preserved / Campo preservado'}
    for field,(name,multiple) in BINDINGS.items():
        value=example(schema_bundle()[0][name]);cf[field]=[value] if multiple else value
    campaign=cf['arg:pesquisas_campo'][0];campaign['campanha_id']='QA-CAMP-0001'
    sample=cf['arg:amostras'][0];sample.update(codigo_amostra='0001',campanha_id='QA-CAMP-0001',latitude=0,longitude=-51.1234567890123,altitude_m=None,descricao_local='',unknown_enrichment={'do_not_export':'retained in DB'})
    second=deepcopy(sample);second['codigo_amostra']='0002';second['latitude']=1;cf['arg:amostras'].append(second)
    analysis=cf['arg:analises'][0];analysis.update(analise_id='QA-A-0001',codigo_amostra='0001',metodo='drx')
    analysis['metodo_analitico']['tipo']='drx'
    cf['arg:composicao_quimica_global'].update(codigo_amostra='0001',analise_id='QA-A-0001',SiO2=0,Al2O3=12.3456789012345,FeO=None)
    mineral=cf['arg:argilominerais'][0];mineral.update(nome='Kaolinite',nome_cientifico_padronizado='Kaolinite',codigo_amostra='0001',latitude=0)
    second=deepcopy(mineral);second.update(nome='Illite',nome_cientifico_padronizado='Illite',codigo_amostra='0002',latitude=1);cf['arg:argilominerais'].append(second)
    drx=cf['arg:pacotes_analiticos'][0]['items'][0];drx.update(analise_id='QA-A-0001',codigo_amostra='0001',raw_sha256='a'*64)
    cf['arg:pacotes_analiticos'][0]['items'].append({'synthetic':True,'zero':0,'flag':False,'nullable':None})
    return {'metadata':{'title':'SINTÉTICO — integração científica Argiloteca & < >','publication_date':'2026-01-01','resource_type':{'id':'dataset'},'creators':[{'person_or_org':{'type':'personal','family_name':'Synthetic','given_name':'Argiloteca'}}]},'files':{'enabled':False},'access':{'record':'public','files':'public'},'custom_fields':cf}
