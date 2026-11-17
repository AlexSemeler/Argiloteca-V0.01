import copy,fcntl,hashlib,json,sqlite3,tempfile,unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloclay_intelligence.corpus import build
from argiloclay_intelligence.public_metadata import project,field_requests
from argiloclay_intelligence.workflow import query as workflow
from argiloteca.argiloclay.presentation import record_source,didactic_answer
from argiloteca.argiloclay.index_sync import synchronize,static_digest


def record(**kw):
 r={'id':'abcde-12345','updated':'2026-10-22T10:00:00+00:00','created':'2025-02-01T12:30:00+00:00','access':{'record':'public'},
    'metadata':{'title':'Argilas','creators':[{'person_or_org':{'name':'Silva, Ana','identifiers':[{'scheme':'orcid','identifier':'0000-0001-0002-0003'}]}}],
    'contributors':[{'person_or_org':{'name':'Laboratório CPAA'}}],'publication_date':'2020-05-03','description':'Descrição pública de caulinita.'}}
 r.update(kw);return r

class MetadataTests(unittest.TestCase):
 def test_projection_names_dates_and_no_system_fields(self):
  r=record();r['secret']='never';r['parent']={'access':{'owned_by':{'email':'hidden'}}};p=project(r,'https://example.org')
  self.assertIn('Silva, Ana',p['text']);self.assertIn('2025-02-01',p['text']);self.assertNotIn('hidden',p['text']);self.assertNotIn('never',p['text'])
 def test_singular_plural_and_additional_title_intents(self):
  for q,key in [('Quem é o autor deste registro?','creators'),('Quem é o criador deste registro?','creators'),('Qual é o identificador deste registro?','identifiers'),('Quem é o colaborador deste registro?','contributors'),('Quais são os títulos alternativos deste registro?','additional_titles')]:
   self.assertIn(key,field_requests(q),q)
 def test_projection_rejects_private_and_draft_sources(self):
  for r in [record(access={'record':'restricted'}),record(is_draft=True),record(is_published=False)]:
   with self.assertRaises(ValueError):project(r,'https://example.org')
 def test_fact_fields_render_actual_values_with_citation(self):
  for q,wanted in [('Quem são os autores deste registro?','Silva, Ana'),('Qual é a data de publicação deste registro?','2020-05-03'),('Quando este registro foi criado?','2025-02-01'),('Quando foi a última atualização deste registro?','2026-10-22'),('Quais são os colaboradores deste registro?','Laboratório CPAA')]:
   source=record_source(record(),'abcde-12345',q);answer=didactic_answer(q,[source]);self.assertIn(wanted,answer);self.assertIn('[Fonte 1]',answer)
 def test_absent_field_is_scoped_to_public_metadata(self):
  source=record_source(record(),'abcde-12345','Qual é a licença deste registro?');answer=didactic_answer('licença',[source]);self.assertIn('Não informado nestes metadados públicos',answer)
 def test_structured_intent_does_not_rewrite_unrelated_question(self):
  for q in ['Qual é a data do preço do bitcoin neste registro?','Quem é o autor do assassinato neste registro?','Explique este registro']:
   self.assertFalse(field_requests(q),q)
 def test_routing_domain_concepts_and_record_fields(self):
  class Bridge:
   def call(self,tool,args):self.tool=tool;self.args=args;return {'sources':[]}
  with patch.dict('os.environ',{'ARGILOCLAY_LEGACY_URL':'http://drx:7860'}):
   for q in ['Lei de Bragg','Lei de Bragg no DRX','O que é a equação de Bragg?','O que é d-spacing?']:
    b=Bridge();workflow({'question':q,'context':{'section':'drx'}},b);self.assertEqual(b.tool,'search_drx',q)
  for q in ['Quem são os autores deste registro?','Qual é a data de publicação deste registro?','Quem são os colaboradores deste registro?']:
   b=Bridge();workflow({'question':q,'context':{'record_ids':['abcde-12345']}},b);self.assertEqual(b.tool,'get_public_record')
 def test_shared_projection_contract(self):
  from argiloteca.argiloclay import public_metadata as native
  self.assertEqual(project(record(),'https://example.org'),native.project(record(),'https://example.org'))

class SyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for name in ['argilominerais','grupo_mineralogico']:(self.root/(name+'.jsonl')).write_text(json.dumps({'id':'kaolinite','title':{'pt':'Caulinita'},'props':{'category':'species'}}))
  self.index=self.root/'knowledge.sqlite3';build(self.index,self.root)
 def snapshot(self,rows):return lambda:iter([project(r,'https://example.org') for r in rows])
 def read(self):
  with sqlite3.connect(self.index) as c:return list(c.execute('select id,text,metadata from docs order by id'))
 def test_lifecycle_add_update_delete_visibility_and_idempotence(self):
  a=record();b=record(id='other-12345')
  first=synchronize(self.index,self.snapshot([a,b]));self.assertEqual(first['added'],2)
  again=synchronize(self.index,self.snapshot([a,b]));self.assertEqual(again['unchanged'],2);self.assertEqual(again['updated'],0)
  a=copy.deepcopy(a);a['updated']='2026-10-23T10:00:00+00:00';a['metadata']['creators'][0]['person_or_org']['name']='Oliveira, Ana'
  changed=synchronize(self.index,self.snapshot([a]));self.assertEqual(changed['updated'],1);self.assertEqual(changed['removed'],1)
  self.assertIn('Oliveira, Ana',str(self.read()));self.assertNotIn('Silva, Ana',str(self.read()))
  empty=synchronize(self.index,self.snapshot([]));self.assertEqual(empty['removed'],1);self.assertNotIn('record:',str(self.read()))
  self.assertEqual(first['static_corpus_sha256'],empty['static_corpus_sha256'])
 def test_partial_failure_preserves_valid_index_and_last_success(self):
  ok=synchronize(self.index,self.snapshot([record()]));before=self.index.read_bytes()
  def fails():
   yield project(record(id='new-12345'),'https://example.org')
   raise OSError('upstream unavailable')
  with self.assertRaises(OSError):synchronize(self.index,fails)
  self.assertEqual(before,self.index.read_bytes());status=json.loads(self.index.with_suffix('.sync-status.json').read_text());self.assertEqual(status['state'],'error');self.assertEqual(status['last_success_at'],ok['last_success_at'])
 def test_status_permissions_allow_the_separate_read_only_query_service(self):
  import stat
  synchronize(self.index,self.snapshot([record()]));status=self.index.with_suffix('.sync-status.json')
  self.assertEqual(stat.S_IMODE(status.stat().st_mode),0o644)
  def fails():raise OSError('temporary export error')
  with self.assertRaises(OSError):synchronize(self.index,fails)
  self.assertEqual(stat.S_IMODE(status.stat().st_mode),0o644)
  self.assertEqual(json.loads(status.read_text())['state'],'error')
 def test_malformed_duplicate_hash_and_private_snapshot_rejected(self):
  p=project(record(),'https://example.org')
  for values in [[p,p],[{**p,'access':'restricted'}],[{**p,'sha256':'bad'}]]:
   before=self.index.read_bytes()
   with self.assertRaises(ValueError):synchronize(self.index,lambda:iter(values))
   self.assertEqual(before,self.index.read_bytes())
 def test_simultaneous_runs_do_not_replace_or_overwrite_active_job(self):
  with self.index.with_suffix('.sync.lock').open('a') as f:
   fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);result=synchronize(self.index,self.snapshot([record()]));self.assertEqual(result['state'],'busy')
 def test_live_read_connection_survives_atomic_replacement(self):
  with sqlite3.connect(self.index) as c:
   original=static_digest(c);synchronize(self.index,self.snapshot([record()]));self.assertEqual(static_digest(c),original)
  self.assertIn('record:',str(self.read()))
 def test_incremental_delete_resolves_sparse_fts_rowids_without_touching_static_sources(self):
  a=record();b=record(id='other-12345');first=synchronize(self.index,self.snapshot([a,b]))
  with sqlite3.connect(self.index) as c:
   rows=list(c.execute('select id,title,text from search'));c.execute('delete from search')
   c.executemany('insert into search(rowid,id,title,text) values(?,?,?,?)',[(10000+n,*row) for n,row in enumerate(rows)])
  a['metadata']['creators'][0]['person_or_org']['name']='Oliveira, Ana'
  result=synchronize(self.index,self.snapshot([a]));self.assertEqual(result['removed'],1);self.assertEqual(result['updated'],1)
  with sqlite3.connect(self.index) as c:
   self.assertTrue(list(c.execute("select id from search where search match 'Oliveira'")))
   self.assertFalse(list(c.execute("select id from search where id like 'record:other-%'")))
   self.assertEqual(static_digest(c),first['static_corpus_sha256'])
 def test_missing_search_row_aborts_without_publishing_inconsistent_replacement(self):
  a=record();synchronize(self.index,self.snapshot([a]))
  with sqlite3.connect(self.index) as c:c.execute("delete from search where id like 'record:%'")
  before=self.index.read_bytes();a['metadata']['title']='Metadados alterados'
  with self.assertRaises(ValueError):synchronize(self.index,self.snapshot([a]))
  self.assertEqual(before,self.index.read_bytes())

