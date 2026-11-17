"""Disposable filesystem tests: verified backups, retirement and crash recovery."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
from argiloteca.scientific import raw_removal as raw

class RawRemovalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.app=Flask(__name__);self.app.config['ARGILOTECA_OPENALEX_BACKUPS']=str(self.root/'backups')
  ctx=self.app.app_context();ctx.push();self.addCleanup(ctx.pop)
  self.folder=self.root/'files';self.folder.mkdir();self.path=self.folder/'ARC-AAAAAAAAAAAAAAAA_N.raw';self.path.write_bytes(b'disposable raw')
  self.info=raw.file_info(self.path,[self.folder])
  self.plan={'kind':'raw','raw':{'binaries':[self.info],'rows':[{'id':'a'*24,'filename':self.path.name,'sha256':self.info['sha256']}]}}
  self.job=SimpleNamespace(id='a'*32,actor=4,snapshot={'plan':self.plan},result={},state='queued')
 def backup(self):
  self.job.result={'backup':raw.write_backup(self.job,self.plan),'raw_deletion':{'phase':'cleanup','rows':self.plan['raw']['rows']}}
 def finish(self):
  with patch.object(raw,'roots',return_value=[self.folder]),patch('argiloteca.scientific.admin_raw_views.store'),patch.object(raw,'db'):
   raw.finish(self.job)
 def test_backup_contains_verified_bytes_before_unlink(self):
  self.backup();self.assertTrue(self.path.exists());raw.verify_backup(self.job,self.plan,self.job.result['backup'])
  self.finish();self.assertFalse(self.path.exists());self.assertEqual(self.job.result['raw_deletion']['phase'],'complete')
 def test_tampered_backup_preserves_raw(self):
  self.backup();(self.root/'backups'/('a'*32+'.zip')).write_bytes(b'tampered')
  with self.assertRaises(ValueError):self.finish()
  self.assertTrue(self.path.exists())
 def test_changed_raw_is_preserved(self):
  self.backup();self.path.write_bytes(b'new different content')
  with self.assertRaises(ValueError):self.finish()
  self.assertEqual(self.path.read_bytes(),b'new different content')
 def test_missing_checkpoint_cannot_delete(self):
  self.backup();self.job.result.pop('raw_deletion')
  with self.assertRaises(ValueError):self.finish()
  self.assertTrue(self.path.exists())
 def test_recovery_accepts_only_already_missing_approved_files(self):
  self.backup();self.path.unlink();other=self.folder/'untouched.raw';other.write_bytes(b'preserve')
  self.finish();self.assertTrue(other.exists());self.assertEqual(self.job.state,'completed')
 def test_symlink_and_outside_roots_are_rejected(self):
  other=self.root/'outside.raw';other.write_bytes(b'preserve')
  link=self.folder/'link.raw';link.symlink_to(other)
  for path in (link,other):
   with self.assertRaises(ValueError):raw.checked_path(path,[self.folder])
 def test_all_files_checked_before_first_unlink(self):
  second=self.folder/'ARC-AAAAAAAAAAAAAAAA_G.raw';second.write_bytes(b'second');self.plan['raw']['binaries'].append(raw.file_info(second,[self.folder]));self.backup();second.write_bytes(b'changed')
  with self.assertRaises(ValueError):self.finish()
  self.assertTrue(self.path.exists())
 def test_raw_selection_groups_shared_files_once(self):
  from argiloteca.openalex.bulk_maintenance import grouped_specs
  choices=[{'kind':'drx_link','target':'record1','raw_id':'a'*24},{'kind':'drx_link','target':'record2','raw_id':'a'*24},{'kind':'drx_raw','target':'b'*24}]
  specs=grouped_specs(choices,'delete_raw');self.assertEqual(len(specs),1);self.assertEqual(json.loads(specs[0]['selection']),['a'*24,'b'*24])
 def test_registry_without_real_app_is_empty(self):self.assertEqual(raw.retired(),set())
 def test_retired_file_is_absent_from_public_snapshot_and_download_lookup(self):
  from argiloteca.services import drx
  row={'filename':self.path.name,'path':str(self.path)}
  with patch.object(drx,'_load_json_payload',return_value={'results':[row]}),patch.object(raw,'retired',return_value={self.path.name}):
   self.assertEqual(drx._iter_raw_snapshot_rows(),[])
   self.assertIsNone(drx._snapshot_row_by_id(drx._snapshot_id_for_path(str(self.path))))
 def test_retired_file_is_absent_from_private_library_and_stale_content(self):
  from argiloteca.scientific.admin_raw_store import AdminRawStore
  repository=AdminRawStore(self.root,self.root/'uploads');row={'id':'a'*24,'filename':self.path.name}
  with patch.object(repository,'uploaded',return_value=[row]),patch.object(repository,'historical',return_value={'rows':[]}),patch.object(raw,'retired',return_value={'a'*24}):
   self.assertEqual(repository.rows(),[])
   with self.assertRaises(KeyError):repository.get('a'*24)
   with self.assertRaises(FileNotFoundError):repository.content(row)
