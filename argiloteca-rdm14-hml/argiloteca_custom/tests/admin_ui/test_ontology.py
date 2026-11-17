from copy import deepcopy
from pathlib import Path
import json
import unittest
from flask import Flask
from argiloteca.admin_ui.ontology import ENTITIES,matches,predicate
from argiloteca.admin_ui import configure
from argiloteca.scientific.models import BINDINGS

class OntologyTests(unittest.TestCase):
 def test_exact_five_entities_follow_the_supplied_model(self):
  self.assertEqual(list(ENTITIES),['campo','amostra','analise','argilomineral','publicacoes'])
 def test_each_scientific_block_exists_in_the_real_model(self):
  for entity in ENTITIES.values():
   for key in entity['fields']:self.assertIn(key,BINDINGS)
 def test_bibliography_does_not_become_a_physical_sample_by_title(self):
  d={'metadata':{'title':'Field sample XRD kaolinite','resource_type':{'id':'publication-article'}}}
  self.assertFalse(matches(d,'amostra'));self.assertFalse(matches(d,'campo'));self.assertFalse(matches(d,'analise'));self.assertTrue(matches(d,'publicacoes'))
 def test_empty_blocks_and_malformed_scalars_do_not_count(self):
  for value in (None,[],{},'null','',0):
   self.assertFalse(matches({'custom_fields':{'arg:amostras':value}},'amostra'))
 def test_one_record_can_describe_multiple_entities_without_mutation(self):
  d={'custom_fields':{'arg:pesquisas_campo':[{'campanha_id':'c'}],'arg:amostras':[{'codigo_amostra':'a'}],'arg:analises':[{'analise_id':'x'}]}}
  before=deepcopy(d)
  self.assertTrue(all(matches(d,key) for key in ['campo','amostra','analise']));self.assertEqual(before,d)
 def test_mineral_catalogue_records_and_composition_records_are_supported(self):
  self.assertTrue(matches({'custom_fields':{'arg:termo_catalogo':{'slug':'kaolinite'}}},'argilomineral'))
  self.assertTrue(matches({'custom_fields':{'arg:argilominerais':[{'nome':'kaolinite'}]}},'argilomineral'))
 def test_analysis_includes_chemical_results_and_analytical_packages(self):
  for key,value in [('arg:analises',[{'analise_id':'a'}]),('arg:pacotes_analiticos',[{'id':'p'}]),('arg:composicao_quimica_global',{'codigo_amostra':'s'})]:
   self.assertTrue(matches({'custom_fields':{key:value}},'analise'))
 def test_related_publications_are_visible_in_datasets(self):
  self.assertTrue(matches({'metadata':{'resource_type':{'id':'dataset'}},'custom_fields':{'arg:publicacoes_relacionadas':[{'doi':'10.1234/test'}]}},'publicacoes'))
 def test_sql_uses_bound_catalogued_keys(self):
  params={};sql=predicate('amostra',params)
  self.assertNotIn('arg:amostras',sql);self.assertEqual(list(params.values()),['arg:amostras'])
  with self.assertRaises(KeyError):predicate("amostra' OR 1=1",{})
 def test_new_navigation_is_disabled_by_default_outside_local(self):
  app=Flask(__name__);app.config['SITE_UI_URL']='https://production.example.org';configure(app)
  self.assertFalse(app.config['ARGILOTECA_ADMIN_ONTOLOGY_ENABLED']);self.assertNotIn('argiloteca_admin_ui',app.blueprints)
