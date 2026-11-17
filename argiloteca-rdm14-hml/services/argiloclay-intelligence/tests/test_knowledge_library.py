import io,json,sqlite3,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloclay_intelligence.corpus import build
from argiloclay_intelligence.engine import Engine,managed_allowed
from argiloteca.argiloclay import batch_sync
from argiloteca.argiloclay.knowledge import Library
from argiloteca.argiloclay.public_metadata import project

def record(n):return project({'id':f'test-{n}','updated':'2026-10-29T00:00:00Z','access':{'record':'public'},'metadata':{'title':'Caulinita','description':'Argilas e caulinita em estudo.'}},'https://example.org')

class KnowledgeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  for name in ('argilominerais','grupo_mineralogico'):(self.root/(name+'.jsonl')).write_text(json.dumps({'id':'kaolinite','title':{'pt':'Caulinita','en':'Kaolinite'},'props':{'category':'species'}}))
  self.index=self.root/'knowledge.sqlite3';build(self.index,self.root);self.lib=Library(self.root/'private',self.index)
 def provider(self,rows,fail=False):
  def get(c,size):
   values=[]
   for row in rows:
    if c.execute('SELECT 1 FROM sync_seen WHERE rid=?',(row['record_id'],)).fetchone():continue
    if len(values)==size:return values,False
    values.append(row)
   if fail:raise OSError('synthetic failure')
   return values,True
  return get
 def document(self,access='public'):
  r=self.lib.upload(io.BytesIO(b'%PDF-1.4\nsynthetic fixture only'),{'title':'Synthetic kaolinite reference','origin':'test','rights':'synthetic test only','access':access,'minerals':'kaolinite'},'test')
  with self.lib.connect() as c:
   c.execute("UPDATE versions SET state='review' WHERE doc=?",(r['doc'],));c.execute('INSERT INTO pages(doc,version,page,text,method,warnings) VALUES(?,?,?,?,?,?)',(r['doc'],1,1,'Kaolinite é denominada caulinita. Esta referência sintética testa a recuperação documental, sem validade científica e sem dados experimentais.','synthetic','[]'))
  return r
 def test_batch_atomic_resume_and_idempotence(self):
  rows=[record(n) for n in range(5)];before=self.index.read_bytes();batch_sync.start(self.index,'test',2)
  for n in (2,4):
   r=batch_sync.step(self.index,self.provider(rows));self.assertEqual(r['processed'],n);self.assertEqual(before,self.index.read_bytes())
  r=batch_sync.step(self.index,self.provider(rows));self.assertEqual(r['public_records'],5);self.assertEqual(r['state'],'ok')
  self.assertEqual(batch_sync.sha(self.index.parent/'versions'/r['backup']['name']),r['backup']['sha256'])
  batch_sync.start(self.index,'test',2)
  while batch_sync.state(self.index)['state']!='ok':r=batch_sync.step(self.index,self.provider(rows))
  self.assertEqual(r['unchanged'],5);self.assertEqual(r['added'],0)
 def test_partial_scan_failure_preserves_and_resumes(self):
  batch_sync.start(self.index);before=self.index.read_bytes()
  with self.assertRaises(OSError):batch_sync.step(self.index,self.provider([record(1)],True))
  self.assertEqual(before,self.index.read_bytes());self.assertEqual(batch_sync.step(self.index,self.provider([record(1)]))['state'],'ok')
 def test_generation_conflict(self):
  batch_sync.start(self.index)
  with sqlite3.connect(self.index) as c:c.execute("UPDATE manifest SET value=json_set(value,'$.test',1)")
  with self.assertRaises(ValueError):batch_sync.step(self.index,self.provider([]))
 def test_removal_only_after_exhaustion(self):
  batch_sync.start(self.index);batch_sync.step(self.index,self.provider([record(1),record(2)]));batch_sync.start(self.index)
  before=self.index.read_bytes();batch_sync.step(self.index,lambda c,s:([record(1)],False));self.assertEqual(before,self.index.read_bytes())
  self.assertEqual(batch_sync.step(self.index,self.provider([record(1)]))['removed'],1)
 def test_hash_duplicate_rejection_and_single_writer(self):
  batch_sync.start(self.index);before=self.index.read_bytes()
  for rows in [[{**record(1),'sha256':'bad'}],[record(1),record(1)]]:
   with self.assertRaises(ValueError):batch_sync.step(self.index,lambda c,s:(rows,True))
   self.assertEqual(before,self.index.read_bytes())
  with batch_sync.writer_lock(self.index):self.assertEqual(batch_sync.step(self.index,self.provider([]))['state'],'busy')
 def test_pdf_duplicate_hash(self):
  a=self.document();b=self.lib.upload(io.BytesIO(self.lib.path(a['doc'],1).read_bytes()),{'title':'other','origin':'test','rights':'test','access':'restricted'},'test')
  self.assertTrue(b['duplicate']);self.assertEqual(a['doc'],b['doc'])
 def test_approval_revocation_and_policy_failure(self):
  a=self.document();self.lib.index_approved('test');self.assertEqual(Engine(self.index).query('caulinita',{'tipo_fonte':'literatura_pdf'})['sources'],[])
  with self.assertRaises(ValueError):self.lib.review(a['doc'],1,[1],'test',numeric=False)
  self.lib.review(a['doc'],1,[1],'test',numeric=True);self.lib.index_approved('test')
  sources=Engine(self.index).query('caulinita',{'tipo_fonte':'literatura_pdf'})['sources'];self.assertTrue(sources);self.assertTrue(self.lib.source_allowed(sources[0]))
  self.assertFalse(self.lib.source_allowed({**sources[0],'excerpt':'fabricated evidence'}))
  self.lib.withdraw(a['doc'],1,'test');self.assertFalse(self.lib.source_allowed(sources[0]));self.assertEqual(Engine(self.index).query('caulinita',{'tipo_fonte':'literatura_pdf'})['sources'],[])
  self.index.with_suffix('.access.json').unlink();self.assertFalse(managed_allowed(self.index,sources[0]))
 def test_private_approved_not_indexed(self):
  a=self.document('restricted');self.lib.review(a['doc'],1,[1],'test',numeric=True);self.lib.index_approved('test')
  self.assertEqual(Engine(self.index).query('caulinita',{'tipo_fonte':'literatura_pdf'})['sources'],[])
 def test_restore_does_not_restore_permissions(self):
  a=self.document();self.lib.review(a['doc'],1,[1],'test',numeric=True);self.lib.index_approved('test');saved=batch_sync.backup(self.index,'test');self.lib.withdraw(a['doc'],1,'test')
  with self.assertRaises(ValueError):self.lib.restore_index(saved['name'],'bad','test')
  self.lib.restore_index(saved['name'],saved['sha256'],'test');self.assertEqual(Engine(self.index).query('caulinita',{'tipo_fonte':'literatura_pdf'})['sources'],[])
  self.lib.restore_document(a['doc'],1,'test');self.assertFalse(self.lib.get(a['doc'])['pages'][0]['approved'])
 def test_upload_path_signature_and_url(self):
  with self.assertRaises(ValueError):self.lib.path('../escape',1)
  for data,meta in [(b'not pdf',{}),(b'%PDF-1.4',{'url':'javascript:alert(1)'})]:
   with self.assertRaises(ValueError):self.lib.upload(io.BytesIO(data),{'title':'a','origin':'test','rights':'test','access':'public',**meta},'test')

