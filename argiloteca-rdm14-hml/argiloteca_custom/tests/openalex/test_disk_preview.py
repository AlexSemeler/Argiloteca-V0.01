"""Regression checks for bounded OpenAlex preparation and exact legacy semantics."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from argiloteca.openalex import adapters, preview

ROOT = os.environ.get('ARGILOTECA_OPENALEX_ROOT', '')


class StreamingJSONTests(unittest.TestCase):
    def parse(self, value):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'raw.json'; path.write_text(value, encoding='utf-8-sig')
            return list(preview.raw_items(path))

    def test_chunk_boundaries_unicode_and_all_envelopes(self):
        item = {'id':'https://openalex.org/W123', 'text':'argila ç θ '*10000, 'number':123456789}
        for value, envelope in (([item], ''), ({'meta':{'count':1},'results':[item]}, 'results'), ({'records':[item]}, 'records'), ({'data':[item]}, 'data')):
            rows = [row for env, row in self.parse(json.dumps(value, ensure_ascii=False)) if row is not None]
            self.assertEqual(rows, [item])

    def test_empty_higher_priority_envelope_is_retained(self):
        self.assertEqual(self.parse('{"data":[{"id":"W1"}],"results":[]}'), [('data',None),('data',{'id':'W1'}),('results',None)])

    def test_invalid_truncated_nonfinite_and_trailing_input_are_rejected(self):
        for value in ('[{"id":1}', '[{},]', '{"data":[],}', '[NaN]', '[{}] {}', '[{"x":Infinity}]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse(value)


class LegacyParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata, cls.reader, cls.version = adapters.converter(ROOT)

    def disk(self, root, name, corrections=None, limit=0):
        with tempfile.TemporaryDirectory() as temp:
            db=preview.connect(Path(temp)/'stage.sqlite')
            try:
                snapshot, rows, statuses=preview.source_records(root,name,db,corrections,limit)
                snapshot['records']=list(rows)
                snapshot['summary'].update(statuses)
                return snapshot
            finally:db.close()

    def test_real_single_lot_payload_provenance_hashes_and_corrections_match(self):
        name='v59_20261017_125312_yn31iu5f'
        expected=adapters.prepare(ROOT,name)
        self.assertEqual(self.disk(ROOT,name),expected)
        key=expected['records'][0]['provenance'][0]['origin']['key']
        corrections={key:{'title':'Título corrigido para revisão'}}
        self.assertEqual(self.disk(ROOT,name,corrections),adapters.prepare(ROOT,name,corrections))

    def fixture(self, root):
        lot=root/'lotes/v59_parity';lot.mkdir(parents=True)
        (lot/'resultado.json').write_text('{"status":"coleta_concluida"}')
        lines=[];raw=[]
        for i,(doi,work) in enumerate((('10.1234/a','W100000001'),('10.1234/a','W100000002'),('10.1234/b','W100000002'),('10.1234/c','W100000003'))):
            payload={'metadata':{'title':'Clay '+str(i),'publication_date':'2024-01-01','resource_type':{'id':'publication-article'},'creators':[{'person_or_org':{'type':'personal','family_name':'Tester'}}]},'pids':{'doi':{'identifier':doi,'provider':'external'}}}
            (lot/f'p{i}.json').write_text(json.dumps(payload))
            lines.append('\t'.join([str(i),f'p{i}.json','kaolinite','caulinita','',work,doi,'']))
            raw.append({'id':'https://openalex.org/'+work,'doi':doi,'language':'en','type':'article'})
        (lot/'manifest.tsv').write_text('\n'.join(lines))
        (lot/'openalex_raw.json').write_text(json.dumps(raw))
        return lot

    def test_transitive_duplicates_across_rows_and_conflicts_match_verified_merger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lot=self.fixture(root)
            for limit in (0,1):
                expected=self.reader.prepare_lot(lot,limit=limit)
                expected.update(converter=self.version,corrections={})
                for row in expected['records']:row['payload_sha256']=adapters.digest(row['payload'])
                with patch.object(preview,'converter',return_value=(self.metadata,self.reader,self.version)):
                    actual=self.disk(root,lot.name,limit=limit)
                self.assertEqual(actual,expected)
                self.assertEqual(actual['summary']['unique_records'],2)
                self.assertEqual(len(actual['records'][0]['provenance']),3)
                self.assertEqual(actual['records'][0]['status'],'bloqueado')

    def test_empty_results_precedes_data_and_invalid_raw_discards_partial_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lot=self.fixture(root)
            for raw in ('{"data":[{"id":"W100000001","language":"fr"}],"results":[]}', '[{"id":"W100000001"},BROKEN]'):
                (lot/'openalex_raw.json').write_text(raw)
                expected=self.reader.prepare_lot(lot)
                with patch.object(preview,'converter',return_value=(self.metadata,self.reader,self.version)):
                    actual=self.disk(root,lot.name)
                # Error wording is intentionally the stream decoder's wording.
                self.assertEqual(actual['records'],[{**r,'payload_sha256':adapters.digest(r['payload'])} for r in expected['records']])
                self.assertEqual(bool(actual['source_warnings']),bool(expected['source_warnings']))

    def test_invalid_manifest_doi_keeps_legacy_work_match_and_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lot=self.fixture(root)
            lines=(lot/'manifest.tsv').read_text().splitlines();first=lines[0].split('\t');first[6]='invalid-doi';lines[0]='\t'.join(first)
            (lot/'manifest.tsv').write_text('\n'.join(lines))
            expected=self.reader.prepare_lot(lot)
            with patch.object(preview,'converter',return_value=(self.metadata,self.reader,self.version)):
                actual=self.disk(root,lot.name)
            self.assertEqual(actual['records'],[{**r,'payload_sha256':adapters.digest(r['payload'])} for r in expected['records']])


class DiskPageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Flask(__name__);self.app.config['ARGILOTECA_OPENALEX_QUEUE']=self.temp.name
        self.context=self.app.app_context();self.context.push();self.addCleanup(self.context.pop)
        folder=Path(self.temp.name)/'previews';folder.mkdir();self.path=folder/('a'*32+'.sqlite')
        db=preview.connect(self.path);db.execute('CREATE TABLE records(seq INTEGER PRIMARY KEY,key TEXT,status TEXT,body TEXT,sha256 TEXT,search TEXT)')
        self.rows=[]
        for i in range(45):
            row={'key':str(i),'status':'apto' if i%2 else 'bloqueado','identity':{},'payload':{'metadata':{'title':'CAULINITA '+str(i)}},'provenance':[{'raw_candidates':[{'original':i}]}]}
            self.rows.append(row)
            db.execute('INSERT INTO records VALUES(?,?,?,?,?,?)',(i,row['key'],row['status'],json.dumps(row),adapters.digest(row),json.dumps({'metadata':row['payload']['metadata'],'identity':{}}).casefold()))
        db.commit();db.close()
        self.snapshot={'summary':{},'record_store':{'schema':1,'id':'a'*32,'sha256':preview.file_hash(self.path),'bytes':self.path.stat().st_size,'count':45}}

    def test_pages_filters_and_selection_preserve_exact_full_rows(self):
        rows,total,page,pages=preview.page_records(self.snapshot,page=3)
        self.assertEqual((total,page,pages),(45,3,3));self.assertEqual(rows,self.rows[40:])
        rows,total,_,_=preview.page_records(self.snapshot,q='Caulinita',status='apto')
        self.assertEqual(total,22);self.assertEqual(len(rows),20)
        self.assertEqual(list(preview.iter_records(self.snapshot,['3','44'])),[self.rows[3],self.rows[44]])
        self.assertEqual(list(preview.iter_records(self.snapshot,[])),[])

    def test_file_tampering_blocks_reads(self):
        with self.path.open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):list(preview.iter_records(self.snapshot))

    def test_row_tampering_is_rejected_even_if_file_descriptor_is_replaced(self):
        db=preview.connect(self.path);db.execute("UPDATE records SET body='{}' WHERE seq=0");db.commit();db.close()
        self.snapshot['record_store'].update(sha256=preview.file_hash(self.path),bytes=self.path.stat().st_size)
        with self.assertRaises(ValueError):list(preview.iter_records(self.snapshot,['0']))

    def test_administrative_backup_includes_complete_private_preview(self):
        from types import SimpleNamespace
        import zipfile
        from argiloteca.openalex.duplicates import write_backup
        self.app.config['ARGILOTECA_OPENALEX_BACKUPS']=str(Path(self.temp.name)/'backups')
        job=SimpleNamespace(id='b'*32,actor=4)
        info=write_backup(job,{'files':[],'plan':{'job':{'snapshot':self.snapshot}}},None)
        with zipfile.ZipFile(Path(self.app.config['ARGILOTECA_OPENALEX_BACKUPS'])/info['filename']) as archive:
            self.assertEqual(archive.read('preview.sqlite'),self.path.read_bytes())
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['preview_store']['sha256'],self.snapshot['record_store']['sha256'])

    def test_complete_artifact_recovers_after_file_publish_before_journal_commit(self):
        from types import SimpleNamespace
        root=Path(self.temp.name)/'source';(root/'lotes/v59_recovery').mkdir(parents=True)
        params={'lot':'v59_recovery','limit':0}
        snapshot={'source':str(root/'lotes/v59_recovery'),'input_hashes':{},'summary':{'selected_records':45}}
        db=preview.connect(self.path);db.execute('CREATE TABLE preview_metadata(body TEXT)')
        db.execute('INSERT INTO preview_metadata VALUES(?)',(json.dumps({'snapshot':snapshot,'params_sha256':adapters.digest(params),'actor':4}),));db.commit();db.close()
        job=SimpleNamespace(id='a'*32,actor=4,params=params,snapshot={})
        result=preview.build(job,str(root))
        self.assertEqual(result['record_store']['count'],45)
        self.assertEqual(list(preview.iter_records(result)),self.rows)
        job.params={'lot':'v59_other'}
        with self.assertRaises(ValueError):preview.build(job,str(root))


if __name__=='__main__':unittest.main(verbosity=2)
