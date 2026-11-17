"""Offline native V59 export/metadata checks, using synthetic works in a temp dir."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
ROOT=APP.parent/'povoamento/openalex'
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
adapter=load('test_search_adapters',APP/'argiloteca_custom/argiloteca/openalex/adapters.py')
search=load('test_search_native',APP/'argiloteca_custom/argiloteca/openalex/search_extractor.py')
install,_=adapter.release(ROOT,'extractor');runner=load('test_v59',install/'runtime_runner.py')
config,key=runner.configuration();runner.set_paths(config,key)
fixtures=[{'id':'https://openalex.org/W999999999991','display_name':'Electrical circuit measurements',
 'publication_year':2024,'doi':'https://doi.org/10.9999/synthetic-free-search','authorships':[],
 'type':'article','abstract_inverted_index':{},'primary_location':{}},
 {'id':'https://openalex.org/W999999999992','display_name':'XRD study of kaolinite',
 'publication_year':2024,'doi':'https://doi.org/10.9999/synthetic-combined-search','authorships':[],
 'type':'article','abstract_inverted_index':{},'primary_location':{}}]
with tempfile.TemporaryDirectory(prefix='argiloteca-search-native-') as temp:
 work=Path(temp);params=adapter.extraction_parameters({'free_text':'DRX','per_term':2},adapter.terms(ROOT))
 with patch.object(search,'fetch_query',return_value=fixtures):result=search.collect(work,params,runner.vocabulary())
 assert result['payloads']==2 and result['unclassified']==1,result
 payloads=json.loads((work/'openalex_argiloteca.json').read_text())
 assert all('custom_fields' not in p for p in payloads)
 assert len((work/'manifest.tsv').read_text().splitlines())==2
 assert (work/'manifest.tsv').read_text().splitlines()[0].split('\t')[2:4]==['','']
 assert runner.validate_result(work)['payloads']==2
 (work/'resultado.json').write_text(json.dumps({'status':'coleta_concluida',**result}))
 reader=adapter.converter(ROOT)[1];prepared=reader.prepare_lot(work)
 assert len(prepared['records'])==2,prepared
 assert all(not any(i['severity']=='error' for i in r['issues']) for r in prepared['records']),prepared
 assert all('custom_fields' not in r['payload'] for r in prepared['records'])
 assert {r['identity']['openalex_id'] for r in prepared['records']}=={'W999999999991','W999999999992'}
 with patch.object(search,'fetch_query',return_value=[]):empty=search.collect(work,params,runner.vocabulary())
 assert empty['payloads']==0 and not (work/'manifest.tsv').stat().st_size
print(json.dumps({'offline_export':True,'unclassified_retained':True,'no_fabricated_scientific_fields':True,
 'manifest_compatible':True,'metadata_converter_accepts_both':True,'valid_empty_collection':True}))
