import copy,json,sys,unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloteca.argiloclay import community_sources as cs,research_context as rc,bibliography,foundations
from argiloteca.argiloclay.async_service import start
from test_community_sources import row
import test_knowledge_library as knowledge_tests

class DirectExplanationTests(unittest.TestCase):
 def sources(self):
  values=[]
  for n,slug in enumerate(cs.GENERAL_SLUGS[:3]):
   r=row(slug,'858b3eff-fd47-4bd7-ae26-923fe95b7e5'+str(n));r['metadata']['title']=slug
   r['metadata']['page']='<p>Minerais em camadas encontrados em solos e sedimentos. Sua interação com água e íons varia conforme a estrutura.</p><p>Na Argiloteca, esta comunidade organiza registros.</p>'
   values.append(cs.project(r))
  return values
 def test_direct_answer_and_typo(self):
  sources=cs.select('O que são argiloinerais?',self.sources());self.assertEqual(len(sources),3)
  answer=cs.answer(sources,question='O que são argiloinerais?')
  self.assertTrue(answer.startswith('Argilominerais são minerais'));self.assertNotIn('As páginas',answer);self.assertNotIn('identificação de amostra',answer);self.assertNotIn('esta comunidade organiza',answer)
 def test_related_sources_keep_citation_numbers(self):
  sources=cs.select('O que são argilominerais?',self.sources());sources+=[{'record_id':'abcde-12345','title':'Estudo de argilas','record_fields':{'publication_date':'2024'}}]
  answer=cs.answer(sources,question='O que são argilominerais?');self.assertIn('Estudo de argilas (2024) [Fonte 4]',answer)
 def test_scientific_qualification_not_removed(self):
  s=cs.project(row());answer=cs.answer([s],question='O que são hidrotalcitas?');self.assertIn('não pertençam aos grupos clássicos',answer)
 def test_sample_questions_not_intercepted(self):
  self.assertEqual(cs.select('O que são argilominerais desta amostra?',self.sources()),[])
 def test_related_request_accepted(self):
  self.assertTrue(cs.select('O que são argilominerais e indique registros relacionados do acervo?',self.sources()))

class ResearchContextTests(unittest.TestCase):
 def records(self):
  base={'updated':'v1','access':{'record':'public'},'is_published':True,'metadata':{'title':'Pesquisa de argilas','publication_date':'2024','resource_type':{'id':'publication-article'},'description':'Pesquisa publicada de argilas.'},'pids':{'doi':{'identifier':'10.1/test'}}}
  return {'abcde-12345':base,'abcde-67890':copy.deepcopy(base),'abcde-11111':{**base,'access':{'record':'restricted'}}}
 def searcher(self,query,size):
  self.calls.append((query,size))
  if 'publication_date:[' in query:return {'hits':{'total':80,'hits':[]}}
  return {'hits':{'total':1129,'hits':[{'id':x} for x in self.records()]}}
 def setUp(self):self.calls=[]
 def test_counts_same_publication_scope_complete_periods_dedup_and_permissions(self):
  result=rc.collect('O que são argiloinerais?',self.records().get,self.searcher,date(2026,10,29))
  self.assertEqual(len(result['sources']),1);self.assertEqual(result['statistics']['periods'],[(2016,2020),(2021,2025)])
  self.assertEqual(result['statistics']['counts'],[80,80]);self.assertTrue(all('metadata.resource_type.id:publication*' in q for q,_ in self.calls));self.assertEqual(len(self.calls),3)
  self.assertIn('mesmo número',rc.describe(result['statistics']));self.assertNotIn('crescimento',rc.describe(result['statistics']))
 def test_low_coverage_omits_trend(self):
  self.assertEqual(rc.describe({'counts':[1,2]}),'')
 def test_query_syntax_not_forwarded(self):
  result=rc.collect('O que são argilominerais OR access:restricted?',self.records().get,self.searcher,date(2026,10,29))
  self.assertTrue(all('restricted' not in q for q,_ in self.calls))
 def test_approximate_count_not_called_exact(self):
  result=rc.collect('O que são argilominerais?',lambda _:None,lambda q,s:{'hits':{'hits':[],'total':{'value':10000,'relation':'gte'}}},date(2026,10,29))
  self.assertNotIn('statistics',result)
 def test_english_and_bilingual_alias(self):
  self.assertEqual(rc.terms_for('O que é caulinita?'),['caulinita','kaolinite','kaolinita'])
  result=rc.collect('What are clay minerals?',self.records().get,self.searcher,date(2026,10,29));self.assertIn('public collection',rc.describe(result['statistics'],'en'))

