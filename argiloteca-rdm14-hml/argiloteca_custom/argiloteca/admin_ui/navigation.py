"""One bilingual catalogue for the home page, module context and sidebar."""
from flask import current_app, request, url_for
from flask_babel import get_locale
from babel.numbers import format_decimal
from .ontology import ENTITIES


def tr(pt, en):
    return pt if get_locale().language == 'pt' else en


TOOLS = [
 ('population','povoamento','Visão integrada','Integrated overview','dashboard','argiloteca_population.index',None,'ARGILOTECA_POPULATION_ENABLED'),
 ('sources','povoamento','Fontes de dados','Data sources','upload','argiloteca_admin_ui.sources',None,None),
 ('enrichment','povoamento','Atualizar dados do acervo','Enrich collection data','refresh','argiloteca_openalex.enrichment_index',None,'ARGILOTECA_OPENALEX_ROOT'),
 ('authors','curadoria','Autores e ORCID','Authors and ORCID','communities','argiloteca_openalex.authors_index','orcid.png','ARGILOTECA_OPENALEX_ROOT'),
 ('connections','curadoria','Conexões científicas','Scientific connections','connections','argiloteca_scientific.connections_admin',None,None),
 ('catalog','curadoria','Catálogo de argilominerais','Clay mineral catalogue','layers','argiloteca_scientific.catalog_admin',None,None),
 ('map','curadoria','Coordenadas, topônimos e mapa','Coordinates, place names and map','map','argiloteca_scientific.map_admin',None,None),
 ('classification','curadoria','Revisar classificação','Review classification','communities','argiloteca_openalex.manual_index',None,'ARGILOTECA_OPENALEX_ROOT'),
 ('duplicates','curadoria','Revisar duplicados','Review duplicates','layers','argiloteca_openalex.duplicates_index',None,'ARGILOTECA_OPENALEX_ROOT'),
 ('drx_links','curadoria','Registros e dados DRX','Records and XRD data','drx','argiloteca_scientific.drx_link_admin',None,None),
 ('raw','preservacao','Arquivos RAW e classificações','RAW files and classifications','analyses','argiloteca_scientific.admin_raw_library',None,None),
 ('restricted','preservacao','Revisar arquivos restritos','Review restricted files','shield','argiloteca_scientific.restricted_raw_review',None,None),
 ('pdfs','preservacao','PDFs dos repositórios','Repository PDFs','document','argiloteca_repositories.pdf_index',None,'ARGILOTECA_REPOSITORIES_ENABLED'),
 ('archive','preservacao','Remover e arquivar','Remove and archive','archive','argiloteca_maintenance.index',None,'ARGILOTECA_OPENALEX_ROOT'),
 ('knowledge','preservacao','Conhecimento do ArgiloClay','ArgiloClay knowledge','catalog','argiloteca_knowledge.index',None,None),
]
SOURCES = [
 ('openalex','OpenAlex','openalex.png','Publicações e relações bibliográficas.','Publications and bibliographic relationships.','argiloteca_openalex.index','ARGILOTECA_OPENALEX_ROOT','https://openalex.org/'),
 ('pangaea','PANGAEA','pangaea.png','Dados de pesquisa da Terra e do ambiente.','Earth and environmental research data.','argiloteca_pangaea.index','ARGILOTECA_OPENALEX_ROOT','https://www.pangaea.de/'),
 ('mendeley','Mendeley Data','mendeley.svg','Conjuntos de dados científicos.','Scientific datasets.','argiloteca_mendeley.index','ARGILOTECA_MENDELEY_ENABLED','https://data.mendeley.com/'),
 ('lume','LUME UFRGS','lume.png','Produção acadêmica do repositório UFRGS.','Academic output from the UFRGS repository.','argiloteca_repositories.index','ARGILOTECA_REPOSITORIES_ENABLED','https://lume.ufrgs.br/'),
 ('ufsc','Repositório UFSC','ufsc.svg','Produção acadêmica do repositório UFSC.','Academic output from the UFSC repository.','argiloteca_repositories.index','ARGILOTECA_REPOSITORIES_ENABLED','https://repositorio.ufsc.br/'),
]
GROUPS = [('povoamento','Povoamento','Import data'),('curadoria','Curadoria e relações','Curation and relationships'),('preservacao','Arquivos e preservação','Files and preservation')]


