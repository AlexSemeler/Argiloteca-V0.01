"""Run in the installed Invenio runtime: python -m unittest discover .../openalex."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from argiloteca.openalex import adapters

ROOT = os.environ.get('ARGILOTECA_OPENALEX_ROOT', '')


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata, cls.reader, cls.version = adapters.converter(ROOT)

    def test_existing_converter_is_verified(self):
        folder, fingerprint = adapters.release(ROOT, 'metadata')
        self.assertEqual(self.version['sha256'], fingerprint)
        self.assertEqual(Path(self.metadata.__file__).parent, folder)

    def test_real_single_lot_preserves_science_only_in_provenance(self):
        data = adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f')
        row = data['records'][0]
        self.assertNotIn('custom_fields', row['payload'])
        self.assertNotIn('languages', row['payload']['metadata'])
        self.assertIn('custom_fields', row['provenance'][0]['original_payload'])
        self.assertEqual(row['payload']['files'], {'enabled': False})
        self.assertEqual(row['payload_sha256'], adapters.digest(row['payload']))
        adapters.verify_snapshot(ROOT, data)

    def test_payload_tampering_is_blocked(self):
        data = adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f')
        data['records'][0]['payload']['metadata']['title'] = 'alterado'
        with self.assertRaises(ValueError):
            adapters.verify_snapshot(ROOT, data)

    def test_path_escape_and_symlink_are_blocked(self):
        with self.assertRaises(ValueError):
            adapters.lot_path(ROOT, '../credenciais')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder/'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):
                adapters.read_json(folder/'link', folder)

    def test_changed_installation_and_manifest_escape_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder/'code.py').write_text('x=1')
            with self.assertRaises(ValueError):
                adapters.verify_files(folder, {'code.py': '0'*64})
            with self.assertRaises(ValueError):
                adapters.verify_files(folder, {'../elsewhere': '0'*64})

    def test_incomplete_lot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary).resolve()
            (folder/'resultado.json').write_text('{"status":"running"}')
            with self.assertRaises(ValueError):
                self.reader.prepare_lot(folder)

    def test_corrections_cannot_change_identity_or_access(self):
        for field in ('pids', 'access', 'identifiers', 'custom_fields'):
            with self.assertRaises(ValueError):
                adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f', {'fake': {field: {}}})

    def test_corrections_create_a_new_snapshot(self):
        original = adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f')
        key = original['records'][0]['provenance'][0]['origin']['key']
        fixed = adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f', {key: {'title': 'Título verificado para teste'}})
        self.assertNotEqual(original['records'][0]['payload_sha256'], fixed['records'][0]['payload_sha256'])
        self.assertEqual(original['records'][0]['identity'], fixed['records'][0]['identity'])

    def test_doi_punctuation_and_no_doi_work_identity(self):
        from argiloteca.openalex.service import tokens
        payload = {'pids': {'doi': {'identifier': 'https://doi.org/10.1234/Test.'}},
            'metadata': {'identifiers': [{'scheme': 'url', 'identifier': 'https://openalex.org/W123456789'}]}}
        self.assertEqual(tokens(payload, self.metadata), {'doi:10.1234/test.', 'openalex:W123456789'})
        del payload['pids']
        self.assertEqual(tokens(payload, self.metadata), {'openalex:W123456789'})

    def test_extraction_has_bounded_structured_arguments(self):
        available = [{'id': 'kaolinite'}]
        params = adapters.extraction_parameters({'term': 'kaolinite'}, available)
        self.assertEqual(params['per_term'], 1)
        for data in ({'term': '; touch /tmp/x'}, {'term': 'kaolinite', 'per_term': 101}, {'term': 'kaolinite', 'max_terms': 0}):
            with self.assertRaises(ValueError):
                adapters.extraction_parameters(data, available)


class OverwriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = adapters.converter(ROOT)[0]

    def current(self):
        return {'metadata': {'title': 'Título anterior', 'publisher': 'Curadoria local',
                    'identifiers': [{'scheme': 'url', 'identifier': 'https://openalex.org/W123456789'}]},
                'custom_fields': {'arg:publicacao_argilominerais_relacionados': 'curado'},
                'access': {'record': 'restricted', 'files': 'restricted'},
                'files': {'enabled': True, 'default_preview': 'difratograma.raw', 'entries': {'difratograma.raw': {}}},
                'media_files': {'enabled': False}}

    def incoming(self):
        return {'metadata': {'title': 'Título atualizado',
                    'identifiers': [{'scheme': 'url', 'identifier': 'https://openalex.org/W123456789'}]},
                'files': {'enabled': False}, 'access': {'record': 'public', 'files': 'public'}}

    def test_overwrite_supplied_metadata_and_preserve_curated_native_state(self):
        from argiloteca.openalex.service import update_payload
        before = self.current()
        result = update_payload(before, self.incoming(), self.metadata)
        self.assertEqual(result['metadata']['title'], 'Título atualizado')
        self.assertEqual(result['metadata']['publisher'], 'Curadoria local')
        self.assertEqual(result['custom_fields'], before['custom_fields'])
        self.assertEqual(result['files'], {'enabled': True, 'default_preview': 'difratograma.raw'})
        self.assertNotIn('access', result)
        self.assertEqual(before['metadata']['title'], 'Título anterior')

    def test_identity_aliases_survive_overwrite(self):
        from argiloteca.openalex.service import update_payload
        before = self.current()
        before['metadata']['identifiers'].append({'scheme': 'url', 'identifier': 'https://openalex.org/W234567890'})
        result = update_payload(before, self.incoming(), self.metadata)
        self.assertEqual(len(result['metadata']['identifiers']), 2)

    def test_external_doi_fallback_preserves_bibliographic_identity(self):
        from argiloteca.openalex.service import external_doi_payload, tokens
        incoming = self.incoming()
        incoming['pids'] = {'doi': {'identifier': '10.1234/test', 'provider': 'external'}}
        before = copy.deepcopy(incoming)
        result = external_doi_payload(incoming, False)
        self.assertNotIn('pids', result)
        self.assertIn({'scheme': 'doi', 'identifier': '10.1234/test'}, result['metadata']['identifiers'])
        self.assertEqual(tokens(result, self.metadata), tokens(before, self.metadata))
        self.assertEqual(incoming, before)
        self.assertEqual(external_doi_payload(result, False), result)

    def test_enabled_or_locally_managed_doi_is_never_moved(self):
        from argiloteca.openalex.service import external_doi_payload
        for enabled, provider in ((True, 'external'), (False, 'datacite')):
            incoming = self.incoming()
            incoming['pids'] = {'doi': {'identifier': '10.1234/test', 'provider': provider}}
            self.assertEqual(external_doi_payload(incoming, enabled), incoming)

    def test_doi_fallback_preserves_other_pids_and_identifiers(self):
        from argiloteca.openalex.service import external_doi_payload
        incoming = self.incoming()
        incoming['pids'] = {'oai': {'identifier': 'oai:test:1', 'provider': 'oai'},
                            'doi': {'identifier': '10.1234/test', 'provider': 'external'}}
        result = external_doi_payload(incoming, False)
        self.assertEqual(result['pids'], {'oai': incoming['pids']['oai']})
        self.assertEqual(result['metadata']['identifiers'][0], incoming['metadata']['identifiers'][0])

    def test_primary_doi_provider_is_not_replaced(self):
        from argiloteca.openalex.service import update_payload
        before, incoming = self.current(), self.incoming()
        before['pids'] = {'doi': {'identifier': '10.1234/test', 'provider': 'datacite'}}
        incoming['pids'] = {'doi': {'identifier': '10.1234/test', 'provider': 'external'}}
        result = update_payload(before, incoming, self.metadata)
        self.assertNotIn('pids', result)

    def test_missing_doi_can_be_completed(self):
        from argiloteca.openalex.service import update_payload
        incoming = self.incoming()
        incoming['pids'] = {'doi': {'identifier': '10.1234/test', 'provider': 'external'}}
        self.assertEqual(update_payload(self.current(), incoming, self.metadata)['pids'], incoming['pids'])

    def test_divergent_dois_block_overwrite(self):
        from argiloteca.openalex.service import update_payload
        before, incoming = self.current(), self.incoming()
        before['pids'] = {'doi': {'identifier': '10.1234/one'}}
        incoming['pids'] = {'doi': {'identifier': '10.1234/two'}}
        with self.assertRaises(ValueError):
            update_payload(before, incoming, self.metadata)

    def test_historical_claim_does_not_overwrite_a_different_identity(self):
        from argiloteca.openalex.service import update_payload
        incoming = self.incoming()
        incoming['metadata']['identifiers'][0]['identifier'] = 'https://openalex.org/W99999999'
        with self.assertRaises(ValueError):
            update_payload(self.current(), incoming, self.metadata)

    def test_published_draft_and_claim_are_one_target(self):
        from argiloteca.openalex.service import unique_matches
        found = unique_matches([{'id':'same', 'kind':'draft'}, {'id':'same', 'kind':'published'},
                                {'id':'same', 'kind':'draft', 'previous_job':'old'}])
        self.assertEqual(found, [{'id':'same', 'kind':'published'}])

    def test_legacy_identifier_scheme_still_matches_exact_doi(self):
        from argiloteca.openalex.service import tokens
        self.assertEqual(tokens({'metadata':{'identifiers':[{'scheme':'DOI', 'identifier':'https://doi.org/10.1234/TEST'}]}}, self.metadata), {'doi:10.1234/test'})

    def test_deleted_target_never_falls_back_to_create(self):
        from unittest.mock import Mock
        from invenio_pidstore.errors import PIDDoesNotExistError
        from argiloteca.openalex.service import update_existing
        service = Mock()
        service.edit.side_effect = PIDDoesNotExistError('recid', 'deleted')
        with self.assertRaises(ValueError):
            update_existing(service, None, {'id':'deleted'}, {'payload':self.incoming()}, self.metadata, None)
        service.create.assert_not_called()


class AccessTests(unittest.TestCase):
    def test_nonadmin_and_anonymous_are_denied(self):
        from argiloteca.openalex.views import admin_only
        app = Flask(__name__)
        @app.route('/')
        @admin_only
        def protected():
            return 'secret'
        with patch('argiloteca.scientific.restricted_review.can_review', return_value=False):
            self.assertEqual(app.test_client().get('/').status_code, 403)

    def test_csrf_missing_is_denied_even_if_global_protection_is_absent(self):
        from argiloteca.openalex.views import blueprint
        app = Flask(__name__); app.secret_key = 'unit-test-only'
        from flask_babel import Babel
        Babel(app)
        app.register_blueprint(blueprint)
        with patch('argiloteca.scientific.restricted_review.can_review', return_value=True):
            self.assertEqual(app.test_client().post('/administration/openalex/prepare').status_code, 400)


class NativeReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from invenio_app.factory import create_ui
        cls.app = create_ui()

    def snapshot(self):
        return adapters.prepare(ROOT, 'v59_20261017_125312_yn31iu5f')

    def test_invalid_vocabulary_blocks_and_updates_summary(self):
        from argiloteca.openalex.service import review_snapshot
        with self.app.app_context():
            data = self.snapshot()
            data['records'][0]['payload']['metadata']['resource_type'] = {'id': 'nonexistent-openalex-unit-test'}
            reviewed = review_snapshot(ROOT, data, 4)
            self.assertEqual(reviewed['records'][0]['status'], 'bloqueado')
            self.assertEqual(reviewed['records'][0]['instance_validation'], 'invalid')
            self.assertEqual(reviewed['summary']['bloqueado'], 1)
            self.assertEqual(reviewed['source_summary']['bloqueado'], 0)

    def test_multiple_identity_matches_are_blocked(self):
        from argiloteca.openalex.service import review_snapshot, tokens
        metadata = adapters.converter(ROOT)[0]
        data = self.snapshot()
        index = {key: {('one', 'draft'): {'id': 'one', 'kind': 'draft'},
                       ('two', 'published'): {'id': 'two', 'kind': 'published'}}
                 for key in tokens(data['records'][0]['payload'], metadata)}
        with self.app.app_context(), patch('argiloteca.openalex.service.inventory', return_value=index):
            reviewed = review_snapshot(ROOT, data, 4)
            self.assertEqual(reviewed['records'][0]['status'], 'bloqueado')
            self.assertTrue(any(i['code'] == 'duplicate_conflict' for i in reviewed['records'][0]['issues']))

    def test_inventory_failure_does_not_allow_review(self):
        from argiloteca.openalex.service import review_snapshot
        with self.app.app_context(), patch('argiloteca.openalex.service.inventory', side_effect=RuntimeError('database offline')):
            with self.assertRaises(RuntimeError):
                review_snapshot(ROOT, self.snapshot(), 4)

    def test_missing_actor_is_rejected(self):
        from argiloteca.openalex.service import actor_identity
        with self.app.app_context():
            with self.assertRaises(ValueError):
                actor_identity(99999999)


if __name__ == '__main__':
    unittest.main()
