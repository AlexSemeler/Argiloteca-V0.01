import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloteca.argiloclay import community_sources as cs
from argiloteca.argiloclay.service import query,revalidate_response,verify_records
from argiloteca.argiloclay.async_service import start


def row(slug='hidrotalcitas-hidroxidos-duplos-lamelares',cid='858b3eff-fd47-4bd7-ae26-923fe95b7e5c'):
 return {'id':cid,'slug':slug,'updated':'2026-10-29T21:00:00Z','access':{'visibility':'public'},'metadata':{'title':'Hidrotalcitas e Hidróxidos Duplos Lamelares','page':'<p>Os <a href="/argilominerais/hydrotalcite">hidrotalcita</a> e materiais relacionados são descritos nesta comunidade. Embora não pertençam aos grupos clássicos 1:1 e 2:1, são materiais correlatos.</p><p>Fonte editorial de teste.</p><p><strong>Palavras-chave:</strong> adsorção</p><script>alert(1)</script>'}}

class CommunityTests(unittest.TestCase):
 def setUp(self):self.source=cs.project(row())
 def clean(self):return {k:v for k,v in self.source.items() if not k.startswith('_')}
 def test_about_not_short_description_and_no_markup_scripts(self):
  self.assertIn('não pertençam',self.source['excerpt']);self.assertNotIn('alert',self.source['excerpt']);self.assertNotIn('<',self.source['excerpt']);self.assertNotIn('Palavras-chave',self.source['excerpt'])
 def test_private_empty_and_invalid_identifiers_rejected(self):
  for key,value in [('access',{'visibility':'restricted'}),('slug','../bad'),('id','bad')]:
   r=row();r[key]=value;self.assertIsNone(cs.project(r))
  r=row();r['metadata']['page']='';self.assertIsNone(cs.project(r))
 def test_definitions_select_group_species_and_english(self):
  for q in ('O que são hidrotalcitas?','O que é hidrotalcita?','What is hydrotalcite?','Explique hidróxidos duplos lamelares'):
   self.assertEqual(len(cs.select(q,[self.source])),1,q)
 def test_general_question_uses_native_group_about(self):
  self.assertEqual(cs.select('O que são argilominerais?',[self.source])[0]['community_id'],self.source['community_id'])
 def test_unrelated_extra_words_samples_and_classification_not_hijacked(self):
  for q in ('O que são hidrotalcitas em Marte?','Identifique hidrotalcita nesta amostra','Qual o nome em inglês de hidrotalcita?','O que é DRX de hidrotalcita?','Preço de hidrotalcita'):
   self.assertEqual(cs.select(q,[self.source]),[],q)
 def test_ambiguous_related_term_does_not_pick_arbitrary_community(self):
  second=cs.project(row('outro-grupo','858b3eff-fd47-4bd7-ae26-923fe95b7e5d'));second['title']='Outro grupo'
  self.assertEqual(cs.select('What is hydrotalcite?',[self.source,second]),[])
 def test_current_source_overrides_untrusted_link(self):
  source=self.clean();source['url']='https://evil.example';result=cs.verify(source,lambda _:self.source)
  self.assertEqual(result['url'],'/communities/hidrotalcitas-hidroxidos-duplos-lamelares/about')
 def test_revocation_edit_and_excerpt_forgery_blocked(self):
  for resolve in (lambda _:None,lambda _:{**self.source,'updated':'new'},lambda _:{**self.source,'sha256':'other'}):
   self.assertIsNone(cs.verify(self.clean(),resolve))
  self.assertIsNone(cs.verify({**self.clean(),'excerpt':'Invented scientific claim'},lambda _:self.source))
 def test_query_prefers_about_and_keeps_scientific_qualification(self):
  client=unittest.mock.Mock()
  with patch.object(cs,'public_sources',return_value=[self.source]),patch.object(cs,'public_community',return_value=self.source):
   # Default resolver is bound at definition; patch verify at its explicit boundary.
   original=cs.verify
   with patch.object(cs,'verify',side_effect=lambda s,**kw:original(s,lambda _:self.source,**kw)):
    response=query({'question':'O que são hidrotalcitas?'},client)
  client.call.assert_not_called();self.assertIn('não pertençam',response['answer']);self.assertIn('[Fonte 1]',response['answer']);self.assertEqual(response['generation_mode'],'metadata_template')
 def test_incomplete_community_source_cannot_bypass_verification(self):
  incomplete=self.clean();incomplete.pop('community_id')
  result=revalidate_response({'sources':[incomplete]})
  self.assertEqual(result['sources'],[])
 def test_history_verifies_current_version_and_is_bounded(self):
  original=cs.verify
  with patch.object(cs,'verify',side_effect=lambda s,**kw:original(s,lambda _:self.source,**kw)):
   result=verify_records({'records':[],'community_sources':[self.clean()]})
  self.assertEqual(result['community_verified'],[self.source['document_id']])
  with self.assertRaises(ValueError):verify_records({'records':[],'community_sources':[{}]*13})
 def test_selected_record_context_retains_existing_route(self):
  client=unittest.mock.Mock();client.call.return_value={'schema_version':'1.0','sources':[]}
  with patch.object(cs,'public_sources') as public:
   query({'question':'O que são hidrotalcitas?','context':{'record_ids':['abcde-12345']}},client,lambda _: {'updated':'v1'})
  public.assert_not_called();client.call.assert_called_once()
 def test_source_only_answer_never_sends_editorial_text_to_generator(self):
  client=unittest.mock.Mock()
  base={'sources':[self.clean()],'generation_mode':'metadata_template','page_context':{'language':'pt'}}
  with patch('argiloteca.argiloclay.async_service.query',return_value=base):r=start({'question':'O que são hidrotalcitas?'},client)
  self.assertEqual(r['generation']['reason'],'verified_metadata');client.call.assert_not_called()

 def test_status_reports_limited_native_sources_when_rag_is_down(self):
  from flask import Flask,Blueprint
  from argiloteca.argiloclay.routes import register
  from argiloteca.argiloclay.service import Unavailable
  app=Flask(__name__);bp=Blueprint('test_community_status',__name__);register(bp);app.register_blueprint(bp)
  with patch('argiloteca.argiloclay.routes.ChatClient.call',side_effect=Unavailable('offline')),patch.object(cs,'public_sources',return_value=[self.source]):
   result=app.test_client().get('/argiloclay/api/status')
  self.assertEqual(result.status_code,200);self.assertTrue(result.json['partial']);self.assertEqual(result.json['source_scope'],'community_about')

if __name__=='__main__':unittest.main()
