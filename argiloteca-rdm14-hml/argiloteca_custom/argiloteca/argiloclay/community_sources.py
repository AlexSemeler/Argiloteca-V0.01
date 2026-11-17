"""Current, anonymous community About evidence. No record/index mutations."""
import hashlib
import json
import re
from html.parser import HTMLParser
from .presentation import fold, plain

ID = re.compile(r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}')
SLUG = re.compile(r'[a-z0-9][a-z0-9_-]{0,199}')
DEFINITION = re.compile(r'\b(o que (?:e|sao)|what (?:is|are)|defina|definicao|define|explique|explain|descreva|describe)\b')
GRAMMAR = set('o a os as e sao um uma que quais qual de da do das dos em na no nas nos por favor me explique explicar defina definicao descreva descrever sobre segundo conforme comunidade comunidades argiloteca the is are what an a of please explain define describe about according to community communities'.split())
GENERAL = {'argilominerais', 'argilomineral', 'clay minerals', 'clay mineral'}
GENERAL_SLUGS = ('caulim-serpentina', 'esmectitas', 'micas-argilosas-ilitas', 'hidrotalcitas-hidroxidos-duplos-lamelares')
GRAMMAR.update('tendencias tendencia pesquisa pesquisas registros relacionados relacionadas artigos publicacoes principais recentes atuais indique indicar mostre acervo assunto topic trends research papers publications related suggest recommend and in collection from'.split())


def normalize_question(question):
    return re.sub(r'\b(?:argiloinerais|argilomienerais|argilomineirais|argilominearis)\b','argilominerais',fold(question))


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[];self.aliases=set();self.hidden=0;self.anchor=None;self.label=[]
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'):self.hidden+=1
        if self.hidden:return
        if tag in ('p','div','li','h1','h2','h3','br'):self.parts.append('\n')
        if tag=='a':
            href=dict(attrs).get('href','')
            match=re.fullmatch(r'/argilominerais/([a-z0-9_-]+)/?',href)
            self.anchor=match[1] if match else None;self.label=[]
    def handle_endtag(self, tag):
        if tag in ('script','style'):
            self.hidden=max(0,self.hidden-1);return
        if self.hidden:return
        if tag in ('p','div','li','h1','h2','h3'):self.parts.append('\n')
        if tag=='a' and self.anchor:
            self.aliases.update([self.anchor,' '.join(self.label)])
            self.anchor=None;self.label=[]
    def handle_data(self, text):
        if self.hidden:return
        self.parts.append(text)
        if self.anchor:self.label.append(text)


def project(row):
    """Accept only public native communities with actual About text."""
    cid=row.get('id','');slug=row.get('slug','')
    md=row.get('metadata') or {};raw=md.get('page','')
    if (not isinstance(cid,str) or not ID.fullmatch(cid) or not isinstance(slug,str)
            or not SLUG.fullmatch(slug) or row.get('access',{}).get('visibility')!='public'
            or not row.get('updated') or not isinstance(raw,str) or not raw.strip()):return None
    page=Page();page.feed(raw[:64000])
    paragraphs=[re.sub(r'\s+',' ',p).strip() for p in ''.join(page.parts).split('\n')]
    prose=[]
    for p in filter(None,paragraphs):
        if re.match(r'^(palavras.chave|keywords|fontes.base|sources|imagem da cole[cç][aã]o|argilominerais relacionados)',fold(p)):break
        prose.append(p)
    if not prose:return None
    excerpt='\n\n'.join(prose)
    if len(excerpt)>2200:
        excerpt=excerpt[:2200].rsplit(' ',1)[0]+'…'
    title=plain(md.get('title',slug))[:300]
    page.aliases.update({'caulim-serpentina':{'kaolinite','kaolinita','caulinita','kaolin'},'esmectitas':{'smectites','smectite','esmectita'},'micas-argilosas-ilitas':{'illite','ilita'}}.get(slug,set()))
    page.aliases.update(re.split(r' e |[-–]',title,flags=re.I))
    if fold(title).startswith('argilominerais '):page.aliases.add(title.split(' ',1)[1])
    digest=hashlib.sha256(json.dumps([title,raw],ensure_ascii=False).encode()).hexdigest()
    return {'document_id':'community:'+cid+':about','title':title,'excerpt':excerpt,
            'community_id':cid,'community_slug':slug,'updated':row['updated'],'sha256':digest,
            'tipo_fonte':'comunidade_invenio','evidence_kind':'community_editorial_description',
            'derivation':'live_community_about','source_relative_path':'communities/'+slug+'/about',
            'url':'/communities/'+slug+'/about',
            '_aliases':sorted({fold(re.sub(r'[^\w\s-]',' ',s)).replace('-',' ').strip() for s in page.aliases|{title,slug} if s})}


def public_community(cid):
    from flask import has_app_context
    if not has_app_context():return None
    from invenio_communities.proxies import current_communities
    from flask_principal import AnonymousIdentity
    from invenio_access.permissions import any_user
    from flask_principal import PermissionDenied
    from invenio_pidstore.errors import PIDDoesNotExistError,PIDDeletedError,PIDUnregistered
    from sqlalchemy.orm.exc import NoResultFound
    identity=AnonymousIdentity();identity.provides.add(any_user)
    try:return project(current_communities.service.read(identity,cid).to_dict())
    except (PermissionDenied,PIDDoesNotExistError,PIDDeletedError,PIDUnregistered,NoResultFound):return None


