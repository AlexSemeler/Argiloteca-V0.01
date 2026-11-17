"""Curatorial contracts: native relations, legacy compatibility, XML and guards.

Run with the application's Python; tests never commit scientific content.
"""
from copy import deepcopy
import unittest
from unittest.mock import patch, Mock
from invenio_app.factory import create_ui
from jsonschema import ValidationError as SchemaError
from marshmallow import ValidationError
from invenio_access.permissions import system_identity
from invenio_records_resources.services.errors import PermissionDeniedError
from argiloteca.scientific.connections import (FIELD, anonymous_identity, native_relation,
    reconcile_native_relations, validate_links, read_visible, connections_for)
from argiloteca.scientific.connections_integrity import ConnectionsIntegrityComponent
from argiloteca.scientific.models import scientific_errors, public_scientific
from argiloteca.scientific.xml import compiled_xsd, record_to_xml, DEFAULT_NAMESPACE


def link(**kwargs):
    return dict(record_id='abcde-12345', papel='termo', relacao='references', slug='antigorite',
                evidencia='Nome declarado no título da publicação.', **kwargs)


class ConnectionsContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_ui()
    def setUp(self):
        self.ctx=self.app.app_context();self.ctx.push()
        self.term={'id':'abcde-12345','access':{'record':'public'},'metadata':{'resource_type':{'id':'other'}},
                   'custom_fields':{'arg:termo_catalogo':{'slug':'antigorite','situacao':'ativo'}}}
    def tearDown(self):self.ctx.pop()

    def test_native_relations_preserve_existing_citations_and_metadata(self):
        metadata={'title':'Original', 'related_identifiers':[{'identifier':'10.1234/original','scheme':'doi','relation_type':{'id':'references'}}]}
        original=deepcopy(metadata)
        after, links=reconcile_native_relations(metadata,[],[link()])
        self.assertEqual(metadata,original)
        self.assertEqual(after['related_identifiers'][0],original['related_identifiers'][0])
        self.assertTrue(links[0]['native_relation_created'])
        removed,_=reconcile_native_relations(after,links,[])
        self.assertEqual(removed,original)

    def test_remove_keeps_preexisting_identical_native_citation(self):
        original={'related_identifiers':[native_relation(link())]}
        after, links=reconcile_native_relations(original,[],[link()])
        self.assertFalse(links[0]['native_relation_created'])
        removed,_=reconcile_native_relations(after,links,[])
        self.assertEqual(removed,original)

    def test_changing_relation_removes_only_owned_adapter(self):
        source=link();source.update(papel='dados');source.pop('slug')
        after,previous=reconcile_native_relations({'title':'Preserved'},[],[source])
        changed=dict(source,relacao='describes')
        after,links=reconcile_native_relations(after,previous,[changed])
        self.assertEqual(len(after['related_identifiers']),1)
        self.assertEqual(after['related_identifiers'][0]['relation_type']['id'],'describes')

    def test_legacy_does_not_require_migration_and_internal_flag_not_exported(self):
        entry=link();entry['native_relation_created']=True
        data={'id':'00000-11111','metadata':{'title':'Original','publication_date':'2026-10-21','resource_type':{'id':'publication-article'},'creators':[{'person_or_org':{'type':'personal','name':'Test, Reader'}}]},'custom_fields':{FIELD:[entry],'arg:outro':'untouched'}}
        self.assertEqual(scientific_errors(data['custom_fields']),[])
        self.assertNotIn('native_relation_created',public_scientific(data['custom_fields'])[FIELD][0])
        xml=record_to_xml(data);compiled_xsd().assertValid(xml)
        ns={'a':DEFAULT_NAMESPACE}
        self.assertEqual(xml.xpath('string(a:conexoes_cientificas/a:item/a:record_id)',namespaces=ns),'abcde-12345')
        self.assertFalse(xml.xpath('.//a:native_relation_created',namespaces=ns))

    def test_profiled_xml_exports_the_same_typed_connections(self):
        from argiloteca.scientific import PROFILE_FIELD, PROFILE_VERSION
        data={'id':'00000-11111','metadata':{'title':'Profiled','publication_date':'2026-10-21','resource_type':{'id':'dataset'},'creators':[]},'custom_fields':{PROFILE_FIELD:PROFILE_VERSION,FIELD:[link()]}}
        xml=record_to_xml(data);compiled_xsd().assertValid(xml)
        self.assertEqual(xml.xpath('count(a:conexoes_cientificas/a:item)',namespaces={'a':DEFAULT_NAMESPACE}),1)

    def test_hidden_target_title_and_evidence_are_omitted_from_public_graph(self):
        data={'id':'00000-11111','custom_fields':{FIELD:[link()]}}
        with patch('argiloteca.scientific.connections.read_visible',return_value=None):
            self.assertEqual(connections_for(anonymous_identity(),data,incoming=False),{'outgoing':[],'incoming':[]})

    def test_native_read_permission_failure_is_not_a_public_title(self):
        with patch('argiloteca.scientific.connections.service',new=Mock()) as native:
            native.read.side_effect=PermissionDeniedError('read')
            self.assertIsNone(read_visible(anonymous_identity(),'abcde-12345'))

    def test_invalid_legacy_connections_are_validated(self):
        broken=link();broken['evidencia']='x'
        self.assertTrue(scientific_errors({FIELD:[broken]}))
        self.assertTrue(scientific_errors({FIELD:'not a list'}))

    def test_self_and_duplicate_links_are_rejected(self):
        with patch('argiloteca.scientific.connections.read_visible',return_value=self.term):
            for source,links in [('abcde-12345',[link()]),('00000-11111',[link(),link()])]:
                with self.assertRaises(ValueError):validate_links(system_identity,source,links)

    def test_restricted_and_wrong_catalog_targets_are_rejected(self):
        with patch('argiloteca.scientific.connections.read_visible',return_value=None):
            with self.assertRaises(ValueError):validate_links(system_identity,'00000-11111',[link()])
        wrong=deepcopy(self.term);wrong['custom_fields']['arg:termo_catalogo']['slug']='wrong'
        with patch('argiloteca.scientific.connections.read_visible',return_value=wrong):
            with self.assertRaises(ValueError):validate_links(system_identity,'00000-11111',[link()])

    def test_term_requires_reference_relation_and_cannot_be_dataset(self):
        wrong=link();wrong['relacao']='describes'
        with self.assertRaises(SchemaError):validate_links(system_identity,'00000-11111',[wrong])
        wrong=link();wrong['papel']='dados'
        with patch('argiloteca.scientific.connections.read_visible',return_value=self.term):
            with self.assertRaises(ValueError):validate_links(system_identity,'00000-11111',[wrong])

    def test_role_matches_native_resource_type(self):
        dataset=deepcopy(self.term);dataset['custom_fields']={};dataset['metadata']['resource_type']['id']='dataset'
        entry=link();entry.pop('slug');entry['papel']='publicacao'
        with patch('argiloteca.scientific.connections.read_visible',return_value=dataset):
            with self.assertRaises(ValueError):validate_links(system_identity,'00000-11111',[entry])
            entry['papel']='dados';validate_links(system_identity,'00000-11111',[entry])

    def test_unrelated_native_edit_preserves_connections(self):
        original=link();original['native_relation_created']=True
        data={'metadata':{'title':'Edited'},'custom_fields':{'arg:other':'keep'}}
        record={'id':'00000-11111','custom_fields':{FIELD:[original]}}
        ConnectionsIntegrityComponent(None).check(anonymous_identity(),data,record)
        self.assertEqual(data['custom_fields'][FIELD],[original]);self.assertEqual(data['metadata']['title'],'Edited')
        self.assertEqual(data['custom_fields']['arg:other'],'keep')
        self.assertEqual(data['metadata']['related_identifiers'],[native_relation(original)])

    def test_nonadmin_cannot_add_or_remove_connection(self):
        component=ConnectionsIntegrityComponent(None)
        with self.assertRaises(PermissionDeniedError):component.check(anonymous_identity(),{'custom_fields':{FIELD:[link()]}},{'id':'00000-11111'})
        with self.assertRaises(PermissionDeniedError):component.check(anonymous_identity(),{'custom_fields':{FIELD:[]}},{'id':'00000-11111','custom_fields':{FIELD:[link()]}})

    def test_cleanup_does_not_require_old_target_still_public(self):
        old=link();other=dict(link(),record_id='zzzzz-99999')
        with patch('argiloteca.scientific.connections.read_visible',side_effect=AssertionError('unchanged target must not be revalidated')):
            validate_links(system_identity,'00000-11111',[old],[old,other])

if __name__=='__main__':unittest.main(verbosity=2)
