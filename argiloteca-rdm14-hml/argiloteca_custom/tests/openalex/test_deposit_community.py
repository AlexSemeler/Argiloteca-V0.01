"""The native draft form must open for direct community links without a review."""
from copy import deepcopy
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import unittest

from jinja2 import DictLoader, Environment, select_autoescape


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.values = []; self.feed(html)

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == 'input' and data.get('id') == 'deposits-draft-community':
            self.values.append(json.loads(data['value']))


class DepositCommunityTests(unittest.TestCase):
    def render(self, record, preselected=None):
        source = (Path(os.environ['ARGILOTECA_DEPOSIT_TEMPLATE']) if os.environ.get('ARGILOTECA_DEPOSIT_TEMPLATE')
                  else Path(__file__).resolve().parents[3] / 'templates/semantic-ui/invenio_app_rdm/records/deposit.html')
        native = """{% block page_body %}{% if preselectedCommunity %}<input id="deposits-draft-community" value='{{ preselectedCommunity|tojson }}'>{% endif %}<div id="deposit-form"></div>{% endblock %}"""
        env = Environment(loader=DictLoader({'local.html': source.read_text(),
            'argiloteca_native/invenio_app_rdm/records/deposit.html': native,
            'semantic-ui/argiloteca/deposit_navigation.html': '{% macro deposit_navigation(record_id=none) %}{% endmacro %}'}),
            autoescape=select_autoescape())
        return Inputs(env.get_template('local.html').render(record=record, preselectedCommunity=preselected)).values

    def record(self):
        return {'id': 'same-record', 'is_published': False,
            'parent': {'communities': {'default': 'same-community', 'ids': ['same-community']}},
            'expanded': {'parent': {'communities': {'default': {'id': 'same-community',
                'metadata': {'title': 'Existing community'}}}}}}

    def test_direct_membership_uses_actual_default_without_mutation(self):
        record = self.record(); original = deepcopy(record)
        self.assertEqual(self.render(record), [record['expanded']['parent']['communities']['default']])
        self.assertEqual(record, original)

    def test_native_explicit_preselection_is_not_duplicated(self):
        selected = {'id': 'explicit'}
        self.assertEqual(self.render(self.record(), selected), [selected])

    def test_actual_review_workflow_is_left_to_native_form(self):
        record = self.record(); record['parent']['review'] = {'id': 'actual-review'}
        self.assertEqual(self.render(record), [])
        record = self.record(); record['review'] = {'receiver': {'community': 'same-community'}}
        self.assertEqual(self.render(record), [])

    def test_published_and_unclassified_records_are_not_preselected(self):
        record = self.record(); record['is_published'] = True
        self.assertEqual(self.render(record), [])
        self.assertEqual(self.render({'id': 'unclassified', 'parent': {}}), [])

    def test_mismatched_expansion_is_not_used(self):
        record = self.record(); record['expanded']['parent']['communities']['default']['id'] = 'other'
        self.assertEqual(self.render(record), [])

    def test_community_content_is_serialized_safely(self):
        record = self.record()
        record['expanded']['parent']['communities']['default']['metadata']['title'] = "</script><input id='injected'>"
        self.assertEqual(self.render(record), [record['expanded']['parent']['communities']['default']])


if __name__ == '__main__':
    unittest.main()
