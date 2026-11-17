"""Reviewed basic definitions grounded in currently approved AIPEA literature."""
import json,re,sqlite3
from contextlib import closing
from . import community_sources as cs


def kind(question):
    q=cs.normalize_question(question)
    if not cs.DEFINITION.search(q):return None
    words=set(re.findall(r'\w+',q))
    subjects={'argila','argilas','clay','clays','argilomineral','argilominerais','minerals','mineral'}
    if words-cs.GRAMMAR-subjects:return None
    clay=bool(words & {'argila','argilas','clay','clays'})
    mineral=bool(words & {'argilomineral','argilominerais','mineral','minerals'})
    return 'both' if clay and mineral and not re.search(r'\bclay minerals?\b',q) else 'minerals' if mineral else 'clays' if clay else None


def lookup(question,library):
    if not kind(question):return []
    result=[]
    # This is a reviewed nomenclature rule, not a definition inferred from an
    # arbitrary matching PDF. Withdrawal/version/page review is checked below.
    with closing(sqlite3.connect(library.index.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        for phrase in ('composed primarily of fine-grained','minerals which impart plasticity'):
            row=c.execute("SELECT id,title,text,metadata FROM docs WHERE title LIKE '%NOMENCLATURE COMMITTEE FOR 2006%' AND json_extract(metadata,'$.library_id') IS NOT NULL AND instr(lower(text),?)>0 ORDER BY id LIMIT 1",(phrase,)).fetchone()
            if not row:continue
            source={'document_id':row[0],'title':row[1],'excerpt':row[2],**json.loads(row[3])}
            if 'harden' not in source['excerpt'].lower() or not library.source_allowed(source):continue
            source['definition_rule']='aipea-2006-clay-v1' if phrase.startswith('composed') else 'aipea-2006-clay-mineral-v1'
            result.append(source)
    needed={'aipea-2006-clay-v1'} if kind(question)=='clays' else {'aipea-2006-clay-mineral-v1'} if kind(question)=='minerals' else {'aipea-2006-clay-v1','aipea-2006-clay-mineral-v1'}
    return result if needed.issubset({s['definition_rule'] for s in result}) else []


def answer(sources,question,language='pt',trend=''):
    subject=kind(question);en=language=='en';paragraphs=[]
    rules={s.get('definition_rule'):i for i,s in enumerate(sources,1) if s.get('library_id')}
    ref=lambda i:' ['+('Source' if en else 'Fonte')+' '+str(i)+']'
    if subject in ('clays','both'):
        i=rules.get('aipea-2006-clay-v1')
        if not i:return ''
        paragraphs.append(('Clays are natural materials composed mainly of fine-grained minerals. They are generally plastic at an appropriate water content and harden when dried or fired. Clay is a material, rather than the name of a single mineral.' if en else 'Argilas são materiais naturais compostos principalmente por minerais de granulação fina. Em geral, apresentam plasticidade com uma quantidade adequada de água e endurecem ao secar ou após a queima. Argila é um material, e não o nome de um único mineral.')+ref(i))
    if subject in ('minerals','both'):
        i=rules.get('aipea-2006-clay-mineral-v1')
        if not i:return ''
        paragraphs.append(('Clay minerals include phyllosilicate minerals and minerals that give clay plasticity and harden on drying or firing. Clay names the material; clay mineral names a mineral constituent. The concepts are related, but are not interchangeable.' if en else 'Argilominerais incluem os minerais filossilicatos e os minerais que conferem plasticidade à argila e endurecem após secagem ou queima. Argila designa o material; argilomineral designa um constituinte mineral. Os conceitos estão relacionados, mas não são sinônimos.')+ref(i))
    if not paragraphs:return ''
    # Retain original source positions for every community/record citation.
    context=cs.answer(sources,language,question='',trend=trend)
    if context:paragraphs.append(context)
    return '\n\n'.join(paragraphs)
