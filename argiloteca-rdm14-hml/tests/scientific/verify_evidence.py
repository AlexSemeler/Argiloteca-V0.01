import sys,json
from pathlib import Path
from copy import deepcopy
sys.path.insert(0,'/skill/scripts')
sys.path.insert(0,'/tests')
from verify_oai import verify
from lxml import etree
root=Path('/evidence');schema=Path('/schemas/argiloteca-v1.xsd');ns='https://127.0.0.1:5101/schemas/argiloteca/v1/';url=ns+'argiloteca.xsd';official=Path('/skill/assets/oai/OAI-PMH.xsd');reports={}
import shutil
temp=Path('/tmp/oai-validation-xsd');temp.mkdir()
for p in Path('/aux').glob('*.xsd'):shutil.copy(p,temp/p.name)
shutil.copy(schema,temp/'argiloteca-v1.xsd')
combined=temp/'combined.xsd'
combined.write_text('<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="'+ns+'"><xs:include schemaLocation="argiloteca-v1.xsd"/><xs:import namespace="http://www.openarchives.org/OAI/2.0/oai_dc/" schemaLocation="oai_dc.xsd"/></xs:schema>')
schema=combined
for label,verb in [('mixed-records','ListRecords'),('all-records','ListRecords'),('mixed-identifiers','ListIdentifiers'),('all-sets','ListSets')]:
 reports[label]=verify(sorted((root/'oai'/label).glob('page-*.xml')),official,schema,ns,verb=verb,prefix='argiloteca',schema_url=url)
for name,verb,prefix in [('identify','Identify',None),('formats','ListMetadataFormats','argiloteca'),('get-scientific','GetRecord','argiloteca'),('get-legacy','GetRecord','argiloteca'),('get-files_restricted','GetRecord','argiloteca')]:
 reports[name]=verify([root/'oai'/(name+'.xml')],official,schema,ns,verb=verb,prefix=prefix,schema_url=url)
for name,error in [('restricted','idDoesNotExist'),('draft','idDoesNotExist'),('unsupported','cannotDisseminateFormat')]:
 reports[name]=verify([root/'oai'/(name+'.xml')],official,schema,ns,allow_error=error)
# Discriminating XPath values are asserted independently of the serializer.
N={'o':'http://www.openarchives.org/OAI/2.0/','a':ns,'xsi':'http://www.w3.org/2001/XMLSchema-instance'}
tree=etree.parse(str(root/'oai/get-scientific.xml'))
assert tree.xpath('string(//a:amostras/a:item[1]/a:codigo_amostra)',namespaces=N)=='0001'
assert tree.xpath('string(//a:amostras/a:item[1]/a:latitude)',namespaces=N)=='0'
assert tree.xpath('string(//a:amostras/a:item[1]/a:altitude_m/@xsi:nil)',namespaces=N)=='true'
assert tree.xpath('string(//a:referencias_drx_webmineral/a:item/a:has_drx_reference)',namespaces=N)=='false'
assert tree.xpath('string(//a:composicao_quimica_global/a:Al2O3)',namespaces=N)=='12.3456789012345'
assert tree.xpath('string(//a:amostras/a:item[1]/a:observacoes_campo)',namespaces=N)=='Updated scientific field only / Campo atualizado'
assert not tree.xpath('//a:unknown_enrichment',namespaces=N)
reports['independent XPath']={'zero':True,'false':True,'null':True,'precision':True,'leading_zero_identifier':True,'metadata_only_update_value':True,'unknowns_filtered':True}
from xml_roundtrip import typed,normalize,local
from fixtures import publication
from argiloteca.scientific.models import BINDINGS,schema_bundle
expected=publication()['custom_fields'];expected={k:v for k,v in expected.items() if k in BINDINGS}
for sample in expected['arg:amostras']:sample.pop('unknown_enrichment',None)
expected['arg:amostras'][0]['observacoes_campo']='Updated scientific field only / Campo atualizado'
actual={}
content=tree.find('.//{http://www.openarchives.org/OAI/2.0/}metadata')[0]
for node in content:
 field='arg:'+local(node)
 if field in BINDINGS:
  name,multiple=BINDINGS[field];definition={'type':'array','items':{'$ref':name}} if multiple else {'$ref':name}
  actual[field]=typed(node,definition,schema_bundle()[0])
assert normalize(expected)==actual,'Full scientific OAI values differ from independently decoded source'
reports['full scientific roundtrip']={'all_eight_blocks':True,'all_declared_nested_properties':True}
if (root/'persisted-final.json').exists() and (root/'final-record.xml').exists():
 from argiloteca.scientific.xml import compiled_xsd
 final=etree.parse(str(root/'final-record.xml')).getroot();compiled_xsd().assertValid(final)
 source=json.loads((root/'persisted-final.json').read_text())['custom_fields']
 expected={k:v for k,v in source.items() if k in BINDINGS}
 for sample in expected.get('arg:amostras',[]):sample.pop('unknown_enrichment',None)
 actual={}
 for node in final:
  field='arg:'+local(node)
  if field in BINDINGS:
   name,multiple=BINDINGS[field];definition={'type':'array','items':{'$ref':name}} if multiple else {'$ref':name}
   actual[field]=typed(node,definition,schema_bundle()[0])
 assert normalize(expected)==actual,'Final XML differs from independently read committed SQL'
 reports['final committed SQL to XML']={'status':'valid','all_eight_blocks':True,'typed_value_comparison':True}
(root/'oai-validation.json').write_text(json.dumps(reports,indent=2));print(json.dumps({k:v.get('status',True) for k,v in reports.items()},indent=2))
