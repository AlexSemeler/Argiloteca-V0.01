"""Run with the application image: python -m unittest discover -s tests/scientific."""
import unittest
from copy import deepcopy
from decimal import Decimal
from lxml import etree
from argiloteca.scientific.models import validate_model,scientific_errors,schema_bundle,public_scientific,projection
from argiloteca.scientific.xml import record_to_xml,compiled_xsd,build_xsd,DEFAULT_NAMESPACE
from fixtures import models,publication

class Contract(unittest.TestCase):
    def test_all_fourteen_models(self):
        fixtures=models();self.assertEqual(len(fixtures),14)
        for name,payload in fixtures.items():
            with self.subTest(name=name):
                self.assertEqual(validate_model(name,payload),[])
                self.assertTrue(validate_model(name,[]))
    def test_publication_and_references(self):
        data=publication();self.assertEqual(scientific_errors(data['custom_fields']),[])
        self.assertEqual(validate_model('arg_payload_publicacao.schema.json',data),[])
        data['custom_fields']['arg:amostras'][0]['campanha_id']='missing'
        self.assertTrue(scientific_errors(data['custom_fields']))
    def test_permissive_package_is_not_strict_drx(self):
        package=publication()['custom_fields']['arg:pacotes_analiticos'][0]
        self.assertEqual(validate_model('arg_pacote_analitico.schema.json',package),[])
        self.assertTrue(validate_model('arg_drx.schema.json',package['items'][1]))
    def test_dates_types_cardinality_and_bounds(self):
        data=publication()['custom_fields']
        for field,key,bad in [('arg:amostras','latitude',91),('arg:amostras','data_coleta','2026-02-31'),('arg:amostras','codigo_amostra',''),('arg:analises','metodo',False)]:
            value=deepcopy(data);value[field][0][key]=bad;self.assertTrue(scientific_errors(value))
        value=deepcopy(data);value['arg:amostras'][0]['campanha_id']={};self.assertTrue(scientific_errors(value))
    def test_full_xml_values_and_schema(self):
        root=record_to_xml(publication());ns={'a':DEFAULT_NAMESPACE,'xsi':'http://www.w3.org/2001/XMLSchema-instance'}
        self.assertEqual(root.xpath('string(a:amostras/a:item[1]/a:codigo_amostra)',namespaces=ns),'0001')
        self.assertEqual(root.xpath('string(a:amostras/a:item[1]/a:latitude)',namespaces=ns),'0')
        self.assertEqual(root.xpath('string(a:amostras/a:item[1]/a:altitude_m/@xsi:nil)',namespaces=ns),'true')
        self.assertEqual(root.xpath('string(a:referencias_drx_webmineral/a:item/a:has_drx_reference)',namespaces=ns),'false')
        self.assertEqual(root.xpath('string(a:composicao_quimica_global/a:Al2O3)',namespaces=ns),'12.3456789012345')
        self.assertFalse(root.xpath('//a:unknown_enrichment',namespaces=ns))
        self.assertEqual(root.xpath('string(a:metadata/a:title)',namespaces=ns),publication()['metadata']['title'])
        self.assertEqual(root.xpath('count(a:pacotes_analiticos/a:item/a:items/a:item)',namespaces=ns),2)
        self.assertTrue(compiled_xsd().validate(root))
        root.find('{'+DEFAULT_NAMESPACE+'}metadata').remove(root.find('{'+DEFAULT_NAMESPACE+'}metadata/{'+DEFAULT_NAMESPACE+'}title'))
        self.assertFalse(compiled_xsd().validate(root))
    def test_anyof_alternatives_and_legacy_without_profile(self):
        data=publication()
        mineral=data['custom_fields']['arg:argilominerais'][0]
        del mineral['nome'];del mineral['nome_cientifico_padronizado']
        self.assertTrue(scientific_errors(data['custom_fields']))
        legacy=publication();legacy['custom_fields']={'arg:usos_descricao':'ação & < >'}
        self.assertEqual(scientific_errors(legacy['custom_fields']),[])
        root=record_to_xml(legacy);self.assertEqual(root.attrib['profiled'],'false')
    def test_absence_empty_null_and_unknown_policy(self):
        data=publication()['custom_fields'];clean=public_scientific(data)
        self.assertNotIn('unknown_enrichment',clean['arg:amostras'][0])
        self.assertEqual(data['arg:amostras'][0]['descricao_local'],'')
        self.assertIsNone(data['arg:amostras'][0]['altitude_m'])
        self.assertNotIn('nonesuch',data['arg:amostras'][0])
        self.assertFalse(clean['arg:composicao_quimica_global']['provenance']['synthetic'])
    def test_every_scientific_value_roundtrips_xml(self):
        from xml_roundtrip import typed,normalize,local
        from argiloteca.scientific.models import BINDINGS
        expected=publication()['custom_fields'];expected={k:v for k,v in expected.items() if k in BINDINGS}
        for sample in expected['arg:amostras']:sample.pop('unknown_enrichment',None)
        schemas=schema_bundle()[0];root=record_to_xml(publication());actual={}
        for node in root:
            field='arg:'+local(node)
            if field in BINDINGS:
                name,multiple=BINDINGS[field]
                definition={'type':'array','items':{'$ref':name}} if multiple else {'$ref':name}
                actual[field]=typed(node,definition,schemas)
        self.assertEqual(normalize(expected),actual)
    def test_uri_checker_is_active(self):
        data=models()['arg_publicacao.schema.json'];data['url']='not a URI with spaces'
        self.assertTrue(validate_model('arg_publicacao.schema.json',data))
    def test_projection_retains_correlated_items(self):
        result=projection(publication()['custom_fields'])
        self.assertEqual([(r['name'],r['sample'],r['latitude']) for r in result['minerals']],[('Kaolinite','0001',0),('Illite','0002',1)])

if __name__=='__main__':unittest.main()