class BibliographyTests(unittest.TestCase):
 setUp=knowledge_tests.KnowledgeTests.setUp
 document=knowledge_tests.KnowledgeTests.document
 def book(self):
  doc=self.document()['doc']
  with self.lib.connect() as c:
   meta=json.loads(c.execute('SELECT metadata FROM versions WHERE doc=?',(doc,)).fetchone()[0]);meta.update(title='Clays',authors='Alain Meunier',year='2005');c.execute('UPDATE versions SET metadata=? WHERE doc=?',(json.dumps(meta),doc))
  return doc
 def test_author_year_title_lookup_without_author_in_page_text(self):
  doc=self.book();self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test')
  for q in ('Você conhece Meunier, 2005?','Alain Meunier','Clays 2005'):
   sources=bibliography.lookup(q,self.lib);self.assertEqual(len(sources),1,q);self.assertEqual(sources[0]['library_id'],doc)
  self.assertEqual(bibliography.lookup('Meunier 2006',self.lib),[])
 def test_pending_and_withdrawn_books_never_published(self):
  doc=self.book();self.assertEqual(bibliography.lookup('Meunier 2005',self.lib),[])
  self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test');self.lib.withdraw(doc,1,'test');self.assertEqual(bibliography.lookup('Meunier 2005',self.lib),[])
 def test_suggestions_only_approved_active_public_books(self):
  doc=self.book();self.assertEqual(bibliography.suggestions(self.lib),[])
  self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test')
  self.assertEqual(bibliography.suggestions(self.lib),['Você conhece Clays — Alain Meunier (2005)?'])
  self.assertEqual(bibliography.suggestions(self.lib,'en'),['Do you know Clays — Alain Meunier (2005)?'])
  self.lib.withdraw(doc,1,'test');self.assertEqual(bibliography.suggestions(self.lib),[])
 def test_bibliographic_answer_does_not_call_generator(self):
  client=Mock()
  with patch('argiloteca.argiloclay.async_service.query',return_value={'sources':[{'title':'Clays'}],'generation_mode':'bibliographic_lookup'}):r=start({'question':'Meunier 2005'},client)
  self.assertEqual(r['generation']['reason'],'verified_bibliography');client.call.assert_not_called()

class FoundationTests(unittest.TestCase):
 setUp=knowledge_tests.KnowledgeTests.setUp
 document=knowledge_tests.KnowledgeTests.document
 def ready(self):
  doc=self.document()['doc']
  with self.lib.connect() as c:
   meta=json.loads(c.execute('SELECT metadata FROM versions WHERE doc=?',(doc,)).fetchone()[0]);meta.update(title='REPORT OF THE AIPEA NOMENCLATURE COMMITTEE FOR 2006',year='2006')
   c.execute('UPDATE versions SET metadata=? WHERE doc=?',(json.dumps(meta),doc))
   c.execute('UPDATE pages SET text=? WHERE doc=?',('Clays are composed primarily of fine-grained minerals, plastic with water and harden on drying. Clay minerals include phyllosilicates and minerals which impart plasticity and harden on drying or firing.',doc))
  self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test');return doc
 def test_basic_answers_cite_reviewed_library_sources(self):
  self.ready()
  for q,begin in [('O que são argilas?','Argilas são materiais naturais'),('O que são clays?','Argilas são materiais naturais'),('O que são argiloinerais?','Argilominerais incluem'),('What are clays?','Clays are natural materials'),('What is a clay mineral?','Clay minerals include')]:
   sources=foundations.lookup(q,self.lib);self.assertEqual(len(sources),2)
   answer=foundations.answer(sources,q,'en' if q.startswith('What') else 'pt');self.assertTrue(answer.startswith(begin));self.assertRegex(answer,r'\[(Fonte|Source) [12]\]')
 def test_no_unsupported_or_unreviewed_definition(self):
  doc=self.ready();self.lib.withdraw(doc,1,'test')
  self.assertEqual(foundations.lookup('O que são argilas?',self.lib),[])
  self.assertEqual(foundations.answer([],'O que são argilas?'),'')
  for q in ('Identifique a argila da minha amostra','O que são argilas da amostra DRX?','O que são argilas segundo um livro desconhecido?'):
   self.assertIsNone(foundations.kind(q))
 def test_no_model_required_for_reviewed_basics(self):
  client=Mock()
  with patch('argiloteca.argiloclay.async_service.query',return_value={'sources':[{'title':'AIPEA'}],'generation_mode':'verified_foundations'}):r=start({'question':'O que são argilas?'},client)
  self.assertEqual(r['generation']['reason'],'reviewed_definitions');client.call.assert_not_called()

