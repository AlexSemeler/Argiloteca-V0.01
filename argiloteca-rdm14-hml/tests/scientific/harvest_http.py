"""Anonymous real HTTPS OAI collector. Strict TLS with the HML's public CA."""
import json,ssl,sys
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
root=Path(sys.argv[1]);base=sys.argv[2];ctx=ssl.create_default_context(cafile=sys.argv[3]);report=json.loads((root/'integration.json').read_text());OAI='http://www.openarchives.org/OAI/2.0/';ns={'o':OAI}
checks={}
def get(name,params,allow_error=None):
 try:
  with urlopen(base+'/oai2d?'+urlencode(params),context=ctx,timeout=45) as response:body=response.read()
 except HTTPError as error:
  if not allow_error:raise
  body=error.read()
 (root/'oai'/name).write_bytes(body);tree=ET.fromstring(body);errors=tree.findall('o:error',ns)
 if errors and not allow_error:raise AssertionError(name+': '+','.join(e.get('code','')+':'+(e.text or '') for e in errors))
 if allow_error:assert [e.get('code') for e in errors]==[allow_error],ET.tostring(tree)
 return tree

def collect(name,params,expected_ids=None):
 folder=root/'oai'/name;folder.mkdir(exist_ok=True);request=dict(params);pages=[];ids=[];seen=set();payloads=[]
 for page in range(1,1000):
  filename=name+'/page-'+str(page).zfill(6)+'.xml';tree=get(filename,request)
  for header in tree.findall('.//o:header',ns):ids.append(header.findtext('o:identifier',namespaces=ns))
  if params['verb']=='ListSets':ids.extend(n.text for n in tree.findall('o:ListSets/o:set/o:setSpec',ns))
  payloads.extend(tree.findall('.//o:metadata/*',ns))
  token=tree.find('o:'+params['verb']+'/o:resumptionToken',ns);token=token.text if token is not None else None
  pages.append({'file':'page-'+str(page).zfill(6)+'.xml','request':request,'next_token':token})
  if not token:break
  assert token not in seen;seen.add(token);request={'verb':params['verb'],'resumptionToken':token}
 else:raise AssertionError('unfinished harvest')
 assert len(ids)==len(set(ids)),name+' duplicate IDs'
 if expected_ids is not None:assert {i.rsplit(':',1)[-1] for i in ids}==set(expected_ids),(name,ids,expected_ids)
 (folder/'collection.json').write_text(json.dumps({'base_url':base+'/oai2d','complete':True,'pages':pages},indent=2))
 checks[name]={'pages':len(pages),'identifiers':len(ids),'payloads':len(payloads),'duplicates':0}
 print('PASS',name,checks[name],flush=True)
 return ids,payloads

if '--sets-only' in sys.argv:
 collect('all-sets',{'verb':'ListSets'});(root/'oai-sets-http.json').write_text(json.dumps(checks,indent=2));sys.exit(0)

identify=get('identify.xml',{'verb':'Identify'});checks['identify']={k:identify.findtext('o:Identify/o:'+k,namespaces=ns) for k in ['repositoryName','granularity','deletedRecord','baseURL']}
formats=get('formats.xml',{'verb':'ListMetadataFormats'});prefixes=[n.text for n in formats.findall('o:ListMetadataFormats/o:metadataFormat/o:metadataPrefix',ns)];assert 'argiloteca' in prefixes and 'oai_dc' in prefixes and len(prefixes)>=9;checks['formats']=prefixes
for label in ['scientific','legacy','files_restricted']:
 id_=report['records'][label];identifier='oai:hml.argiloteca.invalid:'+id_
 get('get-'+label+'.xml',{'verb':'GetRecord','metadataPrefix':'argiloteca','identifier':identifier})
 get('formats-'+label+'.xml',{'verb':'ListMetadataFormats','identifier':identifier})
get('get-legacy-dc.xml',{'verb':'GetRecord','metadataPrefix':'oai_dc','identifier':report['oai']['legacy']})
get('restricted.xml',{'verb':'GetRecord','metadataPrefix':'argiloteca','identifier':'oai:hml.argiloteca.invalid:'+report['records']['restricted']},allow_error='idDoesNotExist')
get('draft.xml',{'verb':'GetRecord','metadataPrefix':'argiloteca','identifier':'oai:hml.argiloteca.invalid:'+report['records']['new_version_draft']},allow_error='idDoesNotExist')
get('unsupported.xml',{'verb':'GetRecord','metadataPrefix':'does-not-exist','identifier':report['oai']['scientific']},allow_error='cannotDisseminateFormat')
collect('all-sets',{'verb':'ListSets'})
ids=report['harvest_set']['record_ids'];spec=report['harvest_set']['spec']
collect('mixed-identifiers',{'verb':'ListIdentifiers','metadataPrefix':'argiloteca','set':spec},ids)
collect('mixed-records',{'verb':'ListRecords','metadataPrefix':'argiloteca','set':spec},ids)
# Unfiltered mixed collection also exercises every legacy row's crosswalk.
all_ids,_=collect('all-records',{'verb':'ListRecords','metadataPrefix':'argiloteca'})
assert report['oai']['scientific'] in all_ids and report['oai']['legacy'] in all_ids
assert not any(i.rsplit(':',1)[-1] in {report['records']['restricted'],report['records']['new_version_draft']} for i in all_ids)
checks['anonymous exposure']={'public_profiles_and_legacy':True,'restricted_and_drafts_absent':True,'restricted_file_metadata_harvested':True}
(root/'oai-http.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2));print('COMPLETE REAL HTTPS OAI',flush=True)
