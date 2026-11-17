"""Exact catalog retrieval with a bounded question grammar, never general knowledge."""
import json,re
from contextlib import closing
from .engine import connect
from .corpus import words,fold
from .taxonomy import QUESTION_WORDS

EXTRA=set('sao principal principais fichas ficha catalogo conforme segundo baseada base estruturais estrutural estrutura estruturas cristalina cristalino sistema sistemas formula formulas ideal composicao quimica propriedades propriedade fisicas fisica caracteristicas caracteristica ocorrencia ocorrencias formacao ambiente ambientes dureza densidade cor cores onde ocorre ocorrem encontrar encontrados encontrada encontrada explique explicacao resumida resumo saber quero pode poderia poderia detalhar descreva descrever detalhes conte conteudo sobre x caracteristicas referente referentes'.split())
PROPERTY=re.compile(r'\b(formula|estrutura|estrutural|cristalin[oa]|composicao|quimica|propriedades|caracteristicas|ocorrencia|ocorre|ocorrem|onde|formacao|ambiente|dureza|densidade|cor)\b')

def catalog_sources(index,question):
 normalized=' '+' '.join(words(question))+' '
 normalized=normalized.replace(' argilomienerais ',' argilominerais ')
 # Classification and label questions stay in the authoritative vocabulary.
 if re.search(r'\b(ingles|identificador|categoria|especie ou|pertence|qual grupo|qual familia|nome preferido)\b',normalized):return []
 with closing(connect(index)) as conn:
  rows=conn.execute("SELECT * FROM docs WHERE json_type(metadata,'$.catalog_profile')='object' ORDER BY id").fetchall()
 profiles={}
 for row in rows:
  meta=json.loads(row['metadata']);profile=meta.get('catalog_profile')
  if not isinstance(profile,dict) or not meta.get('record_id') or meta.get('access')!='public':continue
  profiles.setdefault(meta['record_id'],(row,meta,profile))
 aliases=[]
 for rid,(_,_,p) in profiles.items():
  for value in [p.get(k,'') for k in ('slug','nome_pt','nome_en','nome_cientifico_padronizado')]+p.get('aliases',[]):
   alias=' '.join(words(value))
   if alias:aliases.append((alias,rid))
 grouped={}
 for alias,rid in set(aliases):grouped.setdefault(alias,[]).append(rid)
 matched=[];remaining=normalized
 for alias,ids in sorted(grouped.items(),key=lambda r:(-len(r[0]),r[0])):
  token=' '+alias+' '
  if token in remaining:
   exact=[rid for rid in ids if profiles[rid][2]['slug']==alias]
   ids=exact or sorted(ids)
   if len(ids)!=1:return []
   matched.append((normalized.find(token),ids[0]));remaining=remaining.replace(token,' ')
 general=not matched and ' argilominerais ' in remaining
 if general:remaining=remaining.replace(' argilominerais ',' ')
 if set(words(remaining))-(QUESTION_WORDS|EXTRA):return []
 if general:
  ids=[]
  for slug in ('kaolinite','illite','montmorillonite'):
   ids += [rid for rid,(_,_,p) in profiles.items() if p['slug']==slug]
 else:ids=list(dict.fromkeys(rid for _,rid in sorted(matched)))
 if not 1<=len(ids)<=3:return []
 if not general and not (PROPERTY.search(normalized) or re.search(r'\b(o que|what is|what are|explique|explicar|defina|definicao|descreva|resumo|ficha|catalogo|compare|diferenca)\b',normalized)):return []
 sources=[]
 for rid in ids:
  row,meta,p=profiles[rid]
  excerpt='Ficha do catálogo: '+p.get('nome_pt',row['title'])+'. '+p.get('descricao_curta','')
  if len(excerpt)>6000:excerpt=excerpt[:5900]
  sources.append({'document_id':'catalog:'+rid,'title':p.get('nome_pt',row['title']),
    'excerpt':excerpt,'tipo_fonte':'registro_invenio','record_id':rid,'updated':meta['updated'],
    'sha256':meta['sha256'],'catalog_slug':p['slug'],
    'derivation':'indexed_mineral_catalog','source_relative_path':'records/'+rid+'.json'})
 return sources
