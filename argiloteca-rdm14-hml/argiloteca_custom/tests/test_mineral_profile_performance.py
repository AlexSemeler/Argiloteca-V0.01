"""Request-scoped mineral lookup and unchanged public DRX summary semantics."""
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import Mock,patch
from flask import Flask
from argiloteca import mineralogia,views
from argiloteca.scientific import catalog
from argiloteca.services import drx


def row(slug,name,state='ativo',access='public'):
    return SimpleNamespace(json={'id':slug+'-12345','access':{'record':access},'custom_fields':{
        catalog.FIELD:{'slug':slug,'nome_pt':name,'nome_en':slug,'nome_cientifico_padronizado':slug,
                       'sinonimos':['Alias '+name],'situacao':state,'enriquecimento':{}}}},
        deletion_status=catalog.RecordDeletionStatusEnum.PUBLISHED)


def setup():
    app=Flask(__name__);app.extensions['invenio-rdm-records']=object()
    rows=[row('kaolinite','Caulinita'),row('illite','Ilita')]
    class Record(dict):updated=datetime(2026,10,22,tzinfo=timezone.utc)
    def read(identity,pid):
        assert identity.id is None
        saved=next(r for r in rows if r.json['id']==pid)
        return SimpleNamespace(id=pid,_record=Record(deepcopy(saved.json)))
    return app,rows,Mock(side_effect=read)


def test_targeted_lookup_checks_one_record_then_reuses_only_within_request():
    app,rows,reader=setup()
    with patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)):
        with app.test_request_context('/'):
            assert mineralogia.build_mineral_profile('kaolinite')['nome_pt']=='Caulinita'
            assert mineralogia.build_mineral_profile('Alias Caulinita')['slug']=='kaolinite'
            assert reader.call_count==1
            assert len(catalog.public_catalog())==2
            assert reader.call_count==2
        with app.test_request_context('/'):
            mineralogia.build_mineral_profile('kaolinite');assert reader.call_count==3


def test_curatorial_invalidation_clears_targeted_rows_profiles_and_full_catalog():
    app,rows,reader=setup()
    with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)):
        assert mineralogia.build_mineral_profile('kaolinite')['nome_pt']=='Caulinita'
        rows[0].json['custom_fields'][catalog.FIELD]['nome_pt']='Nome atualizado'
        catalog.invalidate_public_catalog()
        assert mineralogia.build_mineral_profile('kaolinite')['nome_pt']=='Nome atualizado'
        rows[0].json['access']['record']='restricted';catalog.invalidate_public_catalog()
        assert mineralogia.build_mineral_profile('kaolinite') is None
        assert reader.call_count==2


def test_targeted_private_and_withdrawn_terms_never_fall_back_to_seed():
    app,rows,reader=setup()
    for field,value in [('access','restricted'),('state','retirado')]:
        rows[0]=row('kaolinite','Caulinita',**{field:value})
        with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)):
            assert mineralogia.build_mineral_profile('kaolinite') is None
            assert mineralogia.build_mineral_profile('Caulinita') is None
            assert not reader.called


def test_targeted_lookup_does_not_turn_native_permission_denial_into_file_fallback():
    from invenio_records_resources.services.errors import PermissionDeniedError
    app,rows,reader=setup();reader.side_effect=PermissionDeniedError('read')
    with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)),patch.object(mineralogia,'build_file_mineral_profile') as fallback:
        try:mineralogia.build_mineral_profile('kaolinite')
        except PermissionDeniedError:pass
        else:raise AssertionError('Native denial bypassed')
        fallback.assert_not_called()


def test_profile_return_is_defensive_and_blank_lookup_does_not_load_catalog():
    app,rows,reader=setup()
    with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)):
        assert mineralogia.build_mineral_profile(None) is None;reader.assert_not_called()
        first=mineralogia.build_mineral_profile('kaolinite');first['nome_pt']='Changed by consumer'
        assert mineralogia.build_mineral_profile('kaolinite')['nome_pt']=='Caulinita'


def test_homonymous_alias_keeps_catalog_order_and_exact_slug_keeps_precedence():
    app,rows,reader=setup()
    rows[:]=[row('chlorite_group','Clorita'),row('chlorite','Clorita')]
    rows[0].json['custom_fields'][catalog.FIELD]['nome_en']='Chlorite'
    with app.test_request_context('/'),patch.object(catalog,'catalog_rows',return_value=rows),patch.object(catalog,'service',SimpleNamespace(read=reader)):
        assert mineralogia.build_mineral_profile('Chlorite')['slug']=='chlorite_group'
        assert mineralogia.build_mineral_profile('chlorite')['slug']=='chlorite'


def test_map_resolves_filter_aliases_once_for_the_entire_public_collection():
    records=[{'id':str(i),'custom_fields':{'arg:argilominerais':[{'nome':'Caulinita'}]}} for i in range(100)]
    with patch.object(catalog,'available',return_value=True),patch.object(catalog,'public_map_records',return_value=iter(records)),patch.object(views,'_mineral_lookup_targets',return_value={'caulinita'}) as targets,patch.object(views,'build_mineral_profile') as profiles,patch.object(views,'_extract_points_from_record',return_value=[]):
        result=views._build_argilomineral_points_payload(mineral_term='kaolinite')
        assert result['matched_records']==100;targets.assert_called_once_with('kaolinite');profiles.assert_not_called()


def test_drx_summary_uses_one_complete_filtered_snapshot_and_original_grouping():
    pairs=[]
    for n,preparation in enumerate(['natural','glicolado','calcinado']):
        pairs.append(({'id':str(n),'sample_base':'A','sample_code':'A','filename':str(n),'preparation':preparation,'mineral_candidates':[]},{}))
    with patch.object(drx,'_filtered_raw_snapshot_pairs',return_value=([1,2,3],pairs)) as filtered:
        expected=drx.build_raw_snapshot_comparison_suggestions(filters={'argilomineral':'kaolinite'},limit=1)
        filtered.reset_mock()
        actual=drx.summarize_raw_snapshot_mineral(filters={'argilomineral':'kaolinite'})
        assert actual=={'count':3,'has_trio':any(s['type']=='trio' for s in expected['suggestions'])}
        assert actual['has_trio'];filtered.assert_called_once_with({'argilomineral':'kaolinite'})


def test_empty_drx_summary_remains_empty_without_extra_enrichment():
    with patch.object(drx,'_filtered_raw_snapshot_pairs',return_value=([],[])),patch.object(drx,'_load_advanced_drx_enrichment_index') as advanced:
        assert drx.summarize_raw_snapshot_mineral(filters={'argilomineral':'unknown'})=={'count':0,'has_trio':False}
        advanced.assert_not_called()