class ReadableGenerationTests(unittest.TestCase):
 def test_bilingual_paraphrase_keeps_grounding_and_blocks_added_claims(self):
  from argiloclay_intelligence.generation import prepare,validate_answer
  source={'document_id':'test','title':'Clays','excerpt':'Clays are made up of particles that form stable suspensions in water.','tipo_fonte':'literatura_pdf','numeric_validation':'reviewed'}
  plan=prepare('Como as argilas formam suspensões em água?',[source])
  good='As argilas são compostas por partículas que formam suspensões estáveis em água. [Fonte 1]'
  self.assertEqual(validate_answer(good,plan),good)
  self.assertEqual(validate_answer('Clays form suspensões estáveis em água. [Fonte 1].',plan),'As argilas formam suspensões estáveis em água. [Fonte 1]')
  with self.assertRaises(ValueError):validate_answer('Clays are particles in water. [Fonte 1]',plan)
  for bad in ['As argilas têm 100 partículas em água. [Fonte 1]','As argilas curam doenças. [Fonte 1]','As argilas formam suspensões estáveis em ácido. [Fonte 1]']:
   with self.assertRaises(ValueError):validate_answer(bad,plan)
 def test_generation_context_is_a_complete_relevant_sentence(self):
  from argiloclay_intelligence.generation import prepare
  source={'title':'Clays','excerpt':'agment irrelevant to the question. Clays form stable suspensions in water. Another unrelated statement follows.','tipo_fonte':'literatura_pdf'}
  self.assertEqual(prepare('Argilas e água?',[source])['quote'],'Clays form stable suspensions in water.')
 def test_fallback_does_not_dump_pdf_fragments(self):
  from argiloteca.argiloclay.async_service import reader_fallback
  data={'sources':[{'excerpt':'BROKEN PDF FRAGMENT'}],'answer':'BROKEN PDF FRAGMENT','generation_mode':'extractive'}
  self.assertNotIn('BROKEN PDF',reader_fallback(data)['answer']);self.assertEqual(data['sources'][0]['excerpt'],'BROKEN PDF FRAGMENT')
 def test_question_language_overrides_stale_interface_language(self):
  from argiloteca.argiloclay.service import community_question_language
  self.assertEqual(community_question_language('O que são clays?'),'pt')
  self.assertEqual(community_question_language('What are clays?'),'en')
  self.assertEqual(community_question_language('Explique argilas em inglês'),'en')

class PassageRelevanceTests(unittest.TestCase):
 setUp=knowledge_tests.KnowledgeTests.setUp
 document=knowledge_tests.KnowledgeTests.document
 def test_book_title_and_contents_are_not_topic_evidence(self):
  from argiloclay_intelligence.engine import Engine
  doc=self.document()['doc']
  with self.lib.connect() as c:
   meta=json.loads(c.execute('SELECT metadata FROM versions WHERE doc=?',(doc,)).fetchone()[0]);meta['title']='Clays';meta['minerals']=''
   c.execute('UPDATE versions SET metadata=? WHERE doc=?',(json.dumps(meta),doc))
   c.execute('UPDATE pages SET text=? WHERE doc=?',('Isotopic composition varies with temperature. Potassium dating requires minerals bearing potassium. This synthetic passage does not define the book title.',doc))
  self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test')
  self.assertEqual(Engine(self.index).query('What are clays?')['sources'],[])
  with self.lib.connect() as c:c.execute('UPDATE pages SET text=? WHERE doc=?',('Table of contents. Clays and the origin of life ......................................... 430. References 433. Index 467.',doc))
  self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test')
  self.assertEqual(Engine(self.index).query('What are clays?')['sources'],[])
