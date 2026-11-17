"""Search composition and transport failures without an OpenAlex request."""
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

BASE=Path(__file__).resolve().parents[2]/'argiloteca/openalex'
def load(name):
    spec=importlib.util.spec_from_file_location('search_test_'+name,BASE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
adapters=load('adapters');search=load('search_extractor')


class SearchTests(unittest.TestCase):
    vocabulary=[{'id':'kaolinite','title':{'pt':'Caulinita'}},{'id':'illite','title':{'pt':'Ilita'}}]
    def params(self,**kwargs):return adapters.extraction_parameters(kwargs,self.vocabulary)
    def test_legacy_vocabulary_still_accepted(self):
        self.assertEqual(self.params(term='kaolinite')['search_mode'],'vocabulary')
    def test_free_without_vocabulary(self):
        params=self.params(free_text='DRX')
        self.assertEqual(params['search_mode'],'free')
        self.assertEqual(search.search_queries(params,self.vocabulary),['DRX'])
    def test_combination_is_and_not_two_independent_searches(self):
        params=self.params(term='kaolinite',free_text='DRX OR XRD')
        self.assertEqual(params['search_mode'],'combined')
        self.assertEqual(search.search_queries(params,self.vocabulary),['(DRX OR XRD) AND ("kaolinite")'])
    def test_specific_term_does_not_include_substring_matches(self):
        params=self.params(term='illite',free_text='DRX',max_terms=100)
        vocabulary=self.vocabulary+[{'id':'illite-smectite','title':{'pt':'Interestratificado'}}]
        self.assertEqual(search.search_queries(params,vocabulary),['(DRX) AND ("illite")'])
    def test_all_uses_order_offset_and_limit(self):
        params=self.params(term='__all__',free_text='DRX',offset=1,max_terms=1)
        self.assertEqual(search.search_queries(params,self.vocabulary),['(DRX) AND ("illite")'])
    def test_specific_offset_refused(self):
        with self.assertRaises(ValueError):search.search_queries(self.params(term='kaolinite',free_text='DRX',offset=1),self.vocabulary)
    def test_empty_selection_refused(self):
        for values in ({},{'free_text':'  '},{'term':'not-in-vocab','free_text':'DRX'}):
            with self.assertRaises(ValueError):self.params(**values)
    def test_long_or_control_input_refused(self):
        for value in ('a'*501,'DRX\nXRD','DRX\x00'):
            with self.assertRaises(ValueError):self.params(free_text=value)
    def test_bounded_numeric_arguments_apply_to_all_modes(self):
        for value in ({'per_term':101},{'offset':10001},{'max_terms':0},{'per_term':'x'}):
            with self.assertRaises(ValueError):self.params(free_text='DRX',**value)
    def test_free_search_ignores_vocabulary_offset(self):
        self.assertEqual(search.search_queries(self.params(free_text='XRD',offset=100,max_terms=5),[]),['XRD'])
    def test_client_passes_encoded_and_expression_and_limit(self):
        from urllib.parse import urlparse,parse_qs
        client=SimpleNamespace(BASE_URL='https://api.openalex.org/works',SELECT_FIELDS='id',per_page=100,request_timeout=30)
        with patch.object(search.urllib.request,'urlopen',return_value=io.StringIO(json.dumps({'results':[{'id':'W1'}]}))) as request:
            self.assertEqual(search.fetch_query(client,'(DRX OR XRD) AND ("kaolinite")',1),[{'id':'W1'}])
        values=parse_qs(urlparse(request.call_args.args[0]).query)
        self.assertEqual(values['search'],['(DRX OR XRD) AND ("kaolinite")']);self.assertEqual(values['per-page'],['1'])
    def test_api_failure_is_not_reported_as_empty_success(self):
        client=SimpleNamespace(BASE_URL='https://api.openalex.org/works',SELECT_FIELDS='id',per_page=100,request_timeout=30)
        with patch.object(search.urllib.request,'urlopen',side_effect=HTTPError(client.BASE_URL,429,'limit',{},None)):
            with self.assertRaises(HTTPError):search.fetch_query(client,'DRX',1)
    def test_empty_valid_response_is_allowed(self):
        client=SimpleNamespace(BASE_URL='https://api.openalex.org/works',SELECT_FIELDS='id',per_page=100,request_timeout=30)
        with patch.object(search.urllib.request,'urlopen',return_value=io.StringIO('{"results":[]}')):
            self.assertEqual(search.fetch_query(client,'DRX',1),[])


if __name__=='__main__':unittest.main()
