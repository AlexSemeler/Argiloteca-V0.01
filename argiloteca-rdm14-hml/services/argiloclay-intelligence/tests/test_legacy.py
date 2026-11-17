import io
import json
import os
import unittest
from unittest.mock import patch
from argiloclay_intelligence.legacy import search
from argiloclay_intelligence.workflow import query

class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'ARGILOCLAY_LEGACY_URL':'http://127.0.0.1:7860'});self.env.start();self.addCleanup(self.env.stop)
    def opener(self,payload):
        return lambda req,timeout:io.BytesIO(json.dumps(payload).encode())
    def test_exact_raw_excerpt_and_provenance(self):
        r=search('AM1',opener=self.opener({'schema_version':'1.0','sources':[{'tipo_fonte':'drx_raw','filename':'AM1.raw','sha256':'a'}],'answer':'Intro\n\n[Fonte 1] AM1.raw\nTrecho do índice: Exact RAW text.'}))
        self.assertEqual(r['sources'][0]['excerpt'],'Exact RAW text.')
        self.assertEqual(r['sources'][0]['corpus_origin'],'preserved_drx_service')
    def test_marker_mismatch_fails_closed(self):
        with self.assertRaises(ValueError):search('AM1',opener=self.opener({'schema_version':'1.0','sources':[{'tipo_fonte':'drx_raw','filename':'AM1.raw'}],'answer':'UNTRUSTED'}))
    def test_non_loopback_configuration_rejected(self):
        with patch.dict(os.environ,{'ARGILOCLAY_LEGACY_URL':'https://evil.example'}):
            with self.assertRaises(ValueError):search('AM1')
    def test_technical_excerpt_is_preserved(self):
        r=search('method',opener=self.opener({'schema_version':'1.0','sources':[{'document_id':'technical:1','excerpt':'Exact method.'}]}))
        self.assertEqual(r['sources'][0]['excerpt'],'Exact method.')
    def test_tangential_drx_match_is_refused(self):
        r=search('DRX capital França',opener=self.opener({'schema_version':'1.0','sources':[{'document_id':'technical:1','excerpt':'DRX picos e intensidade.'}]}))
        self.assertEqual(r['sources'],[])
    def test_routes_drx_only_when_enabled(self):
        class Bridge:
            def call(self,name,args):self.name=name;return {'sources':[]}
        b=Bridge();query({'question':'Quais picos DRX da AM1?'},b);self.assertEqual(b.name,'search_drx')
        query({'question':'O que é caulinita?'},b);self.assertEqual(b.name,'lookup_vocabulary')
        query({'question':'Como usar esta página?','context':{'section':'drx'}},b);self.assertEqual(b.name,'get_section_guide')
