"""The five conceptual entities map to actual scientific metadata blocks."""
from collections import OrderedDict

ENTITIES = OrderedDict([
    ('campo', {'label': ('Campo', 'Fieldwork'), 'icon': 'field',
               'description': ('Contexto geológico, localização e coleta.', 'Geological context, location and collection.'),
               'fields': ('arg:pesquisas_campo',), 'tools': ('map', 'connections')}),
    ('amostra', {'label': ('Amostra', 'Sample'), 'icon': 'sample',
                 'description': ('Material coletado, características e procedência.', 'Collected material, characteristics and provenance.'),
                 'fields': ('arg:amostras',), 'tools': ('connections',)}),
    ('analise', {'label': ('Análise', 'Analysis'), 'icon': 'analyses',
                 'description': ('DRX, geoquímica, métodos e resultados.', 'XRD, geochemistry, methods and results.'),
                 'fields': ('arg:analises', 'arg:pacotes_analiticos', 'arg:composicao_quimica_global'),
                 'tools': ('raw', 'drx_links', 'connections')}),
    ('argilomineral', {'label': ('Argilomineral', 'Clay mineral'), 'icon': 'layers',
                       'description': ('Identificação, propriedades e evidências minerais.', 'Identification, properties and mineral evidence.'),
                       'fields': ('arg:argilominerais', 'arg:termo_catalogo'), 'tools': ('catalog', 'map', 'connections')}),
    ('publicacoes', {'label': ('Publicações', 'Publications'), 'icon': 'catalog',
                     'description': ('Fontes bibliográficas, dados e referências relacionadas.', 'Bibliographic sources, data and related references.'),
                     'fields': ('arg:publicacoes_relacionadas',), 'tools': ('population', 'authors', 'connections')}),
])


def matches(data, entity):
    """Reference predicate for the census; no inference from titles or names."""
    spec = ENTITIES[entity]; cf = data.get('custom_fields') or {}
    if any(isinstance(cf.get(key), (list, dict)) and cf[key] for key in spec['fields']):
        return True
    resource = (data.get('metadata') or {}).get('resource_type') or {}
    return entity == 'publicacoes' and str(resource.get('id', '')).startswith('publication-')


# Only active native records and drafts. An edit draft replaces the publication
# for metadata inspection; the publication flag remains available separately.
EFFECTIVE = '''WITH versions AS (
 SELECT id::text uid,json::jsonb body,1 published,0 draft FROM rdm_records_metadata WHERE deletion_status='P' AND json IS NOT NULL
 UNION ALL
 SELECT d.id::text,d.json::jsonb,0,1 FROM rdm_drafts_metadata d WHERE d.json IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM rdm_records_metadata p WHERE p.id=d.id AND p.deletion_status!='P')
), flags AS (
 SELECT body->>'id' rid,max(published) published,max(draft) draft FROM versions WHERE body->>'id' IS NOT NULL GROUP BY body->>'id'
), effective AS (
 SELECT DISTINCT ON (v.body->>'id') v.uid,v.body,f.rid,f.published,f.draft FROM versions v
 JOIN flags f ON f.rid=v.body->>'id' ORDER BY v.body->>'id',v.draft DESC
) '''


def predicate(entity, params):
    """Only catalogued field names enter SQL; values are still bound parameters."""
    fields = []
    for index, field in enumerate(ENTITIES[entity]['fields']):
        key = entity + '_field_' + str(index); params[key] = field
        value = "body->'custom_fields'->:" + key
        fields.append("(jsonb_typeof(" + value + ") IN ('array','object') AND " + value + " NOT IN ('[]'::jsonb,'{}'::jsonb))")
    if entity == 'publicacoes':
        fields.append("body->'metadata'->'resource_type'->>'id' LIKE 'publication-%'")
    return '(' + ' OR '.join(fields) + ')'
