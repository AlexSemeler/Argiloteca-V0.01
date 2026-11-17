"""Public record projection and bilingual structured-field intents; no credentials."""
import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser

PUBLIC_FIELDS = ('title','additional_titles','creators','contributors','publisher',
    'publication_date','dates','version','resource_type','subjects','description',
    'additional_descriptions','languages','identifiers','related_identifiers','rights',
    'copyright','funding','references','sizes','formats','locations')
FIELD_ALIASES = {
 'creators':r'\b(autor(?:es)?|autoras?|criador(?:es)?|criadoras?|autoria|authors?|creators?|who wrote)\b',
 'contributors':r'\b(colaborador(?:es)?|contribuidor(?:es)?|contributors?)\b',
 'title':r'\b(titulos?|titles?)\b',
 'additional_titles':r'\b(titulos? alternativos?|additional titles?)\b',
 'identifiers':r'\b(identificador(?:es)?|identifiers?|doi|orcid)\b',
 'publication_date':r'\b(publicacao|publicado|publicada|publication|published)\b',
 'created':r'\b(criacao|criado|criada|creation|created)\b',
 'updated':r'\b(atualizacao|atualizado|atualizada|modificacao|updated|modified|update)\b',
 'dates':r'\b(datas|dates)\b',
 'resource_type':r'\b(tipo|tipos|type|types)\b',
 'subjects':r'\b(assuntos?|palavras.chave|subjects?|keywords?)\b',
 'description':r'\b(descricoes|descricao|resumo|abstracts?|descriptions?)\b',
 'rights':r'\b(licencas?|direitos|licenses?|rights)\b',
 'publisher':r'\b(editoras?|editor(?:es)?|publisher|publicador)\b',
 'funding':r'\b(financiamento|financiador(?:es)?|funding|funders?)\b',
 'references':r'\b(referencias?|bibliografia|references?)\b',
 'version':r'\b(versao|version)\b',
 'languages':r'\b(idiomas?|linguas?|languages?)\b',
 'custom_fields':r'\b(metadados cientificos|scientific metadata)\b',
}
GRAMMAR = set('a o as os ao aos e de da do das dos em no na nos nas um uma quais qual que quem quando como por favor me diga informe informar mostre mostrar liste listar forneca apresente apresentar sao e foi foram esta estao este esta esse essa deste desta desse dessa neste nesta nesse nessa registro registros trabalho estudo documento publicacao dados dado recurso cientificos cientifico nome nomes todos todas completo completos metadados ultima ultimo primeira primeiro data ano mes dia the a an and of for in on this that these record records dataset please show list tell give what which who when is are was were last latest first scientific metadata resource document registered informado informada registrados registradas disponivel disponiveis consta constam tem possui ha quero saber'.split())
for expression in FIELD_ALIASES.values():
 GRAMMAR.update(re.findall(r'[a-z]+',expression))

def fold(value):
 return ''.join(c for c in unicodedata.normalize('NFKD',str(value).lower()) if not unicodedata.combining(c))

