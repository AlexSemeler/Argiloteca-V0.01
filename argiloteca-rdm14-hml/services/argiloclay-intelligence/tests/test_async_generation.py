import copy,json,sys,time,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloclay_intelligence.generation import Jobs,prepare,validate_answer,fingerprint
from argiloteca.argiloclay.async_service import start,poll

SOURCE={'document_id':'vocab:kaolinite','title':'Caulinita','excerpt':'Nome preferido: Caulinita. ID: kaolinite. Nome em inglês: Kaolinite. Categoria: species. Família: kaolin_group.', 'tipo_fonte':'vocabulario','category':'species','sha256':'a'}
ANSWER='Caulinita é uma espécie de mineral, com ID kaolinite e nome em inglês Kaolinite. [Fonte 1]'
class GenerationTests(unittest.TestCase):
 def test_supported_portuguese_keeps_citation(self):
  self.assertEqual(validate_answer(ANSWER,prepare('O que é caulinita?',[SOURCE])),ANSWER)
 def test_rejects_invention_wrong_citation_negation_and_incomplete_output(self):
  for answer in ['Caulinita tem composição clara e uniforme. [Fonte 1]','Caulinita é um grupo. [Fonte 1]','Caulinita tem 30 minerais. [Fonte 1]','Caulinita é uma espécie. [Fonte 2]','Caulinita não é uma espécie. [Fonte 1]','Caulinita é uma espécie de','O que é caulinita? [Fonte 1]','O nome em inglês da caulinita é caulinita. [Fonte 1]','Caulinita tem ID Caulinita. [Fonte 1]','O nome em português é Kaolinite. [Fonte 1]']:
   with self.subTest(answer=answer),self.assertRaises(ValueError):validate_answer(answer,prepare('O que é caulinita?',[SOURCE]))
 def test_english_label_requires_explicit_controlled_evidence(self):
  with self.assertRaises(ValueError):prepare('Qual é o nome em inglês da caulinita?',[{**SOURCE,'tipo_fonte':'registro_invenio','excerpt':'Dataset title: Caulinita - Kaolinite.'}])
 def test_english_prose_is_not_published_as_portuguese(self):
  with self.assertRaises(ValueError):validate_answer('Caulinita is a mineral. [Fonte 1]',prepare('Caulinita?',[SOURCE]))
 def test_numeric_pdf_and_long_question_fall_back(self):
  for question,sources in [('x'*181,[SOURCE]),('Caulinita?',[]),('Caulinita?',[{**SOURCE,'numeric_validation':'pending_visual_review'}])]:
   with self.assertRaises(ValueError):prepare(question,sources)
 def wait(self,jobs,key):
  for _ in range(100):
   row=jobs.get(key)
   if row['state']!='pending':return row
   time.sleep(.01)
  self.fail('Job did not complete')
 def test_complete_job_is_ephemeral_and_preserves_sources(self):
  j=Jobs(enabled=True,runner=lambda *a:ANSWER);r=j.submit({'question':'O que é caulinita?','sources':[SOURCE]});row=self.wait(j,r['job_id'])
  self.assertEqual(row['state'],'complete');self.assertEqual(row['sources'],[SOURCE]);self.assertEqual(row['sources_fingerprint'],fingerprint([SOURCE]))
 def test_no_evidence_does_not_start_inference(self):
  j=Jobs(enabled=True,runner=lambda *a:self.fail('Inference must not run'))
  self.assertEqual(j.submit({'question':'bitcoin','sources':[]})['reason'],'no_evidence')
 def test_cancel_and_busy_do_not_queue_another_inference(self):
  entered=threading.Event();leave=threading.Event()
  def runner(plan,cancel,deadline):entered.set();leave.wait(1);return ANSWER
  j=Jobs(enabled=True,runner=runner);r=j.submit({'question':'Caulinita?','sources':[SOURCE]});self.assertTrue(entered.wait(.5))
  self.assertEqual(j.submit({'question':'Caulinita?','sources':[SOURCE]})['reason'],'busy')
  j.cancel(r['job_id']);leave.set();time.sleep(.03);self.assertEqual(j.get(r['job_id'])['state'],'cancelled')
 def test_timeout_and_untrusted_generation_keep_fallback(self):
  for runner in [lambda *a:(_ for _ in ()).throw(TimeoutError()),lambda *a:'Caulinita cura câncer. [Fonte 1]']:
   j=Jobs(enabled=True,runner=runner);r=j.submit({'question':'Caulinita?','sources':[SOURCE]});self.assertEqual(self.wait(j,r['job_id'])['state'],'fallback')
 def test_expired_job_is_unavailable(self):
  j=Jobs(enabled=True,runner=lambda *a:ANSWER,ttl=.001);r=j.submit({'question':'Caulinita?','sources':[SOURCE]});time.sleep(.02)
  with self.assertRaises(KeyError):j.get(r['job_id'])

