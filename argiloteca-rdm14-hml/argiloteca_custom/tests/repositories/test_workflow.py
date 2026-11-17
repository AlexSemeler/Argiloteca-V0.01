"""Handle import identity, native review and local-only activation regressions."""
from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from flask import Flask
from argiloteca.repositories import configure,workflow
from argiloteca.openalex import service

META=SimpleNamespace(normalize_doi=lambda v:'',normalize_openalex_id=lambda v:'')


def payload(scheme='handle',value='10183/1970'):
    return {'metadata':{'title':'Source title','identifiers':[{'scheme':scheme,'identifier':value}]}}


class IdentityTests(unittest.TestCase):
    def test_explicit_handle_and_approved_urls_share_identity(self):
        for scheme,value in [('handle','10183/1970'),('url','https://lume.ufrgs.br/handle/10183/1970'),('url','http://www.lume.ufrgs.br/handle/10183/1970'),('url','https://lume.ufrgs.br/xmlui/handle/10183/1970')]:
            self.assertEqual(service.tokens(payload(scheme,value),META),{'handle:10183/1970'})
        self.assertEqual(service.tokens(payload('handle','123456789/230873'),META),{'handle:123456789/230873'})

    def test_arbitrary_url_citation_bad_port_and_wrong_host_cannot_claim_handle(self):
        for scheme,value in [('url','https://evil.example/handle/10183/1970'),('url','https://lume.ufrgs.br:bad/handle/10183/1970'),('url','https://lume.ufrgs.br/handle/123456789/1970'),('other','10183/1970'),('url','https://lume.ufrgs.br/handle/10183/1970?foo=bar')]:
            self.assertEqual(service.tokens(payload(scheme,value),META),set())
        p=payload('other','none');p['metadata']['description']='https://lume.ufrgs.br/handle/10183/1970'
        self.assertEqual(service.tokens(p,META),set())

    def test_handle_import_matches_existing_institutional_url_without_doi(self):
        index={'handle:10183/1970':{('same','published'):{'id':'same','kind':'published'}}}
        self.assertEqual(service.matches({'payload':payload()},index,META),[{'id':'same','kind':'published'}])

    def test_update_same_handle_preserves_native_custom_fields_files(self):
        current=payload('url','https://lume.ufrgs.br/handle/10183/1970');current.update(custom_fields={'science':{'value':1}},files={'enabled':True,'default_preview':'curve.raw'},access={'record':'restricted'})
        incoming=payload();result=service.update_payload(current,incoming,META)
        self.assertEqual(result['custom_fields'],current['custom_fields']);self.assertEqual(result['files'],current['files']);self.assertNotIn('access',result)
        self.assertEqual(len(result['metadata']['identifiers']),2)

    def test_different_handle_cannot_overwrite_from_old_claim(self):
        with self.assertRaises(ValueError):service.update_payload(payload(),payload('handle','10183/9999'),META)


class ActivationTests(unittest.TestCase):
    def test_remote_default_disabled_and_explicit_local_disable(self):
        for url,settings in [('https://repository.example.org',{}),('https://127.0.0.1:5101',{'ARGILOTECA_REPOSITORIES_ENABLED':False})]:
            app=Flask(__name__);app.config.update(SITE_UI_URL=url,**settings)
            with patch.dict(os.environ,{},clear=True):configure(app)
            self.assertNotIn('argiloteca_repositories',app.blueprints)

    def test_identity_fields_not_correctable(self):
        self.assertFalse({'identifiers','pids','access','custom_fields'} & workflow.CORRECTABLE)

    def test_paths_reject_escape_foreign_lot(self):
        for value in ['../secret','men_'+'a'*32,'oai_'+'x'*32]:
            with self.assertRaises(ValueError):workflow.lot_path('/tmp',value)


if __name__=='__main__':unittest.main()
