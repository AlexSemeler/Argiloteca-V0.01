from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch,MagicMock
from flask import Flask
import sqlite3
from argiloteca.openalex import analytics,orcid

ORCID='0000-0002-0177-3342'

def creators():
 return [{'person_or_org':{'type':'personal','given_name':'James B.','family_name':'Harsh','identifiers':[{'scheme':'isni','identifier':'other'}]},'affiliations':[{'name':'Existing institute'}]},
         {'person_or_org':{'type':'personal','given_name':'Another','family_name':'Author'}}]

class NativeOrcidTests(unittest.TestCase):
 def test_job_errors_preserve_both_languages(self):
  error=orcid.ReviewError('ORCID inválido.')
  self.assertEqual(str(error),'ORCID inválido.');self.assertEqual(error.message_en,'Invalid ORCID.')
 def test_checksum_and_confined_identifier(self):
  self.assertEqual(orcid.normalize_orcid('https://orcid.org/'+ORCID),ORCID)
  for v in ('0000-0002-0177-3341','http://evil.test/'+ORCID,ORCID+'/person','x'*100):self.assertIsNone(orcid.normalize_orcid(v))
 def test_addition_preserves_native_authors_and_all_other_fields(self):
  before=creators();original=deepcopy(before);after=orcid.add_identifier(before,[0],ORCID)
  self.assertEqual(before,original);self.assertEqual(len(after),len(before));self.assertEqual(after[1],before[1])
  restored=deepcopy(after);restored[0]['person_or_org']['identifiers'].pop();self.assertEqual(restored,before)
  self.assertEqual(orcid.add_identifier(after,[0],ORCID),after)
 def test_existing_conflicting_or_invalid_orcid_is_not_overwritten(self):
  for value in ('0000-0001-5109-3700','bad'):
   authors=creators();authors[0]['person_or_org']['identifiers'].append({'scheme':'orcid','identifier':value})
   with self.assertRaises(ValueError):orcid.add_identifier(authors,[0],ORCID)
 def test_same_orcid_cannot_be_assigned_to_two_authors(self):
  with self.assertRaises(ValueError):orcid.add_identifier(creators(),[0,1],ORCID)
  authors=orcid.add_identifier(creators(),[0],ORCID)
  with self.assertRaises(ValueError):orcid.add_identifier(authors,[1],ORCID)
 def test_organization_and_absent_slots_rejected(self):
  with self.assertRaises(ValueError):orcid.add_identifier(creators(),[20],ORCID)
  with self.assertRaises(ValueError):orcid.add_identifier([{'person_or_org':{'type':'organizational','name':'Lab'}}],[0],ORCID)
 def test_name_group_is_not_an_identity_or_creator_position(self):
  a=creators()[0];b=deepcopy(a);b['affiliations']=[]
  self.assertEqual(analytics.creator_group(a),analytics.creator_group(b))
  self.assertEqual(analytics.creator_name(a),'James B. Harsh')
  self.assertEqual(analytics.name_key('José À. Silva'),'jose a silva')
 def test_only_orcid_addition_passes_preservation_guard(self):
  before={'metadata':{'title':'same','creators':creators()},'parent':{'communities':{'ids':['c']},'access':{'owned_by':{'user':'4'}}},'files':{'entries':{'curve.raw':{'checksum':'md5:original','size':10}}},'access':{'record':'public'},'pids':{'doi':{'identifier':'10.1/x'}}}
  expected=orcid.add_identifier(creators(),[0],ORCID);after=deepcopy(before);after['metadata']['creators']=expected
  orcid.verify_addition(before,after,expected)
  for field in ('metadata','files','parent','access','pids'):
   changed=deepcopy(after);changed[field]={}
   with self.assertRaises(ValueError):orcid.verify_addition(before,changed,expected)
 def test_payload_does_not_reassign_managed_pids_or_access(self):
  value=orcid.edit_payload({'metadata':{'creators':creators()},'custom_fields':{'science':1},'pids':{'oai':{}},'access':{'record':'restricted'},'files':{'enabled':True,'entries':{'a':{}}}},creators())
  self.assertNotIn('pids',value);self.assertNotIn('access',value);self.assertNotIn('entries',value['files']);self.assertEqual(value['custom_fields'],{'science':1})
 def test_query_quoting_disallows_control_characters(self):
  self.assertEqual(orcid.quote('A" OR *:*'),'"A\\" OR *:*"')
  with self.assertRaises(ValueError):orcid.quote('a\nb')
 def test_registry_client_cannot_use_arbitrary_urls(self):
  with self.assertRaises(ValueError):orcid.request_public('http://127.0.0.1/person')
 def test_registry_errors_are_actionable_and_do_not_return_partial_data(self):
  app=Flask(__name__)
  with app.app_context(),patch.object(orcid.requests,'get') as get:
   get.return_value.__enter__.return_value.status_code=429
   with self.assertRaisesRegex(ValueError,'Limite'):orcid.request_public('expanded-search/')
 def test_search_discards_email_and_preserves_bounded_candidate_metadata(self):
  app=Flask(__name__);job=SimpleNamespace(params={'given':'James','family':'Harsh'},result={})
  with app.app_context(),patch.object(orcid,'request_public',return_value={'num-found':1,'expanded-result':[{'orcid-id':ORCID,'given-names':'James','family-names':'Harsh','email':['not-needed@example.org'],'institution-name':['WSU']}]}):
   orcid.search(job)
  self.assertEqual(job.state,'review');self.assertNotIn('email',str(job.snapshot));self.assertEqual(job.snapshot['candidates'][0]['orcid'],ORCID)

