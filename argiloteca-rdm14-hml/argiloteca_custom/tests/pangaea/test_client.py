"""Search semantics, identity, scientific restraint and durable collection."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

BASE = Path(__file__).resolve().parents[2] / 'argiloteca/pangaea'
spec = importlib.util.spec_from_file_location('pangaea_client_test', BASE / 'client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
VOCABULARY = [
    {'id': 'kaolinite', 'title': {'en': 'Kaolinite', 'pt': 'Caulinita'}},
    {'id': 'illite', 'title': {'en': 'Illite', 'pt': 'Ilita'}}]
DOI = '10.1594/PANGAEA.810743'


def source():
    return {'@type': 'Dataset', 'identifier': 'https://doi.org/' + DOI,
            'name': 'Kaolinite dataset <source>', 'datePublished': '2013-04-27',
            'creator': [{'@type': 'Person', 'name': 'Gerhard Schmiedl', 'familyName': 'Schmiedl',
                         'givenName': 'Gerhard', '@id': 'https://orcid.org/0000-0002-2177-6858'}],
            'description': 'Observed <data>; no inferred samples.', 'inLanguage': 'en',
            'license': 'https://creativecommons.org/licenses/by/3.0/',
            'spatialCoverage': {'geo': {'latitude': 38.2, 'longitude': 25.1}}}


class SearchTests(unittest.TestCase):
    def params(self, **kwargs):
        return client.parameters(kwargs, VOCABULARY)

    def test_three_modes(self):
        for data, mode in [({'free_text': 'XRD'}, 'free'), ({'term': 'kaolinite'}, 'vocabulary'),
                           ({'term': 'kaolinite', 'free_text': 'XRD'}, 'combined')]:
            self.assertEqual(self.params(**data)['search_mode'], mode)

    def test_combination_groups_free_expression_and_bilingual_mineral(self):
        query = client.search_queries(self.params(term='kaolinite', free_text='DRX OR XRD'), VOCABULARY)[0]['query']
        self.assertEqual(query, '(DRX OR XRD) AND ("Kaolinite" OR "Caulinita") -type:series -type:bundled')

    def test_specific_mineral_is_exact_even_with_substring_ids(self):
        rows = VOCABULARY + [{'id': 'illite-smectite', 'title': {'en': 'Illite-smectite'}}]
        self.assertEqual(len(client.search_queries(self.params(term='illite'), rows)), 1)

    def test_all_uses_portuguese_order_offset_and_limit(self):
        queries = client.search_queries(self.params(term='__all__', offset=1, max_terms=1), VOCABULARY)
        self.assertEqual(queries[0]['term']['id'], 'illite')

    def test_free_expression_preserved(self):
        query = '(XRD OR "X-ray diffraction") AND sediment'
        self.assertEqual(client.search_queries(self.params(free_text=query), VOCABULARY), [{'query': query, 'term': None}])

    def test_invalid_inputs(self):
        for data in [{}, {'term': 'unknown'}, {'free_text': 'x' * 501}, {'free_text': 'XRD\n'},
                     {'free_text': 'XRD', 'per_term': 101}, {'term': '__all__', 'max_terms': 82},
                     {'term': 'kaolinite', 'offset': 1}, {'free_text': 'XRD', 'offset': 81}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.params(**data)

    def test_primary_identity_cannot_be_taken_from_html_citation(self):
        self.assertIsNone(client.result_to_candidate({'URI': 'bad', 'html': 'doi:' + DOI}))
        self.assertEqual(client.result_to_candidate({'URI': 'doi:' + DOI, 'html': '10.1594/PANGAEA.111'})['doi'], DOI)


class MappingTests(unittest.TestCase):
    def test_source_fields_and_html_escaping(self):
        payload, issues = client.build_payload(source(), DOI)
        self.assertFalse(issues)
        self.assertEqual(payload['metadata']['locations']['features'][0]['geometry']['coordinates'], [25.1, 38.2])
        self.assertEqual(payload['metadata']['creators'][0]['person_or_org']['identifiers'][0]['scheme'], 'orcid')
        self.assertIn('&lt;data&gt;', payload['metadata']['description'])
        self.assertFalse(payload['files']['enabled'])
        self.assertNotIn('custom_fields', payload)
        self.assertNotIn('pids', payload)

    def test_missing_values_are_blocked_without_inventing_date_or_author(self):
        raw = source()
        for field in ('name', 'creator', 'datePublished', 'license'):
            raw.pop(field)
        payload, issues = client.build_payload(raw, DOI)
        self.assertEqual(sum(i['severity'] == 'error' for i in issues), 3)
        self.assertEqual(payload['metadata']['creators'], [])
        self.assertEqual(payload['metadata']['publication_date'], '')
        self.assertNotIn('rights', payload['metadata'])

    def test_metadata_identity_mismatch_fails(self):
        with self.assertRaises(ValueError):
            client.build_payload(source(), '10.1594/PANGAEA.222')

    def test_graph_and_organizational_author(self):
        raw = source(); raw['creator'] = {'@type': 'Organization', 'name': 'Institute'}
        payload, _ = client.build_payload({'@graph': [{'@type': 'WebPage'}, raw]}, DOI)
        self.assertEqual(payload['metadata']['creators'][0]['person_or_org']['type'], 'organizational')

    def test_invalid_coordinates_are_not_imported(self):
        raw = source(); raw['spatialCoverage']['geo']['latitude'] = 999
        self.assertNotIn('locations', client.build_payload(raw, DOI)[0]['metadata'])


class CollectionTests(unittest.TestCase):
    def test_deduplicates_across_queries_and_preserves_both_origins(self):
        response = {'results': [{'URI': 'doi:' + DOI}]}
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=[response, source(), response]) as fetch:
            result = client.collect(folder, client.parameters({'term': '__all__', 'max_terms': 2}, VOCABULARY), VOCABULARY)
            records = json.loads((Path(folder) / 'records.json').read_text())
            self.assertEqual(result['payloads'], 1)
            self.assertEqual(len(records[0]['origins']), 2)
            self.assertEqual(fetch.call_count, 3)
            self.assertTrue(all(client.sha(Path(folder) / name) == sha for name, sha in result['input_hashes'].items()))

    def test_failed_metadata_can_resume_without_repeating_search(self):
        response = {'results': [{'URI': 'doi:' + DOI}]}
        params = client.parameters({'term': 'kaolinite'}, VOCABULARY)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(client, 'fetch_json', side_effect=[response, HTTPError('https://doi.pangaea.de', 429, 'quota', {}, None)]):
                with self.assertRaises(HTTPError):
                    client.collect(folder, params, VOCABULARY)
            self.assertFalse((Path(folder) / 'resultado.json').exists())
            with patch.object(client, 'fetch_json', return_value=source()) as fetch:
                self.assertEqual(client.collect(folder, params, VOCABULARY)['payloads'], 1)
                self.assertEqual(fetch.call_count, 1)

    def test_changed_recipe_refused(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', return_value={'results': []}):
            client.collect(folder, client.parameters({'free_text': 'XRD'}, VOCABULARY), VOCABULARY)
            with self.assertRaises(ValueError):
                client.collect(folder, client.parameters({'free_text': 'DRX'}, VOCABULARY), VOCABULARY)

    def test_malformed_response_does_not_become_empty_success(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', return_value={'error': 'failure'}):
            with self.assertRaises(ValueError):
                client.collect(folder, client.parameters({'free_text': 'XRD'}, VOCABULARY), VOCABULARY)
            self.assertFalse((Path(folder) / 'resultado.json').exists())


if __name__ == '__main__':
    unittest.main()
