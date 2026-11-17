"""Census grain, provenance and identity regressions using synthetic data."""
from copy import deepcopy
import json
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from flask import Flask

from argiloteca.population import configure
from argiloteca.population import snapshot as s, queries as q
from argiloteca.openalex.analytics import add_occurrences
from argiloteca.openalex.adapters import digest
from argiloteca.population import orcid as po

VALID='0000-0002-0177-3342'

def payload(rid='r1', doi='10.1234/test', name='José Silva', orcid=None):
    person={'type':'personal','name':name}
    if orcid: person['identifiers']=[{'scheme':'orcid','identifier':orcid}]
    return {'id':rid,'metadata':{'title':'Argila e caulinita','publication_date':'2024','resource_type':{'id':'dataset'},
            'creators':[{'person_or_org':person}], 'identifiers':[{'scheme':'doi','identifier':doi}]}}

class CensusTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:');self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE occurrences(key TEXT,gid TEXT,rid TEXT,kind TEXT,slot INTEGER,name TEXT,title TEXT,creator TEXT,uuid TEXT,existing_orcid TEXT,oa_id TEXT,doi TEXT);
            CREATE TABLE candidates(occurrence TEXT,orcid TEXT,source TEXT,body TEXT,UNIQUE(occurrence,orcid,source));''')
        s.schema(self.c)
    def tearDown(self): self.c.close()
    def native(self, rid='r1', kind='published', **kwargs):
        data=payload(rid=rid,**kwargs);s.native_record(self.c,rid+kind,data,kind);add_occurrences(self.c,rid+kind,data,kind);return data
    def test_publication_and_draft_count_once_with_effective_authorship(self):
        self.native(name='Old author');self.native(kind='draft',name='New author');s.consolidate(self.c)
        data=q.summary(self.c,{})
        self.assertEqual((data['total'],data['published'],data['drafts'],data['editing'],data['authors']),(1,1,0,1,1))
        self.assertEqual(self.c.execute('SELECT name FROM p_authors').fetchone()[0],'New author')
        self.assertTrue(self.c.execute('SELECT native_key FROM p_authors').fetchone()[0])
    def test_draft_only_separate_from_published(self):
        self.native(kind='draft');s.consolidate(self.c);self.assertEqual(q.summary(self.c,{})['drafts'],1)
    def test_source_observations_are_not_extra_records_or_authors(self):
        data=self.native(orcid=VALID)
        for source in ('openalex','pangaea','mendeley'):
            s.add_entry(self.c,source,source+'_lot','k',data)
        s.consolidate(self.c);data=q.summary(self.c,{})
        self.assertEqual((data['total'],data['authors'],data['profiles']),(1,1,1))
        self.assertEqual(self.c.execute('SELECT count(*) FROM p_sources').fetchone()[0],3)
    def test_recovered_transitive_identity_links_not_titles(self):
        a=payload(doi='10.1234/a');b=payload(doi='10.1234/a');b['metadata']['identifiers'].append({'scheme':'url','identifier':'https://openalex.org/W123'})
        c=payload(doi='10.1234/c');c['metadata']['identifiers'].append({'scheme':'url','identifier':'https://openalex.org/W123'})
        d=payload(doi='10.1234/d')
        for n,p in enumerate((a,b,c,d)):s.add_entry(self.c,'openalex','lot',str(n),p)
        s.consolidate(self.c);self.assertEqual(q.summary(self.c,{})['recovered'],2)
    def test_duplicate_native_rids_are_preserved_and_flagged(self):
        self.native('r1');self.native('r2');s.add_entry(self.c,'mendeley','lot','k',payload());s.consolidate(self.c)
        self.assertEqual(q.summary(self.c,{})['total'],3);self.assertEqual(q.summary(self.c,{})['conflicts'],3)
    def test_identifiers_do_not_mine_references_or_lookalike_hosts(self):
        p=payload(doi='');p['metadata']['description']='doi:10.1234/reference';p['metadata']['identifiers']=[{'scheme':'url','identifier':'https://lume.ufrgs.br.evil.test/handle/10183/12'}]
        self.assertEqual(s.identifiers(p),set())
    def test_valid_source_orcid_produces_same_work_suggestion(self):
        self.native();s.add_entry(self.c,'pangaea','lot','k',payload(orcid=VALID));s.consolidate(self.c)
        row=self.c.execute('SELECT * FROM candidates').fetchone();self.assertEqual(row['source'],'PANGAEA');self.assertEqual(row['orcid'],VALID)
        self.assertEqual(q.summary(self.c,{})['missing'],1)
    def test_homonym_on_another_work_is_not_suggested(self):
        self.native();s.add_entry(self.c,'mendeley','lot','k',payload(doi='10.1234/another',orcid=VALID));s.consolidate(self.c)
        self.assertEqual(self.c.execute('SELECT count(*) FROM candidates').fetchone()[0],0)
    def test_organization_excluded_and_invalid_orcid_not_linked(self):
        p=payload(orcid='bad');p['metadata']['creators'].append({'person_or_org':{'type':'organizational','name':'Lab'}})
        s.add_entry(self.c,'mendeley','lot','k',p);s.consolidate(self.c);data=q.summary(self.c,{})
        self.assertEqual((data['authors'],data['linked'],data['orcid_conflicts']),(1,0,1))
    def test_conflicting_valid_orcids_not_counted_as_profile(self):
        creator=payload(orcid=VALID)['metadata']['creators'][0]
        creator['person_or_org']['identifiers'].append({'scheme':'orcid','identifier':'0000-0001-5109-3700'})
        self.assertEqual(s.orcid_state(creator)[1],'conflict')
    def test_filter_counts_and_export_listing_match(self):
        self.native(name='José Silva');s.add_entry(self.c,'mendeley','lot','k',payload());s.consolidate(self.c)
        rows,count=q.listing(self.c,{'source':'mendeley','q':'jose','status':'missing'},authors=True)
        self.assertEqual(count,len(rows));self.assertEqual(count,1)
        self.assertEqual(q.listing(self.c,{'source':'ufsc'})[1],0)
    def test_source_memberships_are_non_additive(self):
        self.native();s.add_entry(self.c,'mendeley','l1','k',payload());s.add_entry(self.c,'pangaea','l2','k',payload());s.consolidate(self.c)
        self.assertEqual(sum(row['total'] for row in q.source_summary(self.c)),2);self.assertEqual(q.summary(self.c,{})['total'],1)
    def test_unknown_source_is_explicit(self):
        self.native();s.consolidate(self.c);self.assertEqual(q.summary(self.c,{'source':'unknown'})['published'],1)
    def test_source_revised_author_order_is_preserved(self):
        a=payload(name='First');a['metadata']['creators'].append({'person_or_org':{'type':'personal','name':'Second'}})
        s.add_entry(self.c,'mendeley','lot','k',a,'review');s.consolidate(self.c)
        self.assertEqual([r[0] for r in self.c.execute('SELECT name FROM p_authors ORDER BY slot')],['First','Second'])

class RevisionTests(unittest.TestCase):
    def test_revised_job_preserves_other_corrections_and_source(self):
        params={'lot':'men_test','corrections':{'k':{'title':'Original corrected title'},'other':{'description':'keep'}}}
        source=SimpleNamespace(id='source',state='review',kind='men_prepare',params=deepcopy(params),snapshot={})
        p=payload();before=p['metadata']['creators'];after=deepcopy(before);after[0]['person_or_org']['identifiers']=[{'scheme':'orcid','identifier':VALID}]
        plan={'source_job':'source','source_params_sha':digest(params),'analysis':'a','row_key':'k','payload_sha':digest(p),'after_creators':after}
        preview=SimpleNamespace(id='preview',kind='pop_orcid_preview',state='review',actor=4,snapshot=plan)
        with patch.object(po.db.session,'get',side_effect=[source,SimpleNamespace()]),patch.object(po,'checked_analysis'),patch.object(po,'iter_records',return_value=iter([{'payload':p}])):
            job=po.revised_job(preview,4,'reviewed')
        self.assertEqual(source.params,params);self.assertEqual(job.params['corrections']['k']['title'],'Original corrected title')
        self.assertEqual(job.params['corrections']['other'],params['corrections']['other']);self.assertEqual(job.params['corrections']['k']['creators'],after)
        self.assertEqual(job.params['population_orcid_review']['preview'],'preview')
    def test_cross_actor_and_changed_source_rejected(self):
        p=SimpleNamespace(kind='pop_orcid_preview',state='review',actor=4,snapshot={'source_job':'s'})
        with patch.object(po.db.session,'get',return_value=SimpleNamespace(state='review')):
            with self.assertRaises(ValueError):po.revised_job(p,5,'')
    def test_nonlocal_feature_disabled_by_default(self):
        app=Flask(__name__);app.config['SITE_UI_URL']='https://argiloteca.example.org';configure(app)
        self.assertFalse(app.config['ARGILOTECA_POPULATION_ENABLED']);self.assertNotIn('argiloteca_population',app.blueprints)

class SourceIntegrityTests(unittest.TestCase):
    setUp = CensusTests.setUp
    tearDown = CensusTests.tearDown
    def test_incomplete_and_tampered_lots_are_excluded_not_empty_success(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);parent=base/'lotes';parent.mkdir()
            incomplete=parent/'men_incomplete';incomplete.mkdir();(incomplete/'resultado.json').write_text(json.dumps({'status':'running'}))
            corrupt=parent/'men_corrupt';corrupt.mkdir();(corrupt/'records.json').write_text('[]')
            (corrupt/'resultado.json').write_text(json.dumps({'status':'coleta_concluida','payloads':1,'input_hashes':{'records.json':'0'*64}}))
            app=Flask(__name__);app.config.update(ARGILOTECA_OPENALEX_ROOT=str(base/'missing'),ARGILOTECA_MENDELEY_ROOT=str(base))
            with app.app_context(),patch('argiloteca.openalex.models.OpenAlexJob.query') as jobs:
                jobs.filter.return_value.order_by.return_value.yield_per.return_value=[]
                s.source_lots(self.c)
            self.assertEqual(self.c.execute('SELECT count(*) FROM p_entries').fetchone()[0],0)
            self.assertEqual(self.c.execute('SELECT count(*) FROM p_warnings').fetchone()[0],2)
    def test_closed_lot_with_no_matches_is_explicit_and_hash_preserved(self):
        from argiloteca.openalex.preview import file_hash
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);folder=base/'lotes'/'men_valid';folder.mkdir(parents=True)
            (folder/'records.json').write_text('[]');sha=file_hash(folder/'records.json')
            (folder/'resultado.json').write_text(json.dumps({'status':'coleta_concluida','payloads':0,'input_hashes':{'records.json':sha}}))
            app=Flask(__name__);app.config.update(ARGILOTECA_OPENALEX_ROOT=str(base/'missing'),ARGILOTECA_MENDELEY_ROOT=str(base))
            with app.app_context(),patch('argiloteca.openalex.models.OpenAlexJob.query') as jobs:
                jobs.filter.return_value.order_by.return_value.yield_per.return_value=[];s.source_lots(self.c)
            self.assertEqual(self.c.execute('SELECT count,sha FROM p_lots').fetchone()[:],(0,sha))
    def test_openalex_array_positions_keep_all_collected_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);folder=base/'lotes'/'v59_fixture';folder.mkdir(parents=True)
            rows=[payload(doi='10.1234/'+str(n)) for n in range(3)]
            (folder/'openalex_argiloteca.json').write_text(json.dumps(rows))
            (folder/'resultado.json').write_text(json.dumps({'status':'coleta_concluida','payloads':3}))
            app=Flask(__name__);app.config.update(ARGILOTECA_OPENALEX_ROOT=str(base))
            with app.app_context(),patch('argiloteca.openalex.models.OpenAlexJob.query') as jobs:
                jobs.filter.return_value.order_by.return_value.yield_per.return_value=[];s.source_lots(self.c)
            self.assertEqual(self.c.execute('SELECT count(*) FROM p_entries').fetchone()[0],3)
            s.consolidate(self.c);self.assertEqual(q.summary(self.c,{})['recovered'],3)
    def test_distinct_observations_may_share_one_review_row(self):
        for seq in (1,2):s.add_entry(self.c,'openalex','lot','merged-key',payload(),'review',observation=seq)
        self.assertEqual(self.c.execute('SELECT count(*) FROM p_entries').fetchone()[0],2)
        s.consolidate(self.c);self.assertEqual(q.summary(self.c,{})['recovered'],1)

    def test_native_managed_doi_does_not_hide_declared_source_doi(self):
        data=payload(doi='10.1234/source');data['pids']={'doi':{'identifier':'10.1234/native'}}
        self.assertEqual(s.identifiers(data),{'doi:10.1234/native','doi:10.1234/source'})
    def test_configured_fixture_exclusion_is_reported_without_touching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);folder=base/'lotes'/'men_fixture';folder.mkdir(parents=True)
            path=folder/'resultado.json';path.write_text('{"status":"coleta_concluida","payloads":0}')
            original=path.read_bytes();app=Flask(__name__);app.config.update(ARGILOTECA_OPENALEX_ROOT=str(base/'none'),ARGILOTECA_MENDELEY_ROOT=str(base),ARGILOTECA_POPULATION_EXCLUDED_LOTS={'men_fixture':'Synthetic regression fixture'})
            with app.app_context(),patch('argiloteca.openalex.models.OpenAlexJob.query') as jobs:
                jobs.filter.return_value.order_by.return_value.yield_per.return_value=[];s.source_lots(self.c)
            self.assertEqual(path.read_bytes(),original);self.assertEqual(self.c.execute('SELECT count(*) FROM p_lots').fetchone()[0],0)
            self.assertIn('Synthetic regression fixture',self.c.execute('SELECT message FROM p_warnings').fetchone()[0])
