"""Verify native UTC incremental boundaries and anonymous access through HTTPS."""
import json,ssl,sys
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from xml.etree import ElementTree as E
from datetime import datetime,timedelta
root=Path(sys.argv[1]);base=sys.argv[2];ctx=ssl.create_default_context(cafile=sys.argv[3]);r=json.loads((root/'integration.json').read_text());N={'o':'http://www.openarchives.org/OAI/2.0/','a':'https://127.0.0.1:5101/schemas/argiloteca/v1/'};report={}
def request(path,name,expected_status=200):
 try:
  with urlopen(base+path,context=ctx,timeout=30) as response:body=response.read();status=response.status
 except HTTPError as error:body=error.read();status=error.code
 assert status in (expected_status if isinstance(expected_status,list) else [expected_status]),(name,status)
 (root/name).write_bytes(body);return body
q={'verb':'ListRecords','metadataPrefix':'argiloteca','from':r['incremental']['from'],'until':r['incremental']['until']}
tree=E.fromstring(request('/oai2d?'+urlencode(q),'oai/incremental.xml'))
ids=[e.text for e in tree.findall('.//o:identifier',N)];assert r['oai']['scientific'] in ids
value=tree.find('.//a:amostras/a:item/a:observacoes_campo',N).text;assert value==r['incremental']['expected_value']
stamps=[e.text for e in tree.findall('.//o:datestamp',N)];assert r['incremental']['from'] in stamps
report['incremental_exact_second']={'from':q['from'],'until':q['until'],'identifiers':ids,'datestamps':stamps,'scientific_only_value':value}
q={'verb':'GetRecord','metadataPrefix':'argiloteca','identifier':r['withdrawal']['former_identifier']}
tree=E.fromstring(request('/oai2d?'+urlencode(q),'oai/withdrawn.xml',422));assert tree.find('o:error',N).get('code')=='idDoesNotExist'
# A real file exists, but only its public metadata may be harvested anonymously.
fid=r['records']['files_restricted'];meta=json.loads(request('/api/records/'+fid,'file-restricted-record.json'))
assert meta['access']['record']=='public' and meta['access']['files']=='restricted' and meta['files']['enabled']
request('/api/records/'+fid+'/files/synthetic.txt/content','restricted-file-response.json',[403,404])
report['withdrawal_and_file_access']={'former_public_identifier_rejected':True,'public_metadata_restricted_file':True,'anonymous_content_denied':True,'deletedRecord':'no; reconciliation required'}
(root/'incremental-http.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
