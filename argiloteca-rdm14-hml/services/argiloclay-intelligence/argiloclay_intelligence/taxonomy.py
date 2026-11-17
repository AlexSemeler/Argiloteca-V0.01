"""Read-only, exact vocabulary routing for bounded classification questions."""
import json
import re
from contextlib import closing
from .engine import connect
from .corpus import words

# Wording of classification/label questions, not scientific properties or uses.
QUESTION_WORDS = set('a o as os um uma uns umas e eh de da do das dos em no na nos nas que qual quais como me diga explique explicar defina definir definicao nome nomes chamado chamada conhecido conhecida preferido portugues ingles id identificador categoria classificacao classificado classificada especie especies mineral minerais mineralogico mineralogica grupo grupos familia familias serie series material materiais interestratificado interestratificados ou pertence pertencem faz parte amplo termo entre diferenca diferencas comparar compare comparacao forma maneira simples didatica didatico linguagem acessivel por favor este esse esta essa mineral argilomineral argilominerais sobre significado significa what is are explain simple terms difference between preferred name english portuguese identifier group species series family category classification'.split())


def vocabulary_sources(index, question):
    normalized = ' ' + ' '.join(words(question)) + ' '
    with closing(connect(index)) as conn:
        aliases = conn.execute('SELECT alias,canonical FROM aliases ORDER BY length(alias) DESC,alias').fetchall()
        matches = []
        remaining = normalized
        for row in aliases:
            token = ' ' + row['alias'] + ' '
            if token in remaining:
                matches.append((normalized.find(token), row['canonical']))
                remaining = remaining.replace(token, ' ')
        if set(words(remaining)) - QUESTION_WORDS:
            return []
        identifiers = list(dict.fromkeys(v for _,v in sorted(matches)))
        if not 1 <= len(identifiers) <= 2:
            return []
        sources = []
        for identifier in identifiers:
            row = conn.execute("SELECT * FROM docs WHERE json_extract(metadata,'$.tipo_fonte')='vocabulario' AND json_extract(metadata,'$.term_id')=? ORDER BY id LIMIT 1",(identifier,)).fetchone()
            if row:
                sources.append({'document_id':row['id'],'title':row['title'],'excerpt':row['text'],**json.loads(row['metadata'])})
        # The family's readable label has its own independently cited source.
        for source in list(sources):
            family = source.get('family')
            if not family or any(s.get('term_id')==family for s in sources):continue
            row=conn.execute("SELECT * FROM docs WHERE json_extract(metadata,'$.vocabulary')='grupo_mineralogico' AND json_extract(metadata,'$.term_id')=? LIMIT 1",(family,)).fetchone()
            if row and len(sources)<4:
                sources.append({'document_id':row['id'],'title':row['title'],'excerpt':row['text'],**json.loads(row['metadata'])})
    return sources
