"""Analytical enrichment invariants, using private temporary files only."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
from tempfile import TemporaryDirectory
from unittest.mock import patch,MagicMock
import json,sqlite3,unittest,uuid,zipfile
from flask import Flask
from argiloteca.openalex import enrichment as e,analytics


def work(oid='W1',doi='https://doi.org/10.1234/a',fwci=0,pct=None):
 return {'id':'https://openalex.org/'+oid,'doi':doi,'display_name':'A work',
 'primary_topic':{'id':'https://openalex.org/T1','display_name':'Clay','score':.9,'subfield':{'id':'https://openalex.org/subfields/1','display_name':'Sub'},'field':{'id':'https://openalex.org/fields/2','display_name':'Field'},'domain':{'id':'https://openalex.org/domains/3','display_name':'Domain'}},
 'topics':[],'fwci':fwci,'citation_normalized_percentile':pct,'cited_by_count':0,'counts_by_year':[],'updated_date':'2026-10-20'}


class Metrics(unittest.TestCase):
 def test_zero_and_absence_are_distinct(self):
  p=e.payload(work());self.assertEqual(p['fwci'],0);self.assertEqual(p['cited_by_count'],0);self.assertIsNone(p['citation_normalized_percentile']);self.assertEqual(p['counts_by_year'],[])
 def test_invalid_values_cannot_enter_overlay(self):
  for bad in (-1,float('nan'),float('inf'),True,'1'):
   with self.assertRaises(ValueError):e.payload(work(fwci=bad))
  with self.assertRaises(ValueError):e.payload(work(pct={'value':1.1}))
 def test_exact_id_doi_fallback_conflict_and_ambiguity(self):
  row={'oa_id':'W1','doi':'10.1234/a'}
  self.assertEqual(e.resolve(row,[work()])[0],'ready')
  self.assertEqual(e.resolve(row,[])[0],'missing')
  self.assertEqual(e.resolve(row,[work(doi='https://doi.org/10.1234/other')])[0],'blocked')
  self.assertEqual(e.resolve(row,[work(),work('W2')],True)[0],'blocked')
  self.assertEqual(e.resolve(row,[work('W2')],True)[0],'blocked')
  self.assertEqual(e.resolve({'oa_id':'','doi':'10.1234/a'},[work()],True)[0],'ready')
 def test_hierarchy_and_optional_topic(self):
  p=e.payload(work());self.assertEqual(p['primary_topic']['domain']['id'],'https://openalex.org/domains/3')
  w=work();w['primary_topic']=None;self.assertIsNone(e.payload(w)['primary_topic'])
 def test_retry_is_bounded(self):
  self.assertEqual(e.RetryLater(100000).seconds,86400);self.assertEqual(e.RetryLater(-10).seconds,2)


class PrivateVersions(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.app=Flask(__name__);self.app.config['ARGILOTECA_OPENALEX_QUEUE']=self.temp.name
  self.ctx=self.app.app_context();self.ctx.push();self.uid=str(uuid.uuid4());self.native={'id':'one','metadata':{'title':'Original','creators':[{'orcid':'untouched'}]},'files':{'existing':True},'communities':['keep']}
  self.preview=NS(id='a'*32,kind='enrich_collect',state='review',params={},actor=4,snapshot={},result={})
  c=sqlite3.connect(e.path_for(self.preview.id));c.execute('CREATE TABLE plan(uid TEXT PRIMARY KEY,rid TEXT,title TEXT,oa_id TEXT,doi TEXT,native_hash TEXT,old TEXT,proposed TEXT,status TEXT,reason TEXT,candidates TEXT)')
  self.proposal=e.payload(work());self.proposal['topics']=[{**self.proposal['primary_topic'],'id':'https://openalex.org/T2','display_name':'Additional'},self.proposal['primary_topic']];c.execute('INSERT INTO plan VALUES(?,?,?,?,?,?,?,?,?,?,?)',(self.uid,'one','Original','W1','10.1234/a',e.native_hash(self.native),'null',json.dumps(self.proposal),'ready','exact','[]'));c.commit();c.close()
  self.preview.snapshot={'sha256':e.sha(e.path_for(self.preview.id))}
  self.pointer=NS(version=None);self.jobs={self.preview.id:self.preview};self.fake_db=MagicMock();self.fake_db.session.get.side_effect=lambda cls,key:self.jobs.get(key)
  self.fake_db.session.query.return_value.filter_by.return_value.with_for_update.return_value.one.return_value=self.pointer
  @contextmanager
  def lock(*args):yield True
  self.patches=[patch.object(e,'db',self.fake_db),patch.object(e,'job_lock',lock),patch.object(e,'native',return_value=(self.native,'P'))]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.ctx.pop();self.temp.cleanup()
 def application(self,jid='b'*32):
  job=NS(id=jid,kind='enrich_apply',state='queued',actor=4,params={'preview':self.preview.id,'selection':[self.uid],'review':{'actor':4,'confirmation':'APLICAR'}},result={})
  self.jobs[jid]=job;return job
 def test_apply_backup_idempotence_and_restore(self):
  before=deepcopy(self.native);a=self.application();e.apply(a)
  self.assertEqual(a.result['changed'],1);self.assertEqual(self.pointer.version,a.id)
  with zipfile.ZipFile(e.path_for(a.id,'.zip')) as z:self.assertIsNone(z.testzip());self.assertIn('preview.sqlite',z.namelist())
  b=self.application('c'*32);e.apply(b);self.assertEqual((b.result['changed'],b.result['unchanged']),(0,1))
  with e.store(b.id) as c:self.assertEqual(c.execute('SELECT count(*) FROM accepted').fetchone()[0],1)
  e.path_for(a.id).unlink() # Exercise actual recovery from ZIP, not pointer-only recovery.
  r=NS(id='d'*32,params={'version':b.id},actor=4,result={});e.restore(r)
  self.assertEqual(self.pointer.version,a.id);self.assertTrue(e.path_for(a.id).exists())
  r2=NS(id='e'*32,params={'version':a.id},actor=4,result={});e.restore(r2);self.assertIsNone(self.pointer.version)
  self.assertEqual(self.native,before)
 def test_changed_native_record_is_preserved(self):
  self.native['metadata']['title']='New title';a=self.application();e.apply(a)
  self.assertEqual(a.result['changed'],0);self.assertEqual(len(a.result['failures']),1)
 def test_changed_plan_is_rejected(self):
  with e.store(self.preview.id,True) as c:c.execute("UPDATE plan SET status='blocked'")
  with self.assertRaises(ValueError):e.apply(self.application())
 def test_corrupt_backup_cannot_restore(self):
  a=self.application();e.apply(a);e.path_for(a.id,'.zip').write_bytes(b'corrupt')
  with self.assertRaises(ValueError):e.restore(NS(params={'version':a.id},actor=4))
  self.assertEqual(self.pointer.version,a.id)
 def test_checkpoint_resume_and_retry_do_not_refetch_completed_rows(self):
  with e.store(self.preview.id,True) as c:
   c.execute('DELETE FROM plan')
   for n in range(105):
    c.execute('INSERT INTO plan VALUES(?,?,?,?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),str(n),'Title','W'+str(n+1),'10.1234/a','native','null',None,'pending','','[]'))
  self.preview.state='queued';self.preview.result={}
  with patch.object(e,'initialize'),patch.object(e,'fetch',side_effect=e.RetryLater(45)):
   self.assertEqual(e.collect_chunk(self.preview),0);self.assertEqual(self.preview.state,'waiting_api')
  with e.store(self.preview.id) as c:self.assertEqual(e.progress(c)['processed'],0)
  self.preview.result['retry_at']=0
  with patch.object(e,'initialize'),patch.object(e,'fetch',side_effect=lambda query:[work(oid) for oid in query.split(':',1)[1].split('|')]):
   e.collect_chunk(self.preview)
  with e.store(self.preview.id) as c:self.assertEqual(e.progress(c)['processed'],100)
  with patch.object(e,'initialize'),patch.object(e,'fetch',side_effect=lambda query:[work(oid) for oid in query.split(':',1)[1].split('|')]) as fetch:
   e.collect_chunk(self.preview);self.assertEqual(fetch.call_count,1)
   self.assertEqual(e.collect_chunk(self.preview),0)
  self.assertEqual(self.preview.state,'review');self.assertEqual(self.preview.result['ready'],105)
  e.validate_plan(self.preview)
 def test_stale_analytical_values_and_blocked_selection(self):
  with e.store(self.preview.id,True) as c:c.execute("UPDATE plan SET old=?",(json.dumps({'fwci':42}),))
  self.preview.snapshot['sha256']=e.sha(e.path_for(self.preview.id))
  a=self.application();e.apply(a);self.assertEqual(a.result['changed'],0);self.assertEqual(len(a.result['failures']),1)
  with e.store(self.preview.id,True) as c:c.execute("UPDATE plan SET status='blocked'")
  self.preview.snapshot['sha256']=e.sha(e.path_for(self.preview.id))
  with self.assertRaises(ValueError):e.apply(self.application('c'*32))
 def test_manual_ambiguity_review_forks_without_mutating_original(self):
  from argiloteca.openalex import enrichment_views as v
  with e.store(self.preview.id,True) as c:
   c.execute("UPDATE plan SET status='blocked',candidates=?",(json.dumps([{'id':self.proposal['id'],'payload':self.proposal}]),))
  original=e.sha(e.path_for(self.preview.id));self.preview.snapshot['sha256']=original
  saved=[]
  def add(job):saved.append(job)
  self.fake_db.session.add.side_effect=add
  self.fake_db.session.flush.side_effect=lambda:setattr(saved[-1],'id','f'*32)
  with self.app.test_request_context('/review',method='POST',data={'uid':self.uid,'candidate':self.proposal['id'],'note':'Confirmed against DOI source','confirm':'REVISADO','plan_sha256':original}),patch.object(v,'get_job',return_value=self.preview),patch.object(v,'db',self.fake_db),patch.object(v,'current_user',NS(id=4)),patch.object(v,'target',side_effect=lambda j:j):
   fork=v.enrichment_review(self.preview.id)
  self.assertEqual(e.sha(e.path_for(self.preview.id)),original)
  self.assertEqual(fork.snapshot['identity_review']['actor'],4)
  with e.store(fork.id) as c:self.assertEqual(c.execute('SELECT status FROM plan').fetchone()[0],'ready')
  self.assertIsNone(self.pointer.version)
 def test_interrupted_activation_keeps_backup_and_active_pointer(self):
  a=self.application()
  with patch.object(e,'native',side_effect=[(self.native,'P'),({'changed':'during backup'},'P')]):
   with self.assertRaises(ValueError):e.apply(a)
  self.assertIsNone(self.pointer.version);self.assertEqual(a.result['phase'],'backup_verified')
  self.assertTrue(e.path_for(a.id,'.zip').exists())
 def test_unsafe_path_rejected(self):
  with self.assertRaises(ValueError):e.path_for('../secret')
 def test_statistics_exact_filters_missing_and_csv_population(self):
  a=self.application();e.apply(a)
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.executescript('CREATE TABLE works(rid,title,year,type,oa_id,doi,source_id,source,source_type,issn,citations,collected);CREATE TABLE authorship(rid,aid,name,orcid);CREATE TABLE tags(rid,kind,id,label);')
  c.executemany('INSERT INTO works VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',[('one','One',2020,'article','W1','10.1234/a',None,None,None,None,0,None),('two','Two',2021,'article','W2',None,None,None,None,None,None,None)])
  d=analytics.statistics(c,enrichment=a.id);cov={r['id']:r for r in d['coverage']}
  self.assertEqual((cov['fwci']['n'],cov['fwci']['missing']),(1,1));self.assertEqual(d['fwci'][0]['n'],1);self.assertEqual(len(d['additional_topics']),1);self.assertEqual(d['additional_topics'][0]['id'],'https://openalex.org/T2')
  self.assertIsNone(d['top_groups'][0]['share']);self.assertEqual(sum(r['n'] for r in d['primary_topic']),1)
  d=analytics.statistics(c,domain='https://openalex.org/domains/3',enrichment=a.id)
  self.assertEqual(d['total'],1);self.assertEqual(c.execute('SELECT count(*) FROM measures').fetchone()[0],1)
  d=analytics.statistics(c,domain='https://openalex.org/domains/99',enrichment=a.id);self.assertEqual(d['total'],0)
  c.close()

if __name__=='__main__':unittest.main()
