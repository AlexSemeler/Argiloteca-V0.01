"""Legacy works are recognized only through an approved native identity."""
from copy import deepcopy
import sqlite3
import unittest
from argiloteca.openalex.analytics import approved_work_ids


class ApprovedIdentityTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.execute('CREATE TABLE accepted(uid TEXT PRIMARY KEY,rid TEXT UNIQUE,oa_id TEXT,doi TEXT)')
        self.c.execute('INSERT INTO accepted VALUES(?,?,?,?)',('uuid','one-two','https://openalex.org/W123','10.1234/a'))
        self.native={'id':'one-two','metadata':{'title':'Preserved title','identifiers':[{'scheme':'doi','identifier':'https://doi.org/10.1234/A'}]}}

    def tearDown(self):
        self.c.close()

    def test_exact_approved_uuid_rid_doi_recovers_id_without_mutating_bibliography(self):
        before=deepcopy(self.native)
        self.assertEqual(approved_work_ids(self.c,'uuid',self.native),{'W123'})
        self.assertEqual(self.native,before)

    def test_no_accepted_version_does_not_infer_identity(self):
        self.assertEqual(approved_work_ids(None,'uuid',self.native),set())

    def test_each_native_identity_constraint_is_required(self):
        self.assertEqual(approved_work_ids(self.c,'other-uuid',self.native),set())
        for key,value in [('id','changed'),('doi','10.1234/other')]:
            record=deepcopy(self.native)
            if key=='id':record[key]=value
            else:record['metadata']['identifiers'][0]['identifier']=value
            self.assertEqual(approved_work_ids(self.c,'uuid',record),set())

    def test_undeclared_or_missing_doi_is_not_a_match(self):
        record=deepcopy(self.native);record['metadata']['identifiers']=[]
        record['metadata']['description']='10.1234/a https://openalex.org/W123'
        self.assertEqual(approved_work_ids(self.c,'uuid',record),set())

    def test_declared_native_ids_are_never_replaced_by_overlay(self):
        self.native['metadata']['identifiers'] += [{'scheme':'url','identifier':'https://openalex.org/W999'}]
        self.assertEqual(approved_work_ids(self.c,'uuid',self.native),{'W999'})
        self.native['metadata']['identifiers'] += [{'scheme':'url','identifier':'https://openalex.org/W1000'}]
        self.assertEqual(approved_work_ids(self.c,'uuid',self.native),{'W999','W1000'})

    def test_non_openalex_overlay_id_is_rejected(self):
        self.c.execute("UPDATE accepted SET oa_id='https://example.test/W123'")
        self.assertEqual(approved_work_ids(self.c,'uuid',self.native),set())
