import io,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloteca.argiloclay.knowledge import Library,ExtractionError,EXTRACT_BATCH_PAGES

class PDFExtractionBatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.index=self.root/'knowledge.sqlite3';self.index.write_bytes(b'unchanged analytical index fixture')
  self.lib=Library(self.root/'private',self.index)
  self.item=self.lib.upload(io.BytesIO(b'%PDF-1.4\nSynthetic fixture only; no scientific content.'),{'title':'Synthetic long document','rights':'test only','origin':'test','access':'restricted'},'test')
  self.doc=self.item['doc'];self.calls=[]
 def parser(self,count,fail=None):
  def run(args,**kwargs):
   if args[0]=='pdfinfo':return SimpleNamespace(stdout='Pages: '+str(count)+'\n')
   if args[0]=='pdftotext':
    page=int(args[args.index('-f')+1]);self.calls.append(page)
    if page==fail:raise subprocess.TimeoutExpired('pdftotext',30)
    Path(args[-1]).write_text('Synthetic test page '+str(page)+'. '+('Content requiring human review. '*5));return SimpleNamespace(stdout='')
   raise AssertionError(args[0])
  return run
 def test_477_pages_use_bounded_batches_and_stay_unapproved(self):
  with patch('argiloteca.argiloclay.knowledge.subprocess.run',side_effect=self.parser(477)):
   batches=[]
   while True:
    result=self.lib.extract(self.doc,1);batches.append(result)
    self.assertLessEqual(result['batch_pages'],EXTRACT_BATCH_PAGES)
    if result['state']=='review':break
  self.assertEqual(len(batches),20);self.assertEqual(len(set(self.calls)),477);self.assertEqual(len(self.calls),477)
  item=self.lib.get(self.doc);self.assertEqual(item['extraction']['total_pages'],477);self.assertEqual(item['extracted_pages'],477)
  self.assertFalse(any(p['approved'] or p['numeric_review'] for p in item['pages']))
  self.assertEqual(self.index.read_bytes(),b'unchanged analytical index fixture')
 def test_page_cap_retained_and_error_explains_count(self):
  with patch('argiloteca.argiloclay.knowledge.subprocess.run',side_effect=self.parser(1001)):
   with self.assertRaises(ExtractionError):self.lib.extract(self.doc,1)
  error=json.loads(self.lib.get(self.doc)['error']);self.assertEqual(error,{'code':'page_limit','total_pages':1001,'limit':1000});self.assertEqual(self.calls,[])
 def test_failed_page_resumes_without_overwriting_completed_review(self):
  with patch('argiloteca.argiloclay.knowledge.subprocess.run',side_effect=self.parser(30,fail=4)):
   with self.assertRaises(subprocess.TimeoutExpired):self.lib.extract(self.doc,1)
  self.assertEqual(self.lib.get(self.doc)['extracted_pages'],3)
  with self.lib.connect() as c:c.execute("UPDATE pages SET text='Previously corrected text',approved=1,numeric_review=1,reviewer='reviewer' WHERE doc=? AND page=1",(self.doc,))
  self.calls=[]
  with patch('argiloteca.argiloclay.knowledge.subprocess.run',side_effect=self.parser(30)):
   while self.lib.extract(self.doc,1)['state']!='review':pass
  self.assertEqual(self.calls,list(range(4,31)));p=self.lib.get(self.doc)['pages'][0]
  self.assertEqual(p['text'],'Previously corrected text');self.assertEqual(p['reviewer'],'reviewer');self.assertTrue(p['approved'])
 def test_original_hash_mismatch_stops_before_parser(self):
  self.lib.path(self.doc,1).write_bytes(b'%PDF-1.4 changed')
  with patch('argiloteca.argiloclay.knowledge.subprocess.run') as parser:
   with self.assertRaises(ExtractionError):self.lib.extract(self.doc,1)
  parser.assert_not_called();self.assertEqual(json.loads(self.lib.get(self.doc)['error'])['code'],'original_changed')
 def test_non_pending_document_is_not_reextracted(self):
  with self.lib.connect() as c:c.execute("UPDATE versions SET state='approved' WHERE doc=?",(self.doc,))
  with patch('argiloteca.argiloclay.knowledge.subprocess.run') as parser:r=self.lib.extract(self.doc,1)
  self.assertEqual(r['state'],'approved');parser.assert_not_called()
 def test_time_budget_returns_checkpoint_instead_of_waiting_for_task_timeout(self):
  with patch('argiloteca.argiloclay.knowledge.subprocess.run',side_effect=self.parser(100)),patch('argiloteca.argiloclay.knowledge.time.monotonic',side_effect=[0,0,46]):
   r=self.lib.extract(self.doc,1)
  self.assertEqual(r['pages'],1);self.assertEqual(r['state'],'extracting')

if __name__=='__main__':unittest.main()
