import hashlib,json,sqlite3,tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'argiloteca_custom'))
from argiloteca.argiloclay.openalex_pdfs import Staging

class StagingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.stage=Staging(self.tmp.name);self.stage.root.mkdir();(self.stage.root/'pdfs').mkdir()
  self.data=b'%PDF-1.4\nprivate synthetic document\n';self.id='a'*64
  self.item={'id':self.id,'filename':'doi_'+self.id+'.pdf','sha256':hashlib.sha256(self.data).hexdigest(),'bytes':len(self.data),'title':'Clay test','category':'license_not_confirmed'}
  self.path=self.stage.root/'pdfs'/self.item['filename'];self.path.write_bytes(self.data)
  with sqlite3.connect(self.stage.db) as c:
   c.execute('CREATE TABLE pdfs(id TEXT PRIMARY KEY,title TEXT,search TEXT,category TEXT,data TEXT)')
   c.execute('INSERT INTO pdfs VALUES(?,?,?,?,?)',(self.id,'Clay test','clay test','license_not_confirmed',json.dumps(self.item)))
 def test_private_pdf_integrity_and_lookup(self):
  self.assertEqual(self.stage.verified_file(self.stage.get(self.id)),self.path)
  self.assertEqual(self.stage.listing(q='clay')[1],1);self.assertEqual(self.stage.listing(q='missing')[1],0)
  self.assertEqual(self.stage.listing(category='candidate_open_license')[1],0)
 def test_changed_file_and_signature_rejected(self):
  self.path.write_bytes(b'X'*len(self.data))
  with self.assertRaises(ValueError):self.stage.verified_file(self.item)
  self.path.write_bytes(self.data.replace(b'private',b'changed'))
  with self.assertRaises(ValueError):self.stage.verified_file(self.item)
 def test_traversal_and_symlink_rejected(self):
  with self.assertRaises(KeyError):self.stage.get('../catalog.sqlite3')
  with self.assertRaises(ValueError):self.stage.verified_file({**self.item,'filename':'../file.pdf'})
  target=self.stage.root/'elsewhere.pdf';target.write_bytes(self.data);self.path.unlink();self.path.symlink_to(target)
  with self.assertRaises(ValueError):self.stage.verified_file(self.item)
 def test_missing_stage_is_empty(self):
  self.stage.db.unlink();self.assertEqual(self.stage.listing(),([],0))
