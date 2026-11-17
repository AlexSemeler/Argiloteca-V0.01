"""Consolidation rules and fail-closed backups, without modifying native records."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from flask import Flask
from argiloteca.openalex.duplicates import merge_values, file_plan, plan_group, fingerprint, write_backup


def row(rid='one', kind='published', description='Curto', entries=None):
    data = {'id':rid,'created':'2026-01-01','revision_id':1,
        'metadata':{'title':'Teste','description':description,'identifiers':[{'scheme':'doi','identifier':'10.1234/test'}]},
        'custom_fields':{},'parent':{'id':'parent-'+rid,'access':{'owned_by':{'user':'4'}},'communities':{'ids':[]}},
        'access':{'record':'restricted','files':'restricted','embargo':{'active':False},'status':'metadata-only'},
        'pids':{},'versions':{'index':1},
        'files':{'enabled':bool(entries),'entries':entries or {},'count':len(entries or {})},
        'media_files':{'enabled':False,'entries':{},'count':0}}
    return {'id':rid,'kind':kind,'tokens':['doi:10.1234/test'],'data':data,'pending_edit':False}


class MergeTests(unittest.TestCase):
    def test_homonymous_creators_with_distinct_orcids_remain_separate(self):
        def person(orcid):
            return {'person_or_org':{'name':'Silva, João','identifiers':[{'scheme':'orcid','identifier':orcid}]}}
        first,second=person('0000-0001-5109-3700'),person('0000-0002-1825-0097')
        self.assertEqual(merge_values([first],[second,first]),[first,second])

    def test_missing_fields_and_ordered_lists_are_preserved(self):
        left = {'authors':[{'person_or_org':{'name':'Doe, Jane'},'affiliations':[{'name':'University'}]}], 'title':'Paper'}
        right = {'authors':[{'person_or_org':{'name':'Doe, Jane','identifiers':[{'scheme':'orcid','identifier':'0000-0000-0000-0000'}]}},
                           {'person_or_org':{'name':'Silva, João'}}], 'publisher':'Press'}
        result = merge_values(left,right)
        self.assertEqual(len(result['authors']),2)
        self.assertEqual(result['authors'][0]['affiliations'],left['authors'][0]['affiliations'])
        self.assertEqual(result['publisher'],'Press')
        self.assertIn('identifiers',result['authors'][0]['person_or_org'])

    def test_reviewer_can_keep_shorter_curated_text(self):
        records = [row(),row('two',description='Texto automático muito mais longo')]
        automatic = plan_group(records,'one')
        self.assertEqual(automatic['payload']['metadata']['description'],'Texto automático muito mais longo')
        selected = plan_group(records,'one',{'/metadata/description':'Curto'})
        self.assertEqual(selected['payload']['metadata']['description'],'Curto')
        self.assertEqual(len(selected['conflicts'][0]['values']),2)
        with self.assertRaises(ValueError):
            plan_group(records,'one',{'/metadata/description':'inventado'})

    def test_three_sources_keep_all_alternatives(self):
        records = [row(),row('two',description='Descrição completa'),row('three',description='Outra descrição ainda mais completa')]
        group = plan_group(records,'one',{'/metadata/description':'Descrição completa'})
        self.assertEqual(len(group['conflicts'][0]['values']),3)
        self.assertEqual(group['payload']['metadata']['description'],'Descrição completa')

    def test_conflicting_doi_and_pending_edits_block(self):
        a,b = row(),row('two')
        b['tokens'] = ['doi:10.1234/other'];b['pending_edit']=True
        self.assertGreaterEqual(len(plan_group([a,b],'one')['blockers']),2)

    def test_access_owner_and_community_changes_block(self):
        for field in ('access','owner','community'):
            a,b = row(),row('two')
            if field=='access':b['data']['access']['record']='public'
            elif field=='owner':b['data']['parent']['access']['owned_by']['user']='5'
            else:b['data']['parent']['communities']['ids']=['another']
            self.assertTrue(plan_group([a,b],'one')['blockers'])

    def test_computed_file_status_does_not_change_access_policy(self):
        a,b = row(),row('two')
        b['data']['access']['status']='restricted'
        self.assertFalse(plan_group([a,b],'one')['blockers'])

    def test_managed_doi_must_not_be_retired(self):
        a,b = row(),row('two')
        b['data']['pids']={'doi':{'identifier':'10.1234/test','provider':'datacite'}}
        self.assertTrue(plan_group([a,b],'one')['blockers'])
        self.assertEqual(plan_group([a,b])['canonical'],'two')

    def test_files_with_same_name_and_different_bytes_both_survive(self):
        a = row(entries={'curve.raw':{'checksum':'md5:aaa','size':5}})
        b = row('two',entries={'curve.raw':{'checksum':'md5:bbb','size':9},'paper.pdf':{'checksum':'md5:ccc','size':8}})
        plan = file_plan([a,b],'one')
        self.assertEqual([(f['destination'],f['action']) for f in plan],
                         [('curve.raw','keep'),('curve__two.raw','rename'),('paper.pdf','copy')])
        self.assertEqual(sum(f['size'] for f in plan),22)

    def test_identical_bytes_are_not_duplicated_but_stay_in_backup_plan(self):
        entries = {'curve.raw':{'checksum':'md5:aaa','size':5}}
        plan = file_plan([row(entries=entries),row('two',entries=entries)],'one')
        self.assertEqual([f['action'] for f in plan],['keep','same_content'])
        self.assertEqual(len(plan),2)

    def test_fingerprint_tracks_access_content_and_file_version_not_stats(self):
        original = row()['data'];changed=deepcopy(original)
        changed['stats']={'views':1000};self.assertEqual(fingerprint(original),fingerprint(changed))
        changed['access']['record']='public';self.assertNotEqual(fingerprint(original),fingerprint(changed))


class BackupTests(unittest.TestCase):
    def test_backup_contains_binary_and_manifest_and_rejects_changed_bytes(self):
        content=b'RAW\x00\xff scientific bytes'
        checksum='md5:'+hashlib.md5(content).hexdigest()
        group = plan_group([row(entries={'curve.raw':{'checksum':checksum,'size':len(content)}}),row('two')],'one')
        @contextmanager
        def stream(mode):
            yield BytesIO(content)
        fake=SimpleNamespace(_record=SimpleNamespace(files={'curve.raw':SimpleNamespace(open_stream=stream)}))
        job=SimpleNamespace(id='a'*32,actor=4)
        app=Flask(__name__)
        with tempfile.TemporaryDirectory() as directory,app.app_context():
            app.config['ARGILOTECA_OPENALEX_BACKUPS']=directory
            with patch('argiloteca.openalex.duplicates.read_record',return_value=fake):
                result=write_backup(job,group,None)
                path=Path(directory)/result['filename']
                self.assertEqual(path.stat().st_mode&0o777,0o600)
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.read('files/0.bin'),content)
                    manifest=json.loads(archive.read('manifest.json'))
                    self.assertEqual(manifest['files'][0]['sha256'],hashlib.sha256(content).hexdigest())
                group['files'][0]['checksum']='md5:'+'0'*32
                job.id='b'*32
                with self.assertRaises(ValueError):write_backup(job,group,None)
                self.assertFalse((Path(directory)/('b'*32+'.zip')).exists())


if __name__=='__main__':
    unittest.main()
