"""Provider bounds and a shared cache/rate gate, without scientific writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import requests
from argiloteca.admin_ui.geocoding import candidates, lookup, LookupError


def payload(lon=-51.23, lat=-30.03):
    return {'features':[{'geometry':{'type':'Point','coordinates':[lon,lat]},
        'properties':{'name':'Porto Alegre','city':'Porto Alegre','state':'RS','country':'Brasil'}}]}


def response(data=None, status=200, raw=None):
    result=Mock();result.status_code=status
    result.iter_content.return_value=[raw if raw is not None else json.dumps(data).encode()]
    result.__enter__=Mock(return_value=result);result.__exit__=Mock(return_value=False)
    return result


class GeocodingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fetch=Mock(return_value=response(payload()))
        self.now=1000
    def search(self,q='Porto Alegre',**kwargs):
        return lookup(q,'https://photon.komoot.io/api/',self.temp.name,fetch=self.fetch,now=lambda:self.now,**kwargs)
    def test_geojson_axis_order_labels_and_zero(self):
        result=candidates(payload(0,0))[0]
        self.assertEqual((result['latitude'],result['longitude']),(0,0))
        self.assertEqual(result['label'],'Porto Alegre, RS, Brasil')
    def test_discard_nonfinite_out_of_bounds_and_nonpoint(self):
        for lon,lat in [(181,0),(0,-91),(float('nan'),0),(0,True)]:
            self.assertEqual(candidates(payload(lon,lat)),[])
        data=payload();data['features'][0]['geometry']['type']='LineString'
        self.assertEqual(candidates(data),[])
    def test_at_most_five_results(self):
        data=payload();data['features']*=10
        self.assertEqual(len(candidates(data)),5)
    def test_cache_case_whitespace_and_no_network_for_repeat(self):
        self.assertFalse(self.search()['cached'])
        self.assertTrue(self.search('  porto   alegre  ')['cached'])
        self.fetch.assert_called_once()
        self.assertEqual(Path(self.temp.name,'places.sqlite3').stat().st_mode & 0o777,0o600)
    def test_rate_gate_is_shared_between_calls_and_cache_still_works(self):
        self.search()
        with self.assertRaises(LookupError) as caught:self.search('Curitiba')
        self.assertEqual(caught.exception.status,429)
        self.assertTrue(self.search()['cached'])
        self.now+=2
        self.search('Curitiba');self.assertEqual(self.fetch.call_count,2)
    def test_expired_cache_is_refetched(self):
        self.search();self.now+=604801;self.assertFalse(self.search()['cached'])
        self.assertEqual(self.fetch.call_count,2)
    def test_invalid_query_never_contacts_provider(self):
        for query in ('x',' '*10,'x'*181):
            with self.assertRaises(LookupError) as caught:self.search(query)
            self.assertEqual(caught.exception.status,422)
        self.fetch.assert_not_called()
    def test_provider_failures_and_invalid_json(self):
        for item in [response(status=500),response(raw=b'bad JSON'),response(raw=b'x'*1048577),response({'unknown':True})]:
            self.now+=2;self.fetch.return_value=item
            with self.assertRaises(LookupError):self.search()
        self.fetch.side_effect=requests.Timeout()
        self.now+=2
        with self.assertRaises(LookupError):self.search()
    def test_remote_rate_limit_is_explicit(self):
        self.fetch.return_value=response(status=429)
        with self.assertRaises(LookupError) as caught:self.search()
        self.assertEqual(caught.exception.status,429)
    def test_endpoint_is_configured_https_without_credentials(self):
        for endpoint in ['http://photon.komoot.io/api/','https://user:pass@example.com/','https://example.com/?secret=x']:
            with self.assertRaises(LookupError):lookup('Porto Alegre',endpoint,self.temp.name,fetch=self.fetch)
        self.fetch.assert_not_called()
    def test_network_is_manual_bounded_and_does_not_follow_redirects(self):
        self.search();kwargs=self.fetch.call_args.kwargs
        self.assertEqual(kwargs['params'],{'q':'Porto Alegre','limit':5})
        self.assertEqual(kwargs['timeout'],(4,10));self.assertFalse(kwargs['allow_redirects'])
    def test_empty_results_are_cached(self):
        self.fetch.return_value=response({'features':[]})
        self.assertEqual(self.search()['results'],[])
        self.assertTrue(self.search()['cached'])
