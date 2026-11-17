"""Canonical Argiloteca custom-field contract for InvenioRDM 14.

The v12 database contains 46 ``arg:`` keys, although its live configuration
does not register any custom fields.  This module declares exactly the JSON
types observed in the source database.  Structured values deliberately keep
dynamic object mappings: this preserves the heterogeneous, curated legacy
payloads without inventing scientific values or narrowing their schema during
the infrastructure migration.
"""

from marshmallow import fields

from invenio_records_resources.services.custom_fields import (
    BaseListCF,
    DoubleCF,
    TextCF,
)


class DynamicObjectCF(BaseListCF):
    """An object or list of objects with a dynamic OpenSearch mapping."""

    def __init__(self, name, *, multiple=False):
        super().__init__(name, field_cls=fields.Dict, multiple=multiple)

    @property
    def mapping(self):
        return {"type": "object", "dynamic": True}


TEXT_FIELDS = (
    "arg:amostra_data_coleta",
    "arg:amostra_descricao_local",
    "arg:amostra_local_coleta",
    "arg:amostra_tipo_amostra",
    "arg:analise_data",
    "arg:analise_descricao",
    "arg:analise_equipamento",
    "arg:analise_metodos_relacionados",
    "arg:analise_resultado",
    "arg:composicao_descricao_componentes",
    "arg:composicao_proporcoes",
    "arg:descricao_componentes",
    "arg:equipamento_descricao",
    "arg:equipamento_fabricante",
    "arg:equipamento_nome",
    "arg:metodo_descricao",
    "arg:metodo_tecnicas_utilizadas",
    "arg:metodologia_descricao",
    "arg:metodologia_equipamento_utilizado",
    "arg:metodologia_nome",
    "arg:metodologia_objetivo",
    "arg:origem_ambiente_formacao",
    "arg:origem_era_geologica",
    "arg:origem_formacao_geologica",
    "arg:origem_tipo_rocha",
    "arg:pesquisa_data",
    "arg:pesquisa_local",
    "arg:pesquisa_metodologias_relacionadas",
    "arg:pesquisa_responsavel",
    "arg:publicacao_amostras_relacionadas",
    "arg:publicacao_argilominerais_relacionados",
    "arg:usos_aplicacoes_cientificas",
    "arg:usos_aplicacoes_industriais",
    "arg:usos_aplicacoes_tecnologicas",
    "arg:usos_argilomineral_nome",
    "arg:usos_descricao",
)

DOUBLE_FIELDS = (
    "arg:amostra_altitude",
    "arg:amostra_latitude",
    "arg:amostra_longitude",
)

LIST_OBJECT_FIELDS = (
    "arg:amostras",
    "arg:analises",
    "arg:argilominerais",
    "arg:pesquisas_campo",
    "arg:publicacoes_relacionadas",
)

OBJECT_FIELDS = (
    "arg:composicao_quimica_global",
    "arg:proporcoes_resultados_principais",
)


def build_custom_fields():
    """Build the complete 46-key field list in a deterministic order."""

    result = [TextCF(name=name) for name in TEXT_FIELDS]
    result.extend(DoubleCF(name=name) for name in DOUBLE_FIELDS)
    result.extend(DynamicObjectCF(name, multiple=True) for name in LIST_OBJECT_FIELDS)
    result.extend(DynamicObjectCF(name) for name in OBJECT_FIELDS)
    return sorted(result, key=lambda field: field.name)


LEGACY_CUSTOM_FIELDS = build_custom_fields()

from .scientific.fields import ProfileCF, ProjectionCF

class UnindexedObjectCF(DynamicObjectCF):
    @property
    def mapping(self):
        return {"type": "object", "enabled": False}

ARGILOTECA_CUSTOM_FIELDS = [*LEGACY_CUSTOM_FIELDS, ProfileCF(), ProjectionCF(),
    UnindexedObjectCF("arg:termo_catalogo"),
    UnindexedObjectCF("arg:conexoes_cientificas", multiple=True),
    UnindexedObjectCF("arg:pacotes_analiticos", multiple=True),
    UnindexedObjectCF("arg:referencias_drx_webmineral", multiple=True)]

assert len(LEGACY_CUSTOM_FIELDS) == 46
assert len({field.name for field in ARGILOTECA_CUSTOM_FIELDS}) == 52
