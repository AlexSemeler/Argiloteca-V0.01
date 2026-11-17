import json,sqlite3,unittest
from pathlib import Path
from unittest.mock import patch
from test_knowledge_library import KnowledgeTests,record
from argiloteca.argiloclay import batch_sync

class LibraryCoexistenceTests(unittest.TestCase):
 setUp=KnowledgeTests.setUp
 provider=KnowledgeTests.provider
 document=KnowledgeTests.document
 def publish_pdf(self):
  doc=self.document()['doc'];self.lib.review(doc,1,[1],'test',numeric=True);self.lib.index_approved('test');return doc
 def test_new_pdf_during_partial_refresh_preserves_progress_and_both_corpora(self):
  rows=[record(n) for n in range(3)];state=batch_sync.start(self.index,'test',1)
  batch_sync.step(self.index,self.provider(rows));doc=self.publish_pdf();active=batch_sync.sha(self.index)
  state2=batch_sync.step(self.index,self.provider(rows));self.assertEqual(state2['processed'],2);self.assertEqual(state2['run_id'],state['run_id']);self.assertEqual(state2['library_rebases'],1);self.assertEqual(batch_sync.sha(self.index),active)
  final=batch_sync.step(self.index,self.provider(rows));self.assertEqual(final['state'],'ok');self.assertEqual(final['public_records'],3)
  with sqlite3.connect(self.index) as c:
   self.assertEqual(c.execute("SELECT count(distinct json_extract(metadata,'$.record_id')) FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='registro_invenio'").fetchone()[0],3)
   self.assertGreater(c.execute("SELECT count(*) FROM docs WHERE json_extract(metadata,'$.library_id')=?",(doc,)).fetchone()[0],0)
   self.assertEqual(c.execute('SELECT count(*) FROM search').fetchone()[0],c.execute('SELECT count(*) FROM docs').fetchone()[0])
   self.assertTrue(c.execute("SELECT id FROM search WHERE search MATCH 'sintética'").fetchall())
 def test_public_base_change_still_blocks_publication(self):
  batch_sync.start(self.index);before=batch_sync.sha(self.index)
  with sqlite3.connect(self.index) as c:
   c.execute('INSERT INTO docs VALUES(?,?,?,?)',('record:external:c0','External','Current external update',json.dumps({'tipo_fonte':'registro_invenio','record_id':'external'})))
   c.execute('INSERT INTO search VALUES(?,?,?)',('record:external:c0','External','Current external update'))
  after=batch_sync.sha(self.index)
  with self.assertRaises(batch_sync.CheckpointConflict):batch_sync.step(self.index,self.provider([record(1)]))
  self.assertNotEqual(before,after);self.assertEqual(after,batch_sync.sha(self.index));self.assertEqual(batch_sync.state(self.index)['state'],'restart_required')
 def test_legacy_stale_checkpoint_requires_safe_explicit_restart_with_archive(self):
  start=batch_sync.start(self.index,'test',1);batch_sync.step(self.index,self.provider([record(1),record(2)]));status=batch_sync.state(self.index)
  status.pop('base_records_sha256');status.pop('base_manifest_sha256');batch_sync.save(self.index,status)
  self.publish_pdf();active=batch_sync.sha(self.index)
  with self.assertRaises(batch_sync.CheckpointConflict):batch_sync.step(self.index,self.provider([record(1),record(2)]))
  restarted=batch_sync.start(self.index,'reviewer',1,restart=True)
  self.assertNotEqual(restarted['run_id'],start['run_id']);self.assertEqual(restarted['processed'],0);self.assertEqual(batch_sync.sha(self.index),active)
  previous=restarted['previous_checkpoint'];self.assertEqual(previous['processed'],1)
  archived=self.index.parent/'versions/checkpoints'/previous['archive']
  self.assertTrue((archived/'status.json').is_file());self.assertTrue((archived/'checkpoint.sqlite3').is_file())
  self.assertEqual(batch_sync.sha(self.index.parent/'versions'/previous['backup']['name']),previous['backup']['sha256'])
 def test_completed_checkpoint_rebases_new_pdf_after_publish_interruption(self):
  batch_sync.start(self.index)
  original=batch_sync.os.replace
  def replace(src,dst):
   if str(src).endswith('.batch.sqlite3'):raise OSError('synthetic interrupted publication')
   return original(src,dst)
  with patch.object(batch_sync.os,'replace',side_effect=replace):
   with self.assertRaises(OSError):batch_sync.step(self.index,self.provider([record(1)]))
  doc=self.publish_pdf();final=batch_sync.step(self.index,self.provider([record(1)]));self.assertEqual(final['state'],'ok');self.assertEqual(final['processed'],1)
  with sqlite3.connect(self.index) as c:self.assertGreater(c.execute("SELECT count(*) FROM docs WHERE json_extract(metadata,'$.library_id')=?",(doc,)).fetchone()[0],0)
