"""Contract checks for catalog terms, coordinates and interoperable XML."""
from copy import deepcopy
import unittest
from contextlib import contextmanager

@contextmanager
def raises(error):
    try:
        yield
    except error:
        pass
    else:
        raise AssertionError("Expected " + error.__name__)
from lxml import etree
from argiloteca.scientific.catalog import FIELD, from_profile, payload
from argiloteca.scientific.catalog_views import patch_coordinates
from argiloteca.scientific.models import validate_model, scientific_errors, projection
from argiloteca.scientific.xml import record_to_xml, DEFAULT_NAMESPACE, compiled_xsd


def term():
    return from_profile(dict(slug='mineral-teste', nome_pt='Mineral de teste', nome_en='Test mineral',
        nome_cientifico_padronizado='Test mineral', aliases=['001', 'Sílica'], external_uri='https://example.org/mineral',
        descricao_curta='Referência científica com Unicode', classic_description='Perfil de teste',
        source_profiles={'curadoria': {'zero': 0, 'confirmed': False, 'missing': None}}))


def test_required_names_and_permanent_slug_contract():
    data = term()
    assert not validate_model('arg_termo_catalogo.schema.json', data)
    assert not scientific_errors(payload(data)['custom_fields'])
    for key in ('nome_pt', 'nome_en', 'nome_cientifico_padronizado'):
        broken = deepcopy(data); broken[key] = ''
        assert validate_model('arg_termo_catalogo.schema.json', broken)
    data['slug'] = '../path'
    assert validate_model('arg_termo_catalogo.schema.json', data)
    assert scientific_errors({FIELD: term()})  # No unvalidated API bypass without a profile.


def test_structured_xml_keeps_names_provenance_and_native_metadata():
    data = payload(term()); data['id'] = 'abcde-12345'
    root = record_to_xml(data)
    compiled_xsd().assertValid(root)
    ns = {'a': DEFAULT_NAMESPACE}
    assert root.xpath('string(a:termo_catalogo/a:nome_pt)', namespaces=ns) == 'Mineral de teste'
    assert root.xpath('string(a:termo_catalogo/a:sinonimos/a:item[1])', namespaces=ns) == '001'
    nodes = root.xpath('a:termo_catalogo/a:enriquecimento//a:property[@name="zero"]', namespaces=ns)
    assert nodes[0].text == '0'
    assert root.xpath('a:termo_catalogo/a:enriquecimento//a:property[@name="confirmed"]', namespaces=ns)[0].text == 'false'
    root.find('{'+DEFAULT_NAMESPACE+'}termo_catalogo').remove(root.find('{'+DEFAULT_NAMESPACE+'}termo_catalogo/{'+DEFAULT_NAMESPACE+'}nome_pt'))
    assert not compiled_xsd().validate(root)


def test_coordinate_boundaries():
    for lat, lon in [('NaN','1'),('inf','1'),('91','0'),('0','181'),('','1'),('x','1')]:
        with raises(ValueError): patch_coordinates({}, 'legacy', lat, lon)


def test_coordinate_patch_is_narrow_and_preserves_zero():
    original = {'arg:amostras': [{'codigo_amostra': '001', 'campanha_id': 'c1', 'latitude': 1, 'longitude': 2, 'datum': 'declared'}],
                'arg:outro': {'preservar': True}}
    updated = patch_coordinates(original, 'arg:amostras/0', '0', '-180')
    assert updated['arg:amostras'][0]['latitude'] == 0
    assert updated['arg:amostras'][0]['longitude'] == -180
    assert updated['arg:amostras'][0]['datum'] == 'declared'
    assert updated['arg:outro'] == original['arg:outro']
    assert original['arg:amostras'][0]['latitude'] == 1
    with raises(ValueError): patch_coordinates(original, 'legacy', '0', '0')


def test_catalog_projection_keeps_the_persisted_source_separate():
    data = payload(term())['custom_fields']
    result = projection(data)
    assert result['catalog_slug'] == 'mineral-teste'
    assert result['catalog_status'] == 'ativo'
    assert 'enriquecimento' not in result
    assert data[FIELD]['enriquecimento']['source_profiles']['curadoria']['zero'] == 0


if __name__ == '__main__':
    checks = [unittest.FunctionTestCase(value) for key, value in globals().copy().items() if key.startswith('test_')]
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(checks))
    raise SystemExit(not result.wasSuccessful())