class StatisticsTests(unittest.TestCase):
 def setUp(self):
  self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
  self.c.executescript('CREATE TABLE works(rid,title,year,type,oa_id,doi,source_id,source,source_type,issn,citations,collected);CREATE TABLE authorship(rid,aid,name,orcid);CREATE TABLE tags(rid,kind,id,label);')
  self.c.executemany('INSERT INTO works VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[('one','One',2020,'article','W1','d1','S1','Journal','journal','issn',0,'lot'),('two','Two',2021,'article','W2','d2','S1','Journal','journal','issn',12,'lot'),('three','Three',2021,'book','W3','d3','S2','Books','book series',None,None,'lot')])
  self.c.executemany('INSERT INTO authorship VALUES(?,?,?,?)',[('one','A1','J Doe',None),('two','A1','John Doe',None),('two','A2','Coauthor',None)])
  self.c.executemany('INSERT INTO tags VALUES(?,?,?,?)',[('one','subject','C1','Kaolinite'),('two','subject','C1','Kaolinite'),('two','country','BR','BR')])
 def tearDown(self):self.c.close()
 def test_distinct_work_counts_and_zero_citations_are_not_missing(self):
  d=analytics.statistics(self.c);self.assertEqual((d['total'],d['with_citations']),(3,2));self.assertEqual(d['authors'][0]['n'],2);self.assertEqual(len(d['authors']),2)
 def test_all_missing_citations_remain_missing(self):
  self.c.execute('UPDATE works SET citations=NULL')
  d=analytics.statistics(self.c);self.assertIsNone(d['summary']['citations']);self.assertEqual(d['with_citations'],0)
 def test_filters_apply_consistently_to_rankings_and_coverage(self):
  d=analytics.statistics(self.c,year_from=2021,source_type='journal',subject='kaolinite')
  self.assertEqual(d['total'],1);self.assertEqual(d['journals'][0]['n'],1);self.assertEqual(d['subject'][0]['n'],1);self.assertEqual(d['citations'][0]['rid'],'two')
 def test_chart_totals_share_the_filtered_population(self):
  d=analytics.statistics(self.c)
  self.assertEqual(d['summary'],{'sources':2,'citations':12,'first_year':2020,'last_year':2021,'authors':2})
  self.assertEqual(sum(r['n'] for r in d['source_types']),d['total'])
  filtered=analytics.statistics(self.c,year_from=2021,source_type='journal',subject='kaolinite')
  self.assertEqual(filtered['summary'],{'sources':1,'citations':12,'first_year':2021,'last_year':2021,'authors':2})
  self.assertEqual(filtered['source_types'],[{'label':'journal','n':1}])
 def test_missing_source_type_is_counted_without_inventing_a_category(self):
  self.c.execute("UPDATE works SET source_type=NULL WHERE rid='three'")
  d=analytics.statistics(self.c)
  self.assertEqual(sum(r['n'] for r in d['source_types']),3)
  self.assertIn({'label':None,'n':1},d['source_types'])
 def test_empty_chart_summary_retains_missing_years(self):
  d=analytics.statistics(self.c,year_from=2030)
  self.assertEqual(d['summary'],{'sources':0,'citations':0,'first_year':None,'last_year':None,'authors':0})
  self.assertEqual(d['source_types'],[])
 def test_missing_source_is_locale_neutral(self):
  self.c.execute("UPDATE works SET source=NULL,source_id=NULL WHERE rid='one'")
  d=analytics.statistics(self.c);self.assertIn(None,[r['label'] for r in d['journals']]);self.assertNotIn('Sem fonte',str(d))
 def test_empty_selection_does_not_invent_rankings(self):
  d=analytics.statistics(self.c,year_from=2030);self.assertEqual(d['total'],0);self.assertEqual(d['authors'],[])
 def test_work_ids_only_use_declared_identifiers(self):
  value={'metadata':{'description':'https://openalex.org/W999','identifiers':[{'scheme':'url','identifier':'https://openalex.org/W123'}]}}
  self.assertEqual(analytics.work_ids(value),{'W123'})

if __name__=='__main__':unittest.main()
