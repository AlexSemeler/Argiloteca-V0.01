"""Publication invariants and fail-closed backup checks; no native record writes."""
from copy import deepcopy
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile

from flask import Flask
from argiloteca.openalex import publication as pub


def data():
    return {'id': 'same-id', 'metadata': {'title': 'Curated title'},
            'custom_fields': {'argiloteca:analysis': {'value': 2}},
            'access': {'record': 'restricted', 'files': 'restricted', 'embargo': {'active': False}},
            'parent': {'access': {'owned_by': {'user': '4'}}, 'communities': {'ids': ['one'], 'default': 'one'}},
            'files': {'entries': {'curve.raw': {'checksum': 'md5:abc', 'size': 4, 'metadata': {}, 'version_id': 'draft-version'}}}}


class PreservationTests(unittest.TestCase):
    def test_native_file_version_and_links_may_change_but_bytes_must_not(self):
        before = data(); after = deepcopy(before)
        after['files']['entries']['curve.raw']['version_id'] = 'published-version'
        after['links'] = {'self': 'new-link'}
        pub.preserved(before, after)

    def test_metadata_science_access_owner_and_community_changes_are_blocked(self):
        for field in ('metadata', 'custom_fields', 'access', 'owner', 'community'):
            with self.subTest(field=field):
                before = data(); after = deepcopy(before)
                if field in ('metadata', 'custom_fields'): after[field] = {}
                elif field == 'access': after['access']['record'] = 'public'
                elif field == 'owner': after['parent']['access']['owned_by']['user'] = 'another'
                else: after['parent']['communities']['ids'] = []
                with self.assertRaises(ValueError): pub.preserved(before, after)

    def test_removing_or_changing_a_file_is_blocked(self):
        for change in ('remove', 'checksum', 'size', 'metadata'):
            before = data(); after = deepcopy(before)
            if change == 'remove': after['files']['entries'] = {}
            else: after['files']['entries']['curve.raw'][change] = 'changed'
            with self.assertRaises(ValueError): pub.preserved(before, after)

    def test_summary_distinguishes_new_update_already_published_and_blocked(self):
        records = [{'status': 'ready', 'communities': ['one']}, {'status': 'ready', 'communities': []},
                   {'status': 'already_published'}, {'status': 'blocked'}]
        result = pub.publication_summary(records, {'a': {'state': 'published', 'was_published': False},
            'b': {'state': 'published', 'was_published': True}})
        self.assertEqual([result[k] for k in ('ready', 'published', 'new', 'updated', 'already_published', 'blocked', 'unclassified')], [2, 2, 1, 1, 1, 1, 1])

    def test_tampered_plan_is_rejected_before_any_publication(self):
        job = SimpleNamespace(snapshot={'records': []}, params={'plan_sha256': 'tampered'})
        with self.assertRaises(ValueError): pub.run_chunk(job)


class CheckpointIndexTests(unittest.TestCase):
    def test_committed_publication_repairs_index_without_republishing(self):
        for deleted in (True, False):
            with self.subTest(deleted_draft=deleted):
                row = {'key': 'one', 'id': 'same-id', 'uuid': '12345678-1234-1234-1234-123456789012'}
                job = SimpleNamespace(snapshot={'records': [row]}, result={'cursor': 1, 'items': {'one': {'state': 'published'}}})
                original = deepcopy(job.result)
                service = MagicMock()
                service.draft_cls.get_record.return_value.model.is_deleted = deleted
                pub.repair_checkpoint_index(job, None, service)
                service.read.assert_called_once_with(None, 'same-id')
                service.indexer.index.assert_called_once_with(service.read.return_value._record)
                self.assertEqual(service.indexer.delete.call_count, int(deleted))
                service.publish.assert_not_called()
                self.assertEqual(job.result, original)

    def test_uncommitted_or_blocked_checkpoint_never_repairs_or_publishes(self):
        service = MagicMock()
        for cursor, state in ((0, None), (1, 'blocked')):
            job = SimpleNamespace(snapshot={'records': [{'key': 'one'}]},
                result={'cursor': cursor, 'items': {'one': {'state': state}}})
            pub.repair_checkpoint_index(job, None, service)
        service.read.assert_not_called()
        service.indexer.index.assert_not_called()
        service.publish.assert_not_called()


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.app = Flask(__name__)
        self.app.config['ARGILOTECA_OPENALEX_QUEUE'] = self.directory.name
        self.context = self.app.app_context(); self.context.push()
        self.job = SimpleNamespace(id='f'*32, params={'plan_sha256': 'signed-plan'}, result={})
        self.rows = [{'key': 'one', 'id': 'same-id', 'fingerprint': 'same-fingerprint', 'was_published': False}]
        content = b'RAW\x00\xff unchanged bytes'
        self.content = content
        @contextmanager
        def open_stream(mode):
            yield BytesIO(content)
        class Record(dict):
            pass
        self.native = Record({'metadata': {'title': 'Native title'}})
        self.native.parent = Record({'communities': {'ids': ['one']}})
        self.native.files = {'curve.raw': SimpleNamespace(open_stream=open_stream)}
        self.payload = data()
        self.payload['files']['entries']['curve.raw'].update(checksum='md5:'+hashlib.md5(content).hexdigest(), size=len(content))

    def tearDown(self):
        self.context.pop(); self.directory.cleanup()

    def test_backup_contains_original_metadata_and_binary_and_recovers_orphan(self):
        with patch.object(pub, 'read_state', return_value=(self.native, self.payload, 'same-fingerprint')):
            saved = pub.backup_chunk(self.job, 0, self.rows, None)
            path = pub.backup_path(self.job.id, 0)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(saved['fingerprints'], {'one': 'same-fingerprint'})
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.read('files/0.bin'), self.content)
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual(manifest['records'][0]['draft'], self.payload)
            self.assertEqual(pub.backup_chunk(self.job, 0, self.rows, None), saved)
            self.job.result = {'backups': {'0': saved}}
            self.assertEqual(pub.backup_chunk(self.job, 0, self.rows, None), saved)

    def test_tampered_checkpointed_backup_is_rejected(self):
        with patch.object(pub, 'read_state', return_value=(self.native, self.payload, 'same-fingerprint')):
            saved = pub.backup_chunk(self.job, 0, self.rows, None)
        self.job.result = {'backups': {'0': saved}}
        pub.backup_path(self.job.id, 0).write_bytes(b'changed')
        with self.assertRaises(ValueError): pub.backup_chunk(self.job, 0, self.rows, None)

    def test_changed_record_is_not_in_backup_and_cannot_be_published(self):
        with patch.object(pub, 'read_state', return_value=(self.native, self.payload, 'new-revision')):
            saved = pub.backup_chunk(self.job, 0, self.rows, None)
        self.assertEqual(saved['fingerprints'], {})

    def test_wrong_binary_checksum_aborts_before_backup_publication(self):
        self.payload['files']['entries']['curve.raw']['checksum'] = 'md5:'+'0'*32
        with patch.object(pub, 'read_state', return_value=(self.native, self.payload, 'same-fingerprint')):
            with self.assertRaises(ValueError): pub.backup_chunk(self.job, 0, self.rows, None)
        self.assertFalse(pub.backup_path(self.job.id, 0).exists())

    def test_backup_names_are_confined(self):
        for jid, number in (('../escape', 0), ('f'*32, -1), ('f'*32, 10001)):
            with self.assertRaises(ValueError): pub.backup_path(jid, number)


if __name__ == '__main__': unittest.main()
