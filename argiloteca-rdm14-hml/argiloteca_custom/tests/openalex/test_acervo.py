"""Accepted metrics are visible only on the matching authorized record page."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import sqlite3
import unittest

from flask import Flask
from argiloteca.openalex import enrichment as e
from argiloteca.openalex.acervo import record_complements


class AcceptedComplements(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.app=Flask(__name__)
        self.app.config['ARGILOTECA_OPENALEX_QUEUE']=self.tmp.name
        self.ctx=self.app.app_context();self.ctx.push()
        self.version='a'*32;self.rid='one-two'
        self.native={'id':self.rid,'metadata':{'title':'Preserved','identifiers':[{'scheme':'url','identifier':'https://openalex.org/W1'},{'scheme':'doi','identifier':'10.1234/a'}]}}
        with sqlite3.connect(e.path_for(self.version)) as c:
            c.execute('CREATE TABLE accepted(uid,rid,oa_id,doi,payload)')
            c.execute('INSERT INTO accepted VALUES(?,?,?,?,?)',('uuid',self.rid,'https://openalex.org/W1','10.1234/a',json.dumps({'fwci':0,'cited_by_count':None})))
        c.close()
        self.patches=[patch.object(e,'head',return_value=self.version),patch.object(e,'checked_version',return_value=SimpleNamespace(result={'applied_at':'now'})),patch.object(e,'native',side_effect=lambda _: (self.native,'P'))]
        for p in self.patches:p.start()
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.ctx.pop();self.tmp.cleanup()
    def test_matching_record_is_read_only_and_preserves_missing_values(self):
        before=deepcopy(self.native)
        with self.app.test_request_context('/records/'+self.rid):
            result=record_complements(self.rid)
        self.assertEqual(result['payload']['fwci'],0)
        self.assertIsNone(result['payload']['cited_by_count'])
        self.assertEqual(self.native,before)
    def test_no_draft_preview_or_cross_record_disclosure(self):
        for path in ['/uploads/'+self.rid,'/records/another-id','/records/'+self.rid+'/preview','/api/records/'+self.rid]:
            with self.app.test_request_context(path):self.assertIsNone(record_complements(self.rid))
    def test_changed_identifier_or_native_id_hides_stale_metrics(self):
        for key,value in [('metadata',{'identifiers':[]}),('id','changed-id')]:
            before=deepcopy(self.native);self.native[key]=value
            with self.app.test_request_context('/records/'+self.rid):self.assertIsNone(record_complements(self.rid))
            self.native=before
    def test_single_native_identifier_is_sufficient_but_conflicts_are_hidden(self):
        for identifiers in [[{'scheme':'doi','identifier':'https://doi.org/10.1234/A'}],[{'scheme':'url','identifier':'https://openalex.org/W1'}]]:
            self.native['metadata']['identifiers']=identifiers
            with self.app.test_request_context('/records/'+self.rid):self.assertIsNotNone(record_complements(self.rid))
        for identifiers in [[{'scheme':'url','identifier':'https://openalex.org/W2'},{'scheme':'doi','identifier':'10.1234/a'}],[{'scheme':'url','identifier':'https://openalex.org/W1'},{'scheme':'doi','identifier':'10.1234/conflict'}]]:
            self.native['metadata']['identifiers']=identifiers
            with self.app.test_request_context('/records/'+self.rid):self.assertIsNone(record_complements(self.rid))
    def test_no_version_or_missing_store_keeps_record_available(self):
        with self.app.test_request_context('/records/'+self.rid):
            with patch.object(e,'head',return_value=None):self.assertIsNone(record_complements(self.rid))
            Path(e.path_for(self.version)).unlink()
            self.assertIsNone(record_complements(self.rid))


if __name__=='__main__':unittest.main()
