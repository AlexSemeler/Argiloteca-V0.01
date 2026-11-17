"""Backups, confinement and reviewed lot removal, using disposable folders."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch
from flask import Blueprint,Flask

from argiloteca.openalex import maintenance_files as files
from argiloteca.openalex.maintenance import clear_coordinates,references


class EnqueueNavigationTests(unittest.TestCase):
    def test_shared_enqueue_resolves_dispatcher_from_either_blueprint(self):
        from types import SimpleNamespace
        from argiloteca.openalex.views import enqueue
        app=Flask(__name__)
        for name in ('argiloteca_openalex','argiloteca_maintenance'):
            blueprint=Blueprint(name,__name__,url_prefix='/'+name)
            blueprint.add_url_rule('/submit',view_func=lambda:enqueue(SimpleNamespace(id='synthetic-only')),methods=['POST'])
            blueprint.add_url_rule('/jobs/<job_id>',endpoint='job_detail' if name=='argiloteca_openalex' else 'detail',view_func=lambda job_id:job_id)
            app.register_blueprint(blueprint)
        with patch('argiloteca.openalex.views.db') as database,patch('argiloteca.openalex.tasks.run.delay') as dispatch:
            for name in ('argiloteca_openalex','argiloteca_maintenance'):
                response=app.test_client().post('/'+name+'/submit')
                self.assertEqual(response.status_code,303)
                self.assertEqual(response.headers['Location'],'/argiloteca_openalex/jobs/synthetic-only')
            self.assertEqual(database.session.commit.call_count,2)
            self.assertEqual(dispatch.call_count,2)


class LotMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'source';self.queue=Path(self.temp.name)/'queue'
        self.lot='v59_TEST_SYNTHETIC';self.source=self.root/'lotes'/self.lot
        self.source.mkdir(parents=True);(self.source/'data.json').write_bytes(b'SYNTHETIC ONLY')

    def prepare(self,action='archive_lot',archived=False):
        manifest=files.manifest(self.root,self.lot,archived)
        plan={'kind':'lot','action':action,'target':self.lot,'archived':archived,
              'lot_manifest':manifest,'lot_sha256':files.fingerprint(manifest)}
        jid=uuid.uuid4().hex;backup=files.backup(self.root,self.queue,jid,plan)
        return jid,{'plan':plan,'backup':backup}

    def test_archive_restore_delete_keep_verified_backups(self):
        for action,archived in [('archive_lot',False),('restore_lot',True),('delete_lot',False)]:
            jid,params=self.prepare(action,archived)
            self.assertEqual(files.apply_on_mac(self.root,self.queue,jid,params)['state'],'completed')
            path=self.queue/'maintenance-backups'/(jid+'.zip')
            with zipfile.ZipFile(path) as backup:self.assertEqual(backup.read('lot/data.json'),b'SYNTHETIC ONLY')
        self.assertFalse(self.source.exists())

    def test_stale_source_cannot_be_deleted(self):
        jid,params=self.prepare('delete_lot');(self.source/'data.json').write_text('changed')
        with self.assertRaises(ValueError):files.apply_on_mac(self.root,self.queue,jid,params)
        self.assertTrue(self.source.exists())

    def test_changed_or_missing_backup_cannot_delete(self):
        for corrupt in (False,True):
            jid,params=self.prepare('delete_lot');path=self.queue/'maintenance-backups'/(jid+'.zip')
            if corrupt:path.write_bytes(b'changed')
            else:path.unlink()
            with self.assertRaises((ValueError,FileNotFoundError)):files.apply_on_mac(self.root,self.queue,jid,params)
            self.assertTrue(self.source.exists())

    def test_symlinks_and_path_escape_refused(self):
        (self.source/'link').symlink_to(self.source/'data.json')
        with self.assertRaises(ValueError):files.manifest(self.root,self.lot)
        for target in ('../v59_escape','v59_../escape','/tmp/v59_escape'):
            with self.assertRaises(ValueError):files.source_path(self.root,target)

    def test_existing_destination_never_overwritten(self):
        jid,params=self.prepare();target=self.root/'.admin-trash'/self.lot;target.mkdir(parents=True)
        with self.assertRaises(ValueError):files.apply_on_mac(self.root,self.queue,jid,params)
        self.assertTrue(self.source.exists());self.assertTrue(target.exists())


class LinkMaintenanceTests(unittest.TestCase):
    def test_only_selected_coordinates_removed(self):
        fields={'arg:amostras':[{'codigo_amostra':'A','latitude':1,'longitude':2,'nome':'Preservar'},
                                 {'codigo_amostra':'B','latitude':3,'longitude':4}], 'other':{'keep':True}}
        before=deepcopy(fields);after=clear_coordinates(fields,'arg:amostras/0')
        self.assertEqual(fields,before)
        self.assertEqual(after['arg:amostras'][0],{'codigo_amostra':'A','nome':'Preservar'})
        self.assertEqual(after['arg:amostras'][1],before['arg:amostras'][1]);self.assertEqual(after['other'],before['other'])
        with self.assertRaises(ValueError):clear_coordinates(fields,'arg:amostras/99')

    def test_references_require_exact_identifier_or_url_segment(self):
        self.assertTrue(references({'nested':['https://local/records/abc']},{'abc'}))
        self.assertFalse(references({'title':'abc study','url':'https://local/records/abcdef'},{'abc'}))