if __name__=='__main__':unittest.main()

class PublicationRecoveryTests(unittest.TestCase):
 setUp=KnowledgeTests.setUp
 provider=KnowledgeTests.provider
 def test_interruption_after_completed_staging_is_resumable(self):
  from unittest.mock import patch
  batch_sync.start(self.index)
  with patch.object(batch_sync.os,'replace',side_effect=lambda src,dst: (_ for _ in ()).throw(OSError('synthetic publication failure')) if str(src).endswith('.batch.sqlite3') else __import__('os').rename(src,dst)):
   with self.assertRaises(OSError):batch_sync.step(self.index,self.provider([record(1)]))
  r=batch_sync.step(self.index,self.provider([record(1)]));self.assertEqual(r['state'],'ok');self.assertEqual(r['added'],1)
 def test_interruption_after_atomic_publish_recovers_manifest_receipt(self):
  from unittest.mock import patch
  batch_sync.start(self.index);original=batch_sync.save
  def save(index,value):
   if value.get('state')=='ok':raise OSError('synthetic sidecar failure')
   original(index,value)
  with patch.object(batch_sync,'save',side_effect=save):
   with self.assertRaises(OSError):batch_sync.step(self.index,self.provider([record(1)]))
  r=batch_sync.step(self.index,self.provider([record(1)]));self.assertEqual(r['state'],'ok');self.assertEqual(r['public_records'],1)