class Client:
 def __init__(self,row):self.row=row;self.calls=[]
 def call(self,path,payload=None):self.calls.append((path,payload));return copy.deepcopy(self.row)
class GatewayTests(unittest.TestCase):
 def test_refusal_does_not_enqueue(self):
  c=Client({'schema_version':'1.0','available':True,'sources':[]});r=start({'question':'bitcoin'},c)
  self.assertEqual(r['generation']['state'],'refused');self.assertEqual(len(c.calls),1)
 def test_source_revocation_or_change_discards_generated_prose(self):
  source={**SOURCE,'record_id':'public','updated':'v1'}
  row={'state':'complete','sources':[source],'sources_fingerprint':fingerprint([source]),'generated_answer':ANSWER,'validated':True}
  for resolver in [lambda _:None,lambda _:{'updated':'v2'}]:
   r=poll('id',Client(row),resolver=resolver);self.assertNotIn(ANSWER,r['answer']);self.assertEqual(r['sources'],[]);self.assertEqual(r['generation']['state'],'fallback')
 def test_verified_generation_can_be_published(self):
  row={'state':'complete','sources':[SOURCE],'sources_fingerprint':fingerprint([SOURCE]),'generated_answer':ANSWER,'validated':True,'limitations':['Verifique números no PDF.']}
  r=poll('id',Client(row));self.assertIn('Verifique números no PDF.',r['limitations']);self.assertEqual(r['answer'],ANSWER);self.assertEqual(r['generation_mode'],'rag_generated')
 def test_tampered_source_fingerprint_discards_prose(self):
  row={'state':'complete','sources':[SOURCE],'sources_fingerprint':'wrong','generated_answer':ANSWER,'validated':True}
  r=poll('id',Client(row));self.assertEqual(r['generation']['state'],'fallback');self.assertNotEqual(r['answer'],ANSWER)

if __name__=='__main__':unittest.main()

class BoundaryTests(unittest.TestCase):
 def test_supervisor_kills_worker_at_hard_deadline(self):
  import subprocess
  from unittest.mock import patch
  original=subprocess.Popen
  def sleeping_worker(*args,**kwargs):return original([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
  j=Jobs(enabled=True);started=time.monotonic()
  with patch('argiloclay_intelligence.generation.subprocess.Popen',side_effect=sleeping_worker),self.assertRaises(TimeoutError):
   j._run(prepare('Caulinita?',[SOURCE]),threading.Event(),time.monotonic()+.1)
  self.assertLess(time.monotonic()-started,1)
 def test_job_requires_owner_session_and_csrf(self):
  from flask import Flask,Blueprint
  from flask_login import LoginManager
  from flask_wtf.csrf import generate_csrf
  from unittest.mock import patch
  from argiloteca.argiloclay.routes import register
  app=Flask(__name__);app.secret_key='test-only';login=LoginManager(app);login.user_loader(lambda _:None)
  b=Blueprint('argiloteca',__name__);register(b);app.register_blueprint(b)
  @app.get('/csrf')
  def csrf():return {'token':generate_csrf()}
  a=app.test_client();other=app.test_client();key='a'*32
  token=a.get('/csrf').json['token'];other_token=other.get('/csrf').json['token']
  response={'schema_version':'1.0','available':True,'answer':'Evidence','sources':[SOURCE],'page_context':{'language':'pt'},'generation':{'state':'pending','job_id':key}}
  with patch('argiloteca.argiloclay.routes.async_service.start',return_value=response):
   self.assertEqual(a.post('/argiloclay/api/jobs',json={'question':'Caulinita?'}).status_code,400)
   self.assertEqual(a.post('/argiloclay/api/jobs',json={'question':'Caulinita?'},headers={'X-CSRFToken':token}).status_code,200)
  with patch('argiloteca.argiloclay.routes.async_service.poll',return_value=response) as upstream:
   self.assertEqual(other.get('/argiloclay/api/jobs/'+key,headers={'X-CSRFToken':other_token}).status_code,404);upstream.assert_not_called()
   self.assertEqual(a.get('/argiloclay/api/jobs/'+key,headers={'X-CSRFToken':token}).status_code,200)
  with a.session_transaction() as s:s['argiloclay_job_scope']='different-user'
  self.assertEqual(a.get('/argiloclay/api/jobs/'+key,headers={'X-CSRFToken':token}).status_code,404)

class RetrievalRoutingTests(unittest.TestCase):
 def test_controlled_names_use_vocabulary_instead_of_dataset_titles(self):
  from argiloclay_intelligence.workflow import query
  class Bridge:
   def call(self,name,args):self.name=name;self.args=args;return {'sources':[]}
  b=Bridge();query({'question':'Qual é o nome em inglês da caulinita?'},b)
  self.assertEqual(b.name,'lookup_vocabulary');self.assertIn('caulinita',b.args['term'])
