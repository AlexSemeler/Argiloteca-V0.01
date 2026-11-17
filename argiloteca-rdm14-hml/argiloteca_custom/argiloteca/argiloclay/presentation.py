"""Readable, cited renderings of verified metadata; no scientific inference."""
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser

CATEGORY = {'species':'uma espécie mineral','group':'um grupo mineralógico','family':'uma família mineralógica',
            'series':'uma série mineralógica','material':'um material','interstratified':'um interestratificado'}

def fold(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(text).lower()) if not unicodedata.combining(c))

class Plain(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
        elif tag in ('p','br','div','li'):self.parts.append(' ')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
        elif tag in ('p','div','li'):self.parts.append(' ')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def plain(value):
    p=Plain();p.feed(str(value));return re.sub(r'\s+',' ',''.join(p.parts)).strip()

def snippet(value,limit=650):
    value=plain(value).replace('Abstract ArgiloClay-Robo:','').strip()
    if len(value)<=limit:return value
    cut=value[:limit];boundary=max(cut.rfind('. '),cut.rfind('; '))
    return cut[:boundary+1] if boundary>limit//2 else cut.rsplit(' ',1)[0]+'…'

def record_source(record,rid,question=None):
    """Selected fields read under the current Invenio identity, not JSON chunks."""
    if question:
        structured=structured_record_source(record,rid,question)
        if structured:return structured
    catalog=catalog_source(record,rid,question)
    if catalog:return catalog
    md=record.get('metadata',{});title=plain(md.get('title',''))
    if not title:return None
    desc=plain(md.get('description',''))
    fields={'title':title,'description':snippet(desc,1600)}
    minerals=record.get('custom_fields',{}).get('arg:argilominerais',[])
    if isinstance(minerals,list):
        terms=[]
        for mineral in minerals[:20]:
            if isinstance(mineral,dict) and isinstance(mineral.get('nome'),str):
                name=plain(mineral['nome'])
                if name and len(name)<=80 and name not in terms:terms.append(name)
        if terms:fields['mineral_terms']=terms[:8]
    publication=md.get('publication_date')
    if isinstance(publication,str):fields['publication_date']=publication[:40]
    # Keep only explicit language metadata; no unverified translation.
    languages=md.get('languages',[])
    fields['languages']=[r.get('id','') for r in languages[:10] if isinstance(r,dict)] if isinstance(languages,list) else []
    excerpt='Título: '+title+'.'
    if fields.get('mineral_terms'):excerpt+=' Termos minerais associados nos metadados: '+', '.join(fields['mineral_terms'])+'.'
    if fields['description']:excerpt+=' Descrição informada: '+fields['description']
    if fields.get('publication_date'):excerpt+=' Publicação: '+fields['publication_date']+'.'
    return {'document_id':'live-overview:'+rid,'title':title,'excerpt':excerpt,'record_id':rid,
            'updated':record.get('updated'),'tipo_fonte':'registro_invenio','record_fields':fields,
            'derivation':'live_public_metadata_overview','source_relative_path':'records/'+rid+'.json',
            'sha256':hashlib.sha256(json.dumps(fields,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}

def field(source,label):
    match=re.search(re.escape(label)+r':\s*([^.]+)\.',source.get('excerpt',''))
    return match[1].strip() if match else None

def family_line(source,sources,number):
    family=field(source,'Família')
    if not family or family!=source.get('family'):return ''
    for i,group in enumerate(sources,1):
        if group.get('tipo_fonte')=='vocabulario' and group.get('vocabulary')=='grupo_mineralogico' and group.get('term_id')==family:
            label=field(group,'Nome preferido')
            if label:return 'Na organização da Argiloteca, aparece em “'+label+'”. [Fonte '+str(number)+'] [Fonte '+str(i)+']'
    return ''

def didactic_answer(question,sources):
    q=fold(question or '')
    overviews=[(i,source) for i,source in enumerate(sources,1) if source.get('derivation')=='live_public_metadata_overview']
    if len(overviews)>1:
        return 'Registros encontrados na Argiloteca\n\n'+'\n\n'.join(didactic_answer(question,[source]).replace('[Fonte 1]','[Fonte '+str(i)+']') for i,source in overviews)
    catalog=catalog_answer(question,sources)
    if catalog:return catalog
    for i,source in enumerate(sources,1):
        if source.get('derivation')=='live_public_metadata_fields':
            return '\n\n'.join(line+' [Fonte '+str(i)+']' for line in source['excerpt'].splitlines())
    vocab=[(i,s) for i,s in enumerate(sources,1) if s.get('tipo_fonte')=='vocabulario' and s.get('category') in CATEGORY and field(s,'Categoria')==s.get('category')]
    primary=[(i,s) for i,s in vocab if s.get('vocabulary')!='grupo_mineralogico'] or vocab
    if primary:
        paragraphs=[]
        for i,source in primary[:2]:
            name=field(source,'Nome preferido');category=source.get('category')
            if not name:continue
            if 'ingles' in q:
                english=field(source,'Nome em inglês')
                if not english:return None
                paragraphs.append('O nome em inglês de '+name+' é '+english+'. [Fonte '+str(i)+']')
            elif re.search(r'\b(id|identificador)\b',q):
                identifier=field(source,'ID')
                if not identifier:return None
                paragraphs.append('O identificador de '+name+' no vocabulário é “'+identifier+'”. [Fonte '+str(i)+']')
            else:
                paragraphs.append(name+' é '+CATEGORY[category]+'. [Fonte '+str(i)+']')
                relation=family_line(source,sources,i)
                if relation:paragraphs.append(relation)
        if len(primary)>1 and re.search(r'\b(diferenca|compare|comparar)\b',q):
            paragraphs.append('Essa comparação mostra a classificação no vocabulário. Estes trechos não bastam para comparar propriedades ou comportamento das amostras.')
        return '\n\n'.join(paragraphs) if paragraphs else None
    for i,source in enumerate(sources,1):
        fields=source.get('record_fields')
        if source.get('derivation')!='live_public_metadata_overview' or not isinstance(fields,dict):continue
        title=fields.get('title');description=fields.get('description','')
        if not isinstance(title,str) or not title:return None
        marker=' [Fonte '+str(i)+']'
        answer='O tema apresentado no título deste registro é “'+title+'”.'+marker
        if fields.get('mineral_terms'):
            answer+='\n\nNos metadados da Argiloteca, o registro está associado a: '+', '.join(fields['mineral_terms'])+'.'+marker
        if re.search(r'\b(data|publicacao|publicado)\b',q) and fields.get('publication_date'):
            answer+='\n\nA data de publicação informada é '+fields['publication_date']+'.'+marker
        elif description:
            langs=fields.get('languages',[])
            original=bool(langs) and not any(str(v).lower() in ('pt','por','pt-br') for v in langs)
            caption='A descrição está em outro idioma. Trecho original: “' if original else 'Na descrição do registro: “'
            answer+='\n\n'+caption+snippet(description)+'”'+marker
        else:answer+='\n\nNão há descrição disponível nesses metadados para detalhar o conteúdo.'
        return answer
    return None

def enrich_generation(answer,sources):
    if not sources:return answer
    # The family link is rendered independently, never inferred by the LLM.
    extra=family_line(sources[0],sources,1)
    return answer+'\n\n'+extra if extra else answer

FIELD_LABELS = {'creators':'Autores/criadores','contributors':'Colaboradores','title':'Título',
 'additional_titles':'Títulos alternativos','identifiers':'Identificadores','publication_date':'Data de publicação',
 'created':'Data de criação do registro no Invenio','updated':'Última atualização do registro no Invenio',
 'dates':'Outras datas informadas','resource_type':'Tipo de recurso','subjects':'Assuntos',
 'description':'Descrição/resumo','rights':'Licenças e direitos','publisher':'Editora/publicador',
 'funding':'Financiamento','references':'Referências','version':'Versão','languages':'Idiomas',
 'custom_fields':'Metadados científicos'}


def metadata_value(value):
    """Render explicit public values; never translate names or infer missing data."""
    if value is None or value == '' or value == [] or value == {}:
        return 'Não informado nestes metadados públicos.'
    if isinstance(value,list):
        return '; '.join(metadata_value(v) for v in value[:30]) + ('; consulte o registro para os demais itens.' if len(value)>30 else '')
    if isinstance(value,dict):
        if 'person_or_org' in value:
            person=value['person_or_org'];name=person.get('name') or ' '.join(filter(None,[person.get('given_name'),person.get('family_name')]))
            ids=person.get('identifiers') or []
            return plain(name)+((' ('+metadata_value(ids)+')') if ids else '')
        if value.get('identifier'):
            return plain(value.get('scheme',''))+': '+plain(value['identifier']) if value.get('scheme') else plain(value['identifier'])
        if value.get('subject'):return plain(value['subject'])
        title=value.get('title')
        if isinstance(title,dict):
            label=plain(title.get('pt') or title.get('en') or value.get('id',''))
            details=[plain(value[k]) for k in ('id','link') if isinstance(value.get(k),str)]
            return label+(' ('+'; '.join(details)+')' if details else '')
        if isinstance(title,str):return plain(title)
        return '; '.join(plain(k)+': '+metadata_value(v) for k,v in value.items())
    return plain(value)


def structured_record_source(record,rid,question):
    from .public_metadata import field_requests,safe_metadata
    requested=field_requests(question)
    if not requested:return None
    safe=safe_metadata(record);selected={}
    for field in requested:
        value=safe.get(field)
        if field=='description' and safe.get('additional_descriptions'):
            value=[safe.get('description'),*safe['additional_descriptions']]
        if field=='identifiers':
            value=list(safe.get('identifiers') or [])
            value += [{'scheme':k,**v} for k,v in safe.get('persistent_identifiers',{}).items()]
            if 'orcid' in fold(question):
                for creator in safe.get('creators',[]):value.extend(creator.get('person_or_org',{}).get('identifiers',[]))
        selected[field]=value
    lines=[];budget=5400
    for key,value in selected.items():
        text=FIELD_LABELS[key]+': '+metadata_value(value)
        if len(text)>budget:
            text=snippet(text,max(100,budget-80))+' Consulte o registro para a lista integral.'
        lines.append(text);budget-=len(text)+2
        if budget<150:break
    excerpt='\n'.join(lines)
    return {'document_id':'live-fields:'+rid,'title':plain(record['metadata']['title']),
       'excerpt':excerpt,'record_id':rid,'updated':record.get('updated'),
       'tipo_fonte':'registro_invenio','record_fields':dict(zip(list(selected)[:len(lines)],lines)),
       'derivation':'live_public_metadata_fields','source_relative_path':'records/'+rid+'.json',
       'sha256':hashlib.sha256(json.dumps(selected,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}


CATALOG_LABELS={'formula_ideal':'Fórmula ideal','classe_estrutural':'Estrutura',
 'sistema_cristalino':'Sistema cristalino','grupo_mineralogico':'Grupo mineralógico',
 'ambiente_formacao':'Ambiente de formação'}

def catalog_source(record,rid,question=None):
    from .public_metadata import catalog_projection
    profile=catalog_projection(record)
    if not profile:return None
    fields={k:profile[k] for k in ('slug','nome_pt','nome_en','descricao_curta','descricao_classica',*CATALOG_LABELS) if profile.get(k)}
    name=fields.get('nome_pt') or record.get('metadata',{}).get('title','')
    lines=[]
    for key in ('descricao_curta','formula_ideal','classe_estrutural','sistema_cristalino','grupo_mineralogico','ambiente_formacao'):
        if fields.get(key):lines.append((CATALOG_LABELS.get(key,'Descrição')+': '+fields[key]))
    facts=profile.get('facts',[])
    if facts:fields['facts']=facts
    for fact in facts[:8]:lines.append(fact['label']+': '+fact['value'])
    excerpt=snippet('\n'.join(lines),5200)
    return {'document_id':'catalog:'+rid,'title':name,'excerpt':excerpt,
      'record_id':rid,'updated':record.get('updated'),'tipo_fonte':'registro_invenio',
      'catalog_slug':profile['slug'],'catalog_fields':fields,'derivation':'live_mineral_catalog',
      'source_relative_path':'records/'+rid+'.json',
      'sha256':hashlib.sha256(json.dumps(profile,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}

def catalog_answer(question,sources):
    selected=[(i,s) for i,s in enumerate(sources,1) if s.get('derivation')=='live_mineral_catalog' and isinstance(s.get('catalog_fields'),dict)]
    if not selected:return None
    q=fold(question or '');paragraphs=[]
    general=bool(re.search(r'\bargilomi(?:ne|ene)rais\b',q)) and len(selected)>1
    requested=[]
    for pattern,key in [(r'formula|composicao|quimica','formula_ideal'),(r'estrutura|estrutural','classe_estrutural'),
         (r'cristalin|sistema','sistema_cristalino'),(r'grupo','grupo_mineralogico'),(r'ocorrencia|formacao|ambiente|onde','ambiente_formacao')]:
        if re.search(pattern,q):requested.append(key)
    for i,s in selected:
        fields=s['catalog_fields'];name=plain(fields.get('nome_pt',s['title']));mark=' [Fonte '+str(i)+']'
        paragraphs.append(name)
        if not requested:
            desc=fields.get('descricao_curta') or fields.get('descricao_classica')
            if desc:paragraphs.append(snippet(desc,950)+mark)
        keys=requested or list(CATALOG_LABELS)
        for key in keys:
            if fields.get(key):paragraphs.append(CATALOG_LABELS[key]+': '+plain(fields[key])+'.'+mark)
            elif requested:paragraphs.append(CATALOG_LABELS[key]+': não informado nesta ficha pública.'+mark)
        facts=fields.get('facts',[])
        wanted=[]
        for fact in facts:
            label=fold(fact['label'])
            if requested and 'ambiente_formacao' in requested and re.search(r'ocorrencia|distribuicao',label):wanted.append(fact)
            elif not requested and re.search(r'ocorrencia|associacoes|distribuicao',label):wanted.append(fact)
            elif any(term in q and term in label for term in ('dureza','densidade','cor')):wanted.append(fact)
        for fact in wanted[:2]:paragraphs.append(plain(fact['label'])+': '+snippet(fact['value'],600)+mark)
        if any(term in q for term in ('dureza','densidade','cor')) and not wanted:
            paragraphs.append('A propriedade solicitada não está informada nos campos desta ficha pública.'+mark)
    if re.search(r'\b(amostra|identifique|identificar|medicao|sample|identify|measurement)\b',q):
        paragraphs.append('Identificar um mineral em uma amostra exige os dados analíticos correspondentes.')
    return '\n\n'.join(paragraphs)
