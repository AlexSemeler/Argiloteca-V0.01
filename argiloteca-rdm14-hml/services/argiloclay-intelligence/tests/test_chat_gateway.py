import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'argiloteca_custom'))
from argiloteca.argiloclay.context import validate_context, section_for
from argiloteca.argiloclay.service import query, Unavailable, verify_records, revalidate_response
from argiloclay_intelligence.workflow import query as workflow


class Client:
    def __init__(self, sources): self.sources = sources
    def call(self, path, payload):
        return {"schema_version":"1.0","available":True,"answer":"UNTRUSTED GENERATED PROSE", "sources":copy.deepcopy(self.sources),"limitations":[]}


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.source={"document_id":"record:public:c0","title":"Public record","excerpt":"Literal evidence.","record_id":"public","updated":"2026-10-21T12:00:00Z","url":"https://evil.example"}

    def test_revalidates_visibility_and_rebuilds_citations(self):
        r=query({"question":"record","context":{"path":"/search"}},Client([self.source]),lambda rid:{"updated":self.source['updated']})
        self.assertEqual(r['sources'][0]['url'],'/records/public')
        self.assertNotIn('UNTRUSTED',r['answer']);self.assertIn('[Fonte 1]',r['answer'])

    def test_revocation_deletion_and_stale_snapshot_are_excluded(self):
        for current in (None,{'updated':'NEW'}):
            r=query({'question':'record'},Client([self.source]),lambda rid:current)
            self.assertEqual(r['sources'],[]);self.assertIn('Não conclusivo',r['answer'])

    def test_private_context_never_reaches_pilot(self):
        with self.assertRaises(ValueError):
            query({'question':'record','context':{'path':'/records/private','record_ids':['private']}},Client([]),lambda rid:None)

    def test_forged_context_and_raw_arrays_rejected(self):
        for context in ({'path':'https://evil.example'}, {'path':'//evil.example'}, {'path':'/?token=secret'},
                        {'record_ids':['../drafts']},{'selection':[{'id':'x','curve':[1,2]}]},{'selection':[{'temporary':'true'}]}):
            with self.assertRaises(ValueError): validate_context(context)

    def test_sections_derived_from_path_not_claimed_role(self):
        paths={'/':'home','/search':'search','/mapa-argilominerais':'map','/catalogo-autorizado-de-nomes-para-argilominerais':'catalog',
            '/argilominerais/':'vocabulary','/argilominerais/kaolinite':'mineral','/records/abc':'record','/analises/':'analyses',
            '/analises/abc':'package','/drx/comparacao':'drx','/uploads/new':'deposit','/communities/':'communities',
            '/administration/':'administration','/geoquimica/rede':'geochemistry','/sobre':'help','/other':'repository'}
        for path,expected in paths.items():
            self.assertEqual(validate_context({'path':path,'section':'administration'})['section'],expected)

    def test_english_refusal_and_literal_source(self):
        r=query({'question':'bitcoin','context':{'language':'en'}},Client([]),lambda rid:None)
        self.assertIn('Inconclusive',r['answer'])

    def test_invalid_source_response_is_not_forwarded(self):
        with self.assertRaises(Unavailable): query({'question':'record'},Client([{'excerpt':123}]))

    def test_non_record_source_links_not_trusted(self):
        r=query({'question':'mineral'},Client([{'excerpt':'ok','url':'javascript:alert(1)'}]))
        self.assertNotIn('url',r['sources'][0])

    def test_history_revalidation_never_returns_stale_or_revoked_records(self):
        refs={'records':[{'record_id':'public','updated':'v1'},{'record_id':'private','updated':'v1'}]}
        result=verify_records(refs,lambda rid:{'updated':'v1'} if rid=='public' else None)
        self.assertEqual(result['verified'],[refs['records'][0]])
        self.assertEqual(verify_records(refs,lambda rid:{'updated':'v2'})['verified'],[])

    def test_legacy_rag_endpoint_also_filters_revoked_snapshot_sources(self):
        from flask import Flask, Blueprint
        from types import SimpleNamespace
        from unittest.mock import patch
        from argiloteca.drx.api.rag_routes import register_rag_routes
        app=Flask(__name__); blueprint=Blueprint('legacy_test',__name__)
        source={**self.source,'tipo_fonte':'registro_invenio'}
        client=SimpleNamespace(query=lambda *a,**k:Client([source]).call('',{}))
        register_rag_routes(blueprint,SimpleNamespace(rag_client_factory=lambda:client));app.register_blueprint(blueprint)
        with patch('argiloteca.argiloclay.service.revalidate_response',side_effect=lambda value:revalidate_response(value,lambda rid:None)):
            response=app.test_client().post('/argiloteca/drx/rag/query',json={'question':'registro'})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json['sources'],[])


class WorkflowTests(unittest.TestCase):
    def call(self,name,args):
        self.calls.append((name,args));return {'sources':[]}

    def test_deterministic_tools_all_sections(self):
        for section in ('home','catalog','map','analyses','drx','package','deposit','communities','administration','geochemistry'):
            self.calls=[];r=workflow({'question':'O que posso fazer aqui?','context':{'section':section}},self)
            self.assertEqual(r['transport'],'mcp_stdio');self.assertEqual(self.calls,[('get_section_guide',{'section':section,'language':'pt'})])

    def test_record_and_mineral_context(self):
        self.calls=[];workflow({'question':'Explique este registro','context':{'record_ids':['public']}},self)
        self.assertEqual(self.calls[0][0],'get_public_record')
        self.calls=[];workflow({'question':'Explique este mineral','context':{'term_id':'kaolinite'}},self)
        self.assertEqual(self.calls[0],('lookup_vocabulary',{'term':'Explique kaolinite'}))

    def test_unrelated_question_not_replaced_by_help(self):
        self.calls=[];workflow({'question':'Como comparar salários?','context':{'section':'drx'}},self)
        self.assertEqual(self.calls[0][0],'search_evidence')


if __name__=='__main__':unittest.main()
