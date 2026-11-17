"""Mendeley source identity, versions, mapping, audit and resumability."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('mendeley_test_client', Path(__file__).resolve().parents[2] / 'argiloteca/mendeley/client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
ROWS = [{'id': 'kaolinite', 'title': {'pt': 'Caulinita', 'en': 'Kaolinite'}},
        {'id': 'illite', 'title': {'pt': 'Ilita', 'en': 'Illite'}}]
ID = 'abcdefgh12'
BASE_DOI = '10.17632/' + ID
DOI = BASE_DOI + '.2'


def source(version='2'):
    doi = BASE_DOI + ('.' + version if version else '')
    return {'id': doi, 'type': 'dois', 'relationships': {'client': {'data': {'id': 'bl.mendeley'}}},
            'attributes': {'doi': doi, 'state': 'findable', 'types': {'resourceTypeGeneral': 'Dataset'},
            'url': 'https://data.mendeley.com/datasets/' + ID + ('/' + version if version else ''),
            'titles': [{'title': 'Kaolinite data'}], 'publicationYear': 2020,
            'dates': [{'date': '2020-04-02T00:00:00Z', 'dateType': 'Issued'}],
            'publisher': 'Mendeley Data', 'descriptions': [{'description': '<script>source</script>'}],
            'creators': [{'name': 'Smith, Alice', 'givenName': 'Alice', 'familyName': 'Smith', 'nameType': 'Personal',
                          'affiliation': ['Institute'], 'nameIdentifiers': [{'nameIdentifierScheme': 'ORCID', 'nameIdentifier': 'https://orcid.org/0000-0002-2177-6858'}]}],
            'rightsList': [{'rights': 'CC BY 4.0', 'rightsUri': 'https://creativecommons.org/licenses/by/4.0/'}],
            'subjects': [{'subject': 'Clay'}], 'relatedIdentifiers': [] if version else [
                {'relationType': 'HasVersion', 'relatedIdentifierType': 'DOI', 'relatedIdentifier': BASE_DOI + '.1'},
                {'relationType': 'HasVersion', 'relatedIdentifierType': 'DOI', 'relatedIdentifier': DOI}]}}


class SearchTests(unittest.TestCase):
    def test_modes_and_query(self):
        for values, mode in [({'term': 'kaolinite'}, 'vocabulary'), ({'free_text': 'XRD'}, 'free'),
                             ({'term': 'kaolinite', 'free_text': 'XRD OR DRX'}, 'combined')]:
            params = client.parameters(values, ROWS)
            self.assertEqual(params['search_mode'], mode)
        query = client.search_queries(params, ROWS)[0]['query']
        self.assertEqual(query, '(XRD OR DRX) AND ("Kaolinite" OR "Caulinita")')

    def test_all_sorted_offset_and_exact_selection(self):
        p = client.parameters({'term': '__all__', 'offset': 1}, ROWS)
        self.assertEqual(client.search_queries(p, ROWS)[0]['term']['id'], 'illite')
        more = ROWS + [{'id': 'illite-smectite', 'title': {'en': 'Illite-smectite'}}]
        self.assertEqual(len(client.search_queries(client.parameters({'term': 'illite'}, more), more)), 1)

    def test_invalid_parameters(self):
        for value in ({}, {'term': 'unknown'}, {'free_text': 'x'*501}, {'free_text': 'x\n'},
                      {'term': 'kaolinite', 'offset': 1}, {'free_text': 'XRD', 'per_term': 101}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.parameters(value, ROWS)

    def test_free_query_cannot_override_repository_filter(self):
        p = client.parameters({'free_text': '*:* OR prefix:10.1234'}, ROWS)
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', return_value={'data': []}) as f:
            client.collect(folder, p, ROWS)
            self.assertIn('client-id=bl.mendeley', f.call_args.args[0])
            self.assertIn('page%5Bsize%5D=1', f.call_args.args[0])


class MappingTests(unittest.TestCase):
    def test_fields_and_scientific_restraint(self):
        payload, issues = client.build_payload(source(), DOI)
        self.assertEqual(issues, [])
        md = payload['metadata']
        self.assertEqual(md['version'], '2')
        self.assertEqual(md['publication_date'], '2020-04-02')
        self.assertEqual(md['creators'][0]['person_or_org']['identifiers'][0]['scheme'], 'orcid')
        self.assertIn('&lt;script&gt;', md['description'])
        self.assertFalse(payload['files']['enabled'])
        self.assertNotIn('custom_fields', payload)
        self.assertNotIn('pids', payload)

    def test_primary_identity_cannot_come_from_cited_doi(self):
        for mutation in ('id', 'doi', 'client', 'url', 'type', 'state'):
            raw = source()
            if mutation == 'id': raw['id'] = BASE_DOI + '.1'
            if mutation == 'doi': raw['attributes']['doi'] = 'bad'
            if mutation == 'client': raw['relationships']['client']['data']['id'] = 'another.repository'
            if mutation == 'url': raw['attributes']['url'] = 'https://evil.example/datasets/' + ID
            if mutation == 'type': raw['attributes']['types']['resourceTypeGeneral'] = 'Text'
            if mutation == 'state': raw['attributes']['state'] = 'registered'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                client.build_payload(raw, DOI)

    def test_version_mismatch_rejected(self):
        raw = source(); raw['attributes']['url'] = 'https://data.mendeley.com/datasets/' + ID + '/1'
        with self.assertRaises(ValueError): client.build_payload(raw, DOI)
        with self.assertRaises(ValueError): client.build_payload(source(), BASE_DOI + '.1')

    def test_missing_required_values_and_license(self):
        raw = source()
        for key in ('titles', 'creators', 'dates', 'publicationYear', 'rightsList'): raw['attributes'].pop(key)
        payload, issues = client.build_payload(raw, DOI)
        self.assertEqual(sum(i['severity'] == 'error' for i in issues), 3)
        self.assertEqual(payload['metadata']['publication_date'], '')
        self.assertNotIn('rights', payload['metadata'])

    def test_year_precision_and_invalid_calendar_date(self):
        raw = source(); raw['attributes']['dates'] = [{'dateType': 'Issued', 'date': '2020-02-31'}]
        self.assertEqual(client.build_payload(raw, DOI)[0]['metadata']['publication_date'], '2020')
        raw['attributes'].pop('publicationYear')
        self.assertEqual(client.build_payload(raw, DOI)[0]['metadata']['publication_date'], '')

    def test_legacy_unversioned_doi_has_warning_and_no_guessed_version(self):
        payload, issues = client.build_payload(source(''), BASE_DOI)
        self.assertNotIn('version', payload['metadata'])
        self.assertIn('version_missing', [i['code'] for i in issues])

    def test_organizational_creator_and_geography(self):
        raw = source(); a = raw['attributes']
        a['creators'] = [{'name': 'Institute', 'nameType': 'Organizational'}]
        a['geoLocations'] = [{'geoLocationPoint': {'pointLongitude': 25.1, 'pointLatitude': 38.2}},
                             {'geoLocationPoint': {'pointLongitude': 999, 'pointLatitude': 38.2}}]
        payload, _ = client.build_payload(raw, DOI)
        self.assertEqual(payload['metadata']['creators'][0]['person_or_org']['type'], 'organizational')
        self.assertEqual(len(payload['metadata']['locations']['features']), 1)


class CollectionTests(unittest.TestCase):
    def params(self, **kwargs): return client.parameters({'term': 'kaolinite', **kwargs}, ROWS)

    def test_concept_and_versions_deduplicated_with_latest_declared(self):
        responses = [{'data': [source('1'), source('')]}, {'data': source('')}, {'data': source()}]
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=responses) as f:
            result = client.collect(folder, self.params(per_term=2), ROWS)
            records = json.loads((Path(folder)/'records.json').read_text())
            self.assertEqual(result['payloads'], 1)
            self.assertEqual(records[0]['doi'], DOI)
            self.assertEqual(len(records[0]['origins']), 2)
            self.assertEqual(f.call_count, 3)
            self.assertTrue(all(client.sha(Path(folder)/n) == h for n, h in result['input_hashes'].items()))

    def test_cross_query_dedup_keeps_provenance(self):
        responses = [{'data': [source()]}, {'data': source('')}, {'data': source()}, {'data': [source()]}]
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=responses):
            client.collect(folder, self.params(term='__all__', max_terms=2), ROWS)
            self.assertEqual(len(json.loads((Path(folder)/'records.json').read_text())[0]['origins']), 2)

    def test_legacy_missing_version_links_preserves_discovered_version_with_warning(self):
        concept = source(''); concept['attributes']['relatedIdentifiers'] = []
        responses = [{'data': [source()]}, {'data': concept}, {'data': source()}]
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=responses):
            client.collect(folder, self.params(), ROWS)
            row = json.loads((Path(folder)/'records.json').read_text())[0]
            self.assertEqual(row['doi'], DOI)
            self.assertIn('latest_unverified', [i['code'] for i in row['issues']])

    def test_unversioned_legacy_preserved(self):
        concept = source(''); concept['attributes']['relatedIdentifiers'] = []
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=[{'data': [concept]}, {'data': concept}]):
            client.collect(folder, self.params(), ROWS)
            row = json.loads((Path(folder)/'records.json').read_text())[0]
            self.assertEqual(row['doi'], BASE_DOI)
            self.assertNotIn('version', row['payload']['metadata'])

    def test_resumes_metadata_without_repeating_search_or_concept(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(client, 'fetch_json', side_effect=[{'data': [source()]}, {'data': source('')}, HTTPError('https://api.datacite.org', 429, 'limit', {}, None)]):
                with self.assertRaises(HTTPError): client.collect(folder, self.params(), ROWS)
            with patch.object(client, 'fetch_json', return_value={'data': source()}) as f:
                client.collect(folder, self.params(), ROWS)
                self.assertEqual(f.call_count, 1)

    def test_completed_lot_and_recipe_are_immutable(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', return_value={'data': []}):
            client.collect(folder, self.params(), ROWS)
            with self.assertRaises(ValueError): client.collect(folder, self.params(free_text='XRD'), ROWS)
            (Path(folder)/'records.json').write_text('[{}]')
            with self.assertRaises(ValueError): client.collect(folder, self.params(), ROWS)

    def test_invalid_api_response_does_not_become_empty_success(self):
        for response in ({'errors': []}, {'data': {}}, {'data': [], 'errors': ['bad']}):
            with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', return_value=response):
                with self.assertRaises(ValueError): client.collect(folder, self.params(), ROWS)
                self.assertFalse((Path(folder)/'resultado.json').exists())

    def test_foreign_version_relation_fails_closed(self):
        concept = source(''); concept['attributes']['relatedIdentifiers'][0]['relatedIdentifier'] = '10.17632/zzzzzzzz12.1'
        with tempfile.TemporaryDirectory() as folder, patch.object(client, 'fetch_json', side_effect=[{'data': [source()]}, {'data': concept}]):
            with self.assertRaises(ValueError): client.collect(folder, self.params(), ROWS)

    def test_off_host_requests_refused(self):
        with self.assertRaises(ValueError): client.fetch_json('https://evil.example/dois/one')


if __name__ == '__main__': unittest.main()