def tools():
    result = []
    for key,group,pt,en,icon,endpoint,logo,flag in TOOLS:
        if flag and not current_app.config.get(flag): continue
        if endpoint not in current_app.view_functions: continue
        result.append({'id':key,'group':group,'label':tr(pt,en),'icon':icon,'href':url_for(endpoint,ln=get_locale().language),'endpoint':endpoint,'logo':logo})
    result.append({'id':'deposit','group':'authoring','label':tr('Novo registro científico','New scientific record'),
                   'icon':'plus','href':url_for('argiloteca_scientific.new',ln=get_locale().language),'endpoint':'argiloteca_scientific.new','logo':None})
    return result


def sources():
    rows=[]
    for key,label,logo,pt,en,endpoint,flag,official in SOURCES:
        enabled=bool(current_app.config.get(flag)) and endpoint in current_app.view_functions
        rows.append({'id':key,'label':label,'logo':logo,'description':tr(pt,en),'href':url_for(endpoint,ln=get_locale().language,**({'repository':key} if key in ('lume','ufsc') else {})) if enabled else None,'official':official,'enabled':enabled})
    return rows


def selected():
    endpoint=request.endpoint or ''; bp=request.blueprint or ''
    if bp=='argiloteca_admin_ui':
        return 'sources' if endpoint.endswith('.sources') else 'entities'
    if bp in ('argiloteca_pangaea','argiloteca_mendeley','argiloteca_repositories'):return 'sources'
    if bp=='argiloteca_population':return 'authors' if endpoint.rsplit('.',1)[-1] in ('authors','author','search','preview','apply','job_detail') else 'population'
    if bp=='argiloteca_maintenance':return 'archive'
    if bp=='argiloteca_knowledge':return 'knowledge'
    if bp=='argiloteca_openalex':
        for prefix,key in [('enrichment','enrichment'),('author','authors'),('orcid','authors'),('duplicates','duplicates'),('manual','classification'),('statistics','population')]:
            if endpoint.split('.')[-1].startswith(prefix):return key
        return 'sources'
    for key,group,pt,en,icon,target,logo,flag in TOOLS:
        if endpoint==target or endpoint.startswith(target.removesuffix('_admin')+'_'):return key
    return ''


def context():
    if not request.path.startswith('/administration'):return {}
    from ..scientific.restricted_review import can_review
    allowed=can_review()
    data=tools() if allowed else []
    groups=[{'id':key,'label':tr(pt,en),'items':[row for row in data if row['group']==key]} for key,pt,en in GROUPS]
    source=None;bp=request.blueprint or '';endpoint=request.endpoint or ''
    source_id={'argiloteca_pangaea':'pangaea','argiloteca_mendeley':'mendeley','argiloteca_openalex':'openalex'}.get(bp)
    if bp=='argiloteca_openalex' and selected()!='sources':source_id='orcid' if selected()=='authors' else None
    if bp=='argiloteca_population' and selected()=='authors':source_id='orcid'
    if bp=='argiloteca_repositories':source_id=request.args.get('repository') if request.args.get('repository') in ('lume','ufsc') else 'repositories'
    if source_id:source=next((s for s in sources() if s['id']==source_id),None)
    if source_id=='orcid':source={'label':'ORCID','logo':'orcid.png','id':'orcid'}
    if source_id=='repositories':source={'label':tr('Repositórios OAI','OAI repositories'),'logo':None,'id':'repositories'}
    overview=None
    if allowed and request.endpoint=='administration.dashboard':
        from .views import safe_counts
        overview=safe_counts()
    return {'admin_ux':{'counts':overview,'allowed':allowed,'groups':groups,'tools':{r['id']:r for r in data},'sources':sources() if allowed else [],
                         'active':selected(),'source':source,'entities':[{'id':key,'label':tr(*value['label']),'icon':value['icon'],'description':tr(*value['description']),
                             'href':url_for('argiloteca_admin_ui.entity',entity=key,ln=get_locale().language)} for key,value in ENTITIES.items()]},'au_t':tr,'au_locale':get_locale().language,'au_number':lambda value:format_decimal(value,locale=str(get_locale()))}
