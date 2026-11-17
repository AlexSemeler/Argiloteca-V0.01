"""Local activation and shared native-validation failures; run in Invenio."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask
from flask_babel import lazy_gettext
from marshmallow import ValidationError
from argiloteca.mendeley import configure, workflow
from argiloteca.openalex import publication, service
from argiloteca.openalex.adapters import digest


class ActivationTests(unittest.TestCase):
    def test_remote_environment_is_disabled_by_default(self):
        app = Flask(__name__); app.config['SITE_UI_URL'] = 'https://repository.example.org'
        with patch.dict(os.environ, {}, clear=True): configure(app)
        self.assertFalse(app.config['ARGILOTECA_MENDELEY_ENABLED'])
        self.assertNotIn('argiloteca_mendeley', app.blueprints)

    def test_explicit_disable_is_preserved_on_loopback(self):
        app = Flask(__name__); app.config.update(SITE_UI_URL='https://127.0.0.1:5101', ARGILOTECA_MENDELEY_ENABLED=False)
        configure(app)
        self.assertNotIn('argiloteca_mendeley', app.blueprints)

    def test_version_and_identity_cannot_be_corrected_by_metadata_patch(self):
        self.assertFalse({'version', 'identifiers', 'pids', 'access', 'custom_fields'} & workflow.CORRECTABLE)

    def test_lot_paths_reject_traversal_and_foreign_prefix(self):
        for name in ['../elsewhere', 'pan_'+'a'*32, 'men_'+'x'*32]:
            with self.assertRaises(ValueError): workflow.lot_path('/tmp', name)

    def test_snapshot_verifies_source_and_proposed_payload(self):
        with tempfile.TemporaryDirectory() as base:
            folder = Path(base)/'lotes'/('men_'+'a'*32);folder.mkdir(parents=True)
            source = folder/'records.json';source.write_text('[]')
            payload={'metadata': {'title': 'Preserved'}}
            row={'payload':payload,'payload_sha256':digest(payload)}
            snapshot={'source':str(folder),'input_hashes':{'records.json':workflow.file_hash(source)},'records':[row]}
            workflow.verify_snapshot(base,snapshot)
            row['payload']['metadata']['title']='Changed'
            with self.assertRaises(ValueError): workflow.verify_snapshot(base,snapshot)
            snapshot['records']=[]; source.write_text('[{}]')
            with self.assertRaises(ValueError): workflow.verify_snapshot(base,snapshot)


class NativeMessagesTests(unittest.TestCase):
    def test_localized_validation_message_is_serializable_for_publication(self):
        error=ValidationError({'metadata':{'title':[lazy_gettext('Required')]}})
        self.assertIn('Required',json.loads(publication.error_message(error))['metadata']['title'])

    def test_invalid_native_metadata_blocks_one_row_without_failing_review(self):
        error=ValidationError({'metadata':{'creators':[lazy_gettext('Required')]}})
        row={'payload':{'metadata':{}},'status':'apto','issues':[]}
        context={'metadata':SimpleNamespace(required_vocabularies=[]),'identity':None,'index':{},
                 'vocabulary_cache':set(),'classification':None}
        snapshot={'records':[row],'summary':{}}
        with patch.object(service,'matches',return_value=[]), patch.object(service,'validate_native',side_effect=error), patch('argiloteca.openalex.classification.classify_snapshot',side_effect=lambda root,snap,*a,**kw:snap):
            result=service.review_snapshot('/tmp',snapshot,4,context=context)
        self.assertEqual(row['status'],'bloqueado')
        self.assertEqual(row['instance_validation'],'invalid')
        self.assertEqual(result['summary']['bloqueado'],1)
        self.assertIn('Required',row['issues'][0]['message'])


if __name__=='__main__': unittest.main()
