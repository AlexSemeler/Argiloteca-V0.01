"""Reproducible mapping for every declared source property and nested occurrence."""
import json,hashlib
from pathlib import Path
from argiloteca.scientific.models import schema_bundle,BINDINGS,pointer
from argiloteca.scientific import PROFILE_VERSION,PROFILE_FIELD,SEARCH_FIELD
schemas,_=schema_bundle();rows={}
def inventory(node,name,path=()):
    if not isinstance(node,dict):return
    for key,value in node.get('properties',{}).items():
        location=path+('properties',key)
        rows[(name,location)]={'schema':name,'schema_pointer':pointer(location),'field':key,'definition':value,'required_in_parent':key in node.get('required',[]),'storage':'native metadata/access/files or canonical custom_fields JSONB; no SQL columns added','widget':'structured schema-driven field; repeated arrays; explicit absence/null','units':value.get('unit',value.get('units','not specified by source; no conversion')),'destinations':[]}
        inventory(value,name,location)
    if isinstance(node.get('items'),dict):inventory(node['items'],name,path+('items',))
    for index,value in enumerate(node.get('anyOf',[])):inventory(value,name,path+('anyOf',index))
for name,definition in schemas.items():inventory(definition,name)
def bind(node,name,path,canonical,xml):
    if '$ref' in node:
        name=node['$ref'];node=schemas[name];path=()
    for key,child in node.get('properties',{}).items():
        location=path+('properties',key)
        row=rows[(name,location)]
        dest={'json_path':canonical+'/'+key,'xml_path':xml+'/a:'+key if xml else None,'search':'index-only nested projection for selected sample/analysis/mineral/chemistry fields; other scientific values read from SQL'}
        if dest not in row['destinations']:row['destinations'].append(dest)
        bind(child,name,location,canonical+'/'+key,xml+'/a:'+key if xml else None)
    item=node.get('items')
    if item:
        if 'anyOf' in item:
            for i,choice in enumerate(item['anyOf']):bind(choice,name,path+('items','anyOf',i),canonical+'/*',xml+'/a:item/a:'+('drx' if '$ref' in choice else 'generic') if xml else None)
        else:bind(item,name,path+('items',),canonical+'/*',xml+'/a:item' if xml else None)
for field,(name,multiple) in BINDINGS.items():bind(schemas[name],name,(),'/custom_fields/'+field+('/*' if multiple else ''),'/a:argiloteca/a:'+field.removeprefix('arg:')+('/a:item' if multiple else ''))
payload='arg_payload_publicacao.schema.json'
for key,value in schemas[payload]['properties'].items():
    row=rows[(payload,('properties',key))];row['destinations'].append({'json_path':'/'+key,'xml_path':'/a:argiloteca/a:metadata' if key=='metadata' else None,'policy':'access/files govern native permissions; no access/file-control export; custom_fields mapped by bindings'})
    if key!='custom_fields':bind(value,payload,('properties',key),'/'+key,'/a:argiloteca/a:metadata' if key=='metadata' else None)
# The payload wrapper repeats six blocks; link each schema-level declaration to
# the canonical binding rather than inventing new persistence destinations.
for row in rows.values():
    if not row['destinations'] and row['schema']==payload:
        key=row['field'];field=key if key.startswith('arg:') else None
        if field in BINDINGS:row['destinations'].append({'json_path':'/custom_fields/'+field,'xml_path':'/a:argiloteca/a:'+field.removeprefix('arg:')})
report={'profile_version':PROFILE_VERSION,'schema_count':len(schemas),'property_count':len(rows),'profile_field':PROFILE_FIELD,'index_only_field':SEARCH_FIELD,'source_sha256':{name:hashlib.sha256((Path(__import__('argiloteca.scientific.models',fromlist=['SCHEMA_DIR']).SCHEMA_DIR)/name).read_bytes()).hexdigest() for name in schemas},'fields':list(rows.values())}
print(json.dumps(report,ensure_ascii=False,indent=2))