if __name__=='__main__':unittest.main()

class WorkerConnectionTests(unittest.TestCase):
 def test_inference_uses_fixed_runtime_origin_and_rejects_arbitrary_hosts(self):
  from argiloclay_intelligence import generation_worker as w
  from io import BytesIO,StringIO
  from types import SimpleNamespace
  for origin in ['http://127.0.0.1:11434','http://host.docker.internal:11434','http://evil.example']:
   requests=[]
   def response(req,**kw):
    requests.append(req.full_url)
    return BytesIO(json.dumps({'done_reason':'stop','message':{'content':'Texto [Fonte 1].'}}).encode())
   with patch.dict('os.environ',{'ARGILOCLAY_OLLAMA_URL':origin}),patch.object(w.sys,'stdin',SimpleNamespace(buffer=BytesIO(json.dumps({'quote':'Evidência','question':'Qual?'}).encode()))),patch.object(w.sys,'stdout',StringIO()),patch.object(w,'urlopen',response):
    if 'evil' in origin:
     with self.assertRaises(ValueError):w.main()
     self.assertEqual(requests,[])
    else:
     w.main();self.assertEqual(requests,[origin+'/api/chat'])

class BoundaryKindsTests(unittest.TestCase):
 def test_access_and_tool_unavailable_remain_distinct_from_no_evidence(self):
  from flask import Flask,Blueprint
  from argiloteca.argiloclay import routes
  from argiloteca.argiloclay.service import PublicContextUnavailable,Unavailable
  app=Flask(__name__);app.secret_key='test-only';bp=Blueprint('boundary',__name__);routes.register(bp);app.register_blueprint(bp)
  for error,status,kind in [(PublicContextUnavailable('Contexto indisponível'),400,'access_unavailable'),(Unavailable('MCP indisponível'),503,'tool_unavailable')]:
   with patch.object(routes,'guard',return_value=None),patch.object(routes,'query',side_effect=error):
    r=app.test_client().post('/argiloclay/api/query',json={'question':'Dados?'})
   self.assertEqual(r.status_code,status);self.assertEqual(r.json['response_kind'],kind)

class LateSyncFailureTests(unittest.TestCase):
 setUp=SyncTests.setUp
 snapshot=SyncTests.snapshot
 def test_failed_post_write_validation_keeps_previous_index(self):
  import argiloteca.argiloclay.index_sync as sync
  synchronize(self.index,self.snapshot([record()]));before=self.index.read_bytes()
  with patch.object(sync,'static_digest',side_effect=['original','changed']):
   with self.assertRaises(ValueError):synchronize(self.index,self.snapshot([record(id='new-12345')]))
  self.assertEqual(before,self.index.read_bytes());self.assertEqual(list(self.root.glob('.knowledge-sync-*')),[])
  self.assertEqual(synchronize(self.index,self.snapshot([record()]))['state'],'ok')
