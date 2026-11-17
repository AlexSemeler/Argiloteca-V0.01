import unittest
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask,Blueprint
from argiloteca.drx.api.rag_routes import register_rag_routes
from argiloteca.argiloclay.service import Unavailable

class PanelCatalogRouting(unittest.TestCase):
 def client(self,legacy):
  app=Flask(__name__);bp=Blueprint('test_panel',__name__);register_rag_routes(bp,SimpleNamespace(rag_client_factory=lambda:legacy));app.register_blueprint(bp);return app.test_client()
 def test_unfiltered_definition_uses_shared_gateway_and_honors_top_k(self):
  class Legacy:
   def query(self,*a,**kw):raise AssertionError('Definition must use catalog gateway')
  result={'sources':[{'excerpt':'A'},{'excerpt':'B'}],'answer':'ficha','available':True}
  with patch('argiloteca.argiloclay.service.query',return_value=result) as query,patch('argiloteca.argiloclay.service.revalidate_response',side_effect=lambda row,**kw:row):
   r=self.client(Legacy()).post('/argiloteca/drx/rag/query',json={'question':'O que é caulinita?','top_k':1})
  self.assertEqual(r.status_code,200);self.assertEqual(len(r.json['sources']),1);self.assertEqual(r.json['context_filters'],{});self.assertEqual(query.call_args.args[0]['context']['path'],'/drx/comparacao')
 def test_filtered_drx_query_stays_in_existing_drx_service(self):
  class Legacy:
   def query(self,*a,**kw):self.kw=kw;return {'answer':'DRX','sources':[],'available':True}
  legacy=Legacy();r=self.client(legacy).post('/argiloteca/drx/rag/query',json={'question':'Explique este difratograma','filters':{'sample_code':'ARC-TEST'}})
  self.assertEqual(r.status_code,200);self.assertEqual(legacy.kw['filters'],{'sample_code':'ARC-TEST'})
 def test_unavailable_mcp_returns_graceful_error_without_unrelated_legacy_answer(self):
  with patch('argiloteca.argiloclay.service.query',side_effect=Unavailable('offline')):
   r=self.client(None).post('/argiloteca/drx/rag/query',json={'question':'O que são argilominerais?'})
  self.assertEqual(r.status_code,503);self.assertFalse(r.json['available'])