class Plain(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.hidden=0
 def handle_starttag(self,tag,attrs):
  if tag in ('script','style'):self.hidden+=1
 def handle_endtag(self,tag):
  if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
 def handle_data(self,data):
  if not self.hidden:self.parts.append(data)

def plain(value):
 p=Plain();p.feed(str(value));return re.sub(r'\s+',' ',' '.join(p.parts)).strip()

def field_requests(question):
 q=fold(question);q=re.sub(r'\b[a-z0-9]{5}-[a-z0-9]{5}\b','',q)
 requested=[key for key,pattern in FIELD_ALIASES.items() if re.search(pattern,q)]
 if re.search(r'\b(todos (?:os )?metadados|all (?:the )?metadata)\b',q):requested=list(FIELD_ALIASES)
 # A field word cannot turn an unrelated question into a claim about a record.
 remaining=set(re.findall(r'[a-z]+',q))
 allowed=GRAMMAR|set('publicado publicada publicados publicadas autores autor autora autoras criadores criador criadoras contribuidores colaborador colaboradores contribuidores titulos titulo identificador identificadores atualizada atualizado criacao criado criada modificacao publicacao tipo recurso tipos assuntos assunto palavras chave descricao descricoes resumo licenca licencas direitos editor editora editores editoras financiamento financiadores referencias referencia bibliografia versao idioma idiomas linguas lingua data datas atualizacao'.split())
 allowed.update(['alternativo','alternativos','additional'])
 if remaining-allowed:return []
 if re.search(r'\b(data|date|quando|when)\b',q) and not any(k in requested for k in ('publication_date','created','updated','dates')):requested.extend(['publication_date','created','updated'])
 if 'dates' in requested and any(k in requested for k in ('publication_date','created','updated')):requested.remove('dates')
 return requested

def safe_metadata(row):
 md=row.get('metadata',{});safe={k:md[k] for k in PUBLIC_FIELDS if k in md}
 safe['custom_fields']={k:v for k,v in row.get('custom_fields',{}).items() if k.startswith('arg:')}
 for key in ('created','updated'):
  if row.get(key):safe[key]=row[key]
 pids={k:{'identifier':v['identifier']} for k,v in row.get('pids',{}).items() if isinstance(v,dict) and isinstance(v.get('identifier'),str)}
 if pids:safe['persistent_identifiers']=pids
 return safe

def project(row,base):
 if row.get('access',{}).get('record')!='public' or row.get('is_draft') is True or row.get('is_published') is False:raise ValueError('Public published metadata only')
 md=safe_metadata(row);text=plain(json.dumps(md,ensure_ascii=False,sort_keys=True))
 result={'record_id':str(row['id']),'title':plain(md.get('title','Sem título')),
  'text':text,'updated':row.get('updated'),'source_type':'registro_invenio',
  'url':base.rstrip('/')+'/records/'+str(row['id']),
  'sha256':hashlib.sha256(text.encode()).hexdigest(),'access':'public'}
 profile=catalog_projection(row)
 if profile:result['catalog_profile']=profile
 return result


def catalog_projection(row):
 """Only explicitly public, active native catalog fields; no seed fallback."""
 term=row.get('custom_fields',{}).get('arg:termo_catalogo')
 if not isinstance(term,dict) or term.get('situacao')!='ativo':return None
 slug=term.get('slug','')
 if not isinstance(slug,str) or not re.fullmatch(r'[a-z0-9_-]{1,100}',slug):return None
 enriched=term.get('enriquecimento') or {};profile={'slug':slug}
 for key in ('nome_pt','nome_en','nome_cientifico_padronizado','descricao_curta','descricao_classica',
             'formula_ideal','classe_estrutural','sistema_cristalino','grupo_mineralogico','ambiente_formacao','external_uri','fonte_descricao'):
  value=term.get(key,enriched.get(key))
  if isinstance(value,str) and value.strip():profile[key]=plain(value)[:2200]
 synonyms=term.get('sinonimos',enriched.get('aliases',[]))
 if isinstance(synonyms,list):profile['aliases']=[plain(v)[:100] for v in synonyms[:30] if isinstance(v,str)]
 if 'ambiente_formacao' not in profile and isinstance(enriched.get('ambiente_tipico_formacao'),str):profile['ambiente_formacao']=plain(enriched['ambiente_tipico_formacao'])[:1000]
 blocks=enriched.get('source_profiles',{})
 if isinstance(blocks,dict):
  facts=[]
  for name in ('handbook_mineralogy','cms_source_clays'):
   block=blocks.get(name,{})
   if not isinstance(block,dict):continue
   if name=='handbook_mineralogy':
    for key,label in (('occurrence','Ocorrência'),('association','Associações'),('distribution','Distribuição'),('chemistry','Química'),('name_origin','Origem do nome'),('xray_powder_pattern','Difração de raios X')):
     if isinstance(block.get(key),str) and block[key].strip():facts.append({'label':label,'value':plain(block[key])[:1000],'source':name})
   for fact in block.get('facts',[])[:12]:
    if isinstance(fact,dict) and isinstance(fact.get('label'),str) and isinstance(fact.get('value'),str):
     facts.append({'label':plain(fact['label'])[:100],'value':plain(fact['value'])[:1000],'source':name})
  if facts:profile['facts']=facts[:20]
 return profile