def public_sources():
    from flask import has_app_context,g
    if not has_app_context():return []
    if hasattr(g,'argiloclay_community_sources'):return g.argiloclay_community_sources
    from invenio_communities.proxies import current_communities
    model=current_communities.service.record_cls.model_cls
    # Native IDs only; the anonymous service resolves all content and visibility.
    identifiers=model.query.with_entities(model.id).filter_by(deletion_status='P').order_by(model.id).limit(201)
    rows=[]
    for n,(cid,) in enumerate(identifiers):
        if n==200:raise ValueError('Community discovery limit exceeded')
        source=public_community(str(cid))
        if source:rows.append(source)
    g.argiloclay_community_sources=rows
    return rows


def select(question, sources):
    q=' '.join(re.findall(r'[\w]+',normalize_question(question)))
    if not DEFINITION.search(q):return []
    # Do not turn a sample/curve/field request into a community definition.
    if re.search(r'\b(amostra|sample|drx|xrd|pico|peak|medicao|measurement|identifique|identify)\b',q):return []
    if re.search(r'\b(registro|record)\b',q) and not re.search(r'\b(indique|mostre|related|suggest|recommend)\b',q):return []
    remaining=' '+q+' ';matched=[];aliases={}
    for source in sources:
        for alias in source.get('_aliases',[]):
            alias=' '.join(re.findall(r'[\w]+',alias))
            if alias:aliases.setdefault(alias,[]).append(source)
    for alias,candidates in sorted(aliases.items(),key=lambda pair:-len(pair[0])):
        token=' '+alias+' '
        if token not in remaining:continue
        titled=[s for s in candidates if token in ' '+' '.join(re.findall(r'[\w]+',fold(s['title'])))+' ']
        candidates=titled or candidates
        if len(candidates)!=1:return []
        matched.append(candidates[0]);remaining=remaining.replace(token,' ')
    general=False
    for alias in sorted(GENERAL,key=lambda a:-len(a)):
        token=' '+alias+' '
        if token in remaining:general=True;remaining=remaining.replace(token,' ')
    if set(remaining.split())-GRAMMAR:return []
    if general and not matched:
        by_slug={s['community_slug']:s for s in sources}
        matched=[by_slug[slug] for slug in GENERAL_SLUGS if slug in by_slug]
    unique={s['community_id']:s for s in matched}
    if len(unique)>4:return []
    return [{k:v for k,v in source.items() if not k.startswith('_')} for source in unique.values()]


def verify(source, resolver=public_community, excerpt=True):
    cid=source.get('community_id')
    if not isinstance(cid,str) or not ID.fullmatch(cid):return None
    current=resolver(cid)
    if not current:return None
    for key in ('document_id','community_slug','updated','sha256'):
        if source.get(key)!=current.get(key):return None
    if excerpt and (not isinstance(source.get('excerpt'),str) or not source['excerpt'] or source['excerpt'] not in current['excerpt']):return None
    clean={k:v for k,v in current.items() if not k.startswith('_')}
    if excerpt:clean['excerpt']=source['excerpt']
    clean['visibility_verified']=True
    return clean


def answer(sources, language='pt', question='', trend=''):
    en=language=='en'
    communities=[(i,s) for i,s in enumerate(sources,1) if s.get('derivation')=='live_community_about']
    general=any(term in normalize_question(question) for term in GENERAL)
    paragraphs=[]
    classical=[(i,s) for i,s in communities if s.get('community_slug') in GENERAL_SLUGS[:3]]
    if general and len(classical)>=2:
        # Synthesis limited to the verified group descriptions below. Related
        # LDH materials are not silently classified as classical phyllosilicates.
        intro=('Clay minerals are minerals that form part of clays. Layer structure and interactions with water and ions help explain the differences between their main groups.' if en else
               'Argilominerais são minerais que participam da composição das argilas. A estrutura em camadas e a interação com água e íons ajudam a explicar as diferenças entre seus principais grupos.')
        paragraphs.append(intro+' '+''.join('['+('Source' if en else 'Fonte')+' '+str(i)+']' for i,_ in classical))
        communities=classical
    for i,source in communities:
        sentences=re.split(r'(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕ])',source['excerpt'].replace('\n\n',' '))
        factual=[s for s in sentences if not re.match(r'^(na argiloteca|nesta comunidade|a comunidade|esta comunidade)\b',fold(s))]
        prose=' '.join(factual[:3]) or source['excerpt']
        paragraphs.append(prose+' ['+('Source' if en else 'Fonte')+' '+str(i)+']')
    if trend:paragraphs.append(trend)
    records=[(i,s) for i,s in enumerate(sources,1) if s.get('record_id')]
    if records:
        lines=[]
        for i,s in records:
            date=s.get('record_fields',{}).get('publication_date','')
            lines.append(s['title']+(' ('+date[:4]+')' if date else '')+' ['+('Source' if en else 'Fonte')+' '+str(i)+']')
        paragraphs.append(('Related publications in Argiloteca:\n' if en else 'Para aprofundar, consulte estas publicações da Argiloteca:\n')+'\n'.join(lines))
    return '\n\n'.join(paragraphs)
