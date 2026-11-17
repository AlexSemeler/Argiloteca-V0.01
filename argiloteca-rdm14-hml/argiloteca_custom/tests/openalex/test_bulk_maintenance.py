"""Bulk identity, scope, grouping and narrow ORCID removal contracts."""
from copy import deepcopy
import json,time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from flask import Flask
from argiloteca.openalex import bulk_maintenance as bulk
from argiloteca.openalex.maintenance import remove_orcid
from argiloteca.openalex.adapters import digest


def metadata():
 return {'title':'Preserve this publication','creators':[
  {'person_or_org':{'type':'personal','given_name':'Ana','family_name':'Silva','identifiers':[{'scheme':'orcid','identifier':'0000-0002-1825-0097'},{'scheme':'gnd','identifier':'123'}]},'affiliations':[{'name':'UFRGS'}]},
  {'person_or_org':{'type':'personal','name':'Ana Silva','identifiers':[{'scheme':'orcid','identifier':'0000-0001-5109-3700'}]}}],
  'identifiers':[{'scheme':'doi','identifier':'10.1234/preserve'}]}

def occurrence(md,slot):return {'slot':slot,'creator_sha256':digest(md['creators'][slot])}

class BulkTests(unittest.TestCase):
 def setUp(self):
  self.app=Flask(__name__);self.app.secret_key='unit-test-only';self.ctx=self.app.app_context();self.ctx.push();self.addCleanup(self.ctx.pop)
  self.actor=patch.object(bulk,'current_user',SimpleNamespace(id=7));self.actor.start();self.addCleanup(self.actor.stop)
  self.lang=patch.object(bulk,'t',lambda pt,en:en);self.lang.start();self.addCleanup(self.lang.stop)
 def test_selection_is_bound_to_actor(self):
  value=bulk.token('job','a'*32)
  self.assertEqual(bulk.read_choices([value],7)[0]['target'],'a'*32)
  with self.assertRaises(ValueError):bulk.read_choices([value],8)
 def test_tampered_selection_rejected(self):
  with self.assertRaises(ValueError):bulk.read_choices([bulk.token('job','a'*32)+'bad'],7)
 def test_expired_selection_rejected(self):
  value=bulk.token('job','a'*32)
  with patch('itsdangerous.timed.time.time',return_value=time.time()+3602):
   with self.assertRaises(ValueError):bulk.read_choices([value],7)
 def test_empty_and_oversize_selection_rejected(self):
  for values in ([],['x']*101,['x'*4097]):
   with self.assertRaises(ValueError):bulk.read_choices(values,7)
 def test_duplicates_are_collapsed(self):
  value=bulk.token('job','a'*32);self.assertEqual(len(bulk.read_choices([value,value],7)),1)
 def test_operations_cannot_cross_object_scope(self):
  for kind,op in [('job','unlink'),('record','archive'),('orcid','delete'),('drx_link','delete')]:
   with self.assertRaises(ValueError):bulk.specification({'kind':kind,'target':'x'},op)
 def test_record_deletion_selects_native_kind(self):
  for kind,expected in [('draft','delete_draft'),('published','purge_published')]:
   self.assertEqual(bulk.specification(dict(kind='record',target='abcde-12345',record_kind=kind),'delete')['action'],expected)
 def test_same_record_and_action_deduplicate(self):
  item=dict(kind='record',target='abcde-12345',record_kind='draft')
  self.assertEqual(len(bulk.grouped_specs([item,item],'delete')),1)
 def test_two_orcid_occurrences_group_into_one_record_write(self):
  md=metadata();items=[dict(kind='orcid',target='abcde-12345',record_kind='published',occurrence=occurrence(md,i)) for i in (0,1)]
  specs=bulk.grouped_specs(items,'unlink');self.assertEqual(len(specs),1)
  self.assertEqual(len(json.loads(specs[0]['selection'])),2)
 def test_multiple_drx_links_group_by_record(self):
  rows=[dict(kind='drx_link',target='abcde-12345',raw_id=key*24) for key in ('a','b')]
  result=bulk.grouped_specs(rows,'unlink');self.assertEqual(len(result),1)
  self.assertEqual(result[0]['action'],'remove_drx_many');self.assertEqual(len(json.loads(result[0]['selection'])),2)
 def test_distinct_records_remain_distinct(self):
  rows=[dict(kind='record',target=key,record_kind='published') for key in ('abcde-12345','vwxyz-67890')]
  self.assertEqual(len(bulk.grouped_specs(rows,'delete')),2)
 def test_orcid_removal_preserves_person_other_ids_and_publication(self):
  md=metadata();before=deepcopy(md);result=remove_orcid(md,json.dumps(occurrence(md,0)))
  self.assertEqual(md,before);expected=deepcopy(md);expected['creators'][0]['person_or_org']['identifiers']=[{'scheme':'gnd','identifier':'123'}]
  self.assertEqual(result,expected)
 def test_two_selected_homonyms_only_remove_their_identifiers(self):
  md=metadata();result=remove_orcid(md,json.dumps([occurrence(md,i) for i in (0,1)]))
  self.assertEqual(len(result['creators']),2);self.assertEqual(result['creators'][1]['person_or_org']['name'],'Ana Silva')
  self.assertNotIn('identifiers',result['creators'][1]['person_or_org'])
  self.assertEqual(result['title'],md['title'])
 def test_stale_creator_cannot_remove_a_different_person(self):
  md=metadata();choice=occurrence(md,0);md['creators'].reverse()
  with self.assertRaises(ValueError):remove_orcid(md,json.dumps(choice))
 def test_non_person_and_invalid_slots_are_rejected(self):
  md=metadata()
  for slot in (-1,True,'0',10):
   with self.assertRaises(ValueError):remove_orcid(md,json.dumps({'slot':slot,'creator_sha256':'x'}))
  md['creators'][0]['person_or_org']['type']='organizational'
  with self.assertRaises(ValueError):remove_orcid(md,json.dumps(occurrence(md,0)))
 def test_removed_association_is_not_silently_reapplied(self):
  md=metadata();choice=occurrence(md,0);updated=remove_orcid(md,json.dumps(choice))
  with self.assertRaises(ValueError):remove_orcid(updated,json.dumps(choice))
 def test_malformed_selection_is_rejected(self):
  for value in ('not JSON','[]','null','true','{}'):
   with self.assertRaises(ValueError):remove_orcid(metadata(),value)
 def test_missing_orcid_is_not_a_person_delete(self):
  md=metadata();md['creators'][0]['person_or_org']['identifiers']=[{'scheme':'gnd','identifier':'123'}];before=deepcopy(md)
  with self.assertRaises(ValueError):remove_orcid(md,json.dumps(occurrence(md,0)))
  self.assertEqual(md,before)
 def test_review_exclusion_does_not_resolve_to_native_deletion(self):
  item=dict(kind='import_row',target='a'*32,row_key='row1',native_id='abcde-12345',record_kind='published')
  spec=bulk.specification(item,'exclude');self.assertEqual((spec['kind'],spec['target'],spec['action']),('job','a'*32,'exclude_candidates'))
 def test_review_without_native_record_can_be_excluded_but_not_purged(self):
  item=dict(kind='import_row',target='a'*32,row_key='row1',native_id='',record_kind='')
  self.assertEqual(bulk.specification(item,'exclude')['action'],'exclude_candidates')
  with self.assertRaises(ValueError):bulk.specification(item,'delete')
 def test_review_rows_are_grouped_without_losing_keys(self):
  items=[dict(kind='import_row',target='a'*32,row_key=key,native_id='',record_kind='') for key in ('one','two')]
  specs=bulk.grouped_specs(items,'exclude');self.assertEqual(len(specs),1);self.assertEqual(json.loads(specs[0]['selection']),['one','two'])
 def test_inline_excluded_rows_are_neither_listed_nor_importable(self):
  from argiloteca.openalex.preview import iter_records,page_records
  rows=[{'key':key,'status':'apto','payload':{'metadata':{'title':key}},'identity':{}} for key in ('one','two')]
  source={'records':rows,'admin_excluded_records':['one']}
  self.assertEqual([row['key'] for row in iter_records(source)],['two'])
  self.assertEqual(list(iter_records(source,{'one'})),[])
  self.assertEqual(page_records(source)[1],1);self.assertEqual(len(source['records']),2)
 def test_disk_exclusion_preserves_original_artifact_and_hash(self):
  from contextlib import closing
  import tempfile
  from pathlib import Path
  from argiloteca.openalex import preview
  with tempfile.TemporaryDirectory() as folder:
   self.app.config['ARGILOTECA_OPENALEX_QUEUE']=folder
   path=Path(folder,'previews','a'*32+'.sqlite');path.parent.mkdir()
   with closing(preview.connect(path)) as connection:
    connection.execute('CREATE TABLE records(seq INTEGER PRIMARY KEY,key TEXT,body TEXT,sha256 TEXT,search TEXT,status TEXT)')
    for i,key in enumerate(('one','two')):
     row={'key':key,'status':'apto','payload':{'metadata':{'title':key}},'identity':{}}
     connection.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(i,key,json.dumps(row),digest(row),key,'apto'))
    connection.commit()
   original=preview.file_hash(path)
   source={'record_store':{'schema':1,'id':'a'*32,'bytes':path.stat().st_size,'sha256':original},'admin_excluded_records':['one']}
   self.assertEqual([row['key'] for row in preview.iter_records(source)],['two'])
   self.assertEqual(preview.page_records(source)[1],1)
   self.assertEqual(list(preview.iter_records(source,{'one'})),[])
   self.assertEqual(preview.file_hash(path),original)
