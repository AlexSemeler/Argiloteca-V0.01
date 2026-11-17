"""Author/title/year lookup for already indexed, currently public literature."""
import json
import re
import sqlite3
from contextlib import closing
from .presentation import fold


def suggestions(library, language='pt'):
    """Bounded discovery of active public books, never pending upload metadata."""
    result=[]
    with closing(sqlite3.connect(library.index.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        ids=c.execute("SELECT DISTINCT json_extract(metadata,'$.library_id') FROM docs WHERE json_extract(metadata,'$.library_id') IS NOT NULL GROUP BY 1 ORDER BY length(title),title LIMIT 20").fetchall()
        for (doc,) in ids:
            row=c.execute("SELECT id,title,text,metadata FROM docs WHERE json_extract(metadata,'$.library_id')=? ORDER BY json_extract(metadata,'$.page'),id LIMIT 1",(doc,)).fetchone()
            source={'document_id':row[0],'title':row[1],'excerpt':row[2],**json.loads(row[3])}
            if not library.source_allowed(source):continue
            title=str(source.get('title',''))[:140]
            author=str(source.get('authors',''))[:80]
            year=str(source.get('year',''))[:4]
            reference=title+(' — '+author if author else '')+(' ('+year+')' if year else '')
            result.append(('Você conhece ' if language=='pt' else 'Do you know ')+reference+'?')
            if len(result)==1:break
    return result


def lookup(question, library):
    q=' '+' '.join(re.findall(r'\w+',fold(question)))+' '
    years=set(re.findall(r'\b(?:18|19|20)\d{2}\b',q))
    result=[]
    with closing(sqlite3.connect(library.index.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        # Only active public indexed literature is searchable here. Pending PDF
        # metadata cannot become public merely because an author was requested.
        books=c.execute("SELECT json_extract(metadata,'$.library_id'),title,json_extract(metadata,'$.authors'),json_extract(metadata,'$.year') FROM docs WHERE json_extract(metadata,'$.library_id') IS NOT NULL GROUP BY 1,2,3,4 LIMIT 200").fetchall()
        for doc,title,authors,year in books:
            names=[w for w in re.findall(r'\w+',fold(authors or '')) if len(w)>3]
            author=any(' '+w+' ' in q for w in names)
            book=' '+' '.join(re.findall(r'\w+',fold(title or '')))+' '
            if not (author or len(book.strip())>=4 and book in q):continue
            if years and str(year) not in years:continue
            row=c.execute("SELECT id,title,text,metadata FROM docs WHERE json_extract(metadata,'$.library_id')=? ORDER BY json_extract(metadata,'$.page'),id LIMIT 1",(doc,)).fetchone()
            source={'document_id':row[0],'title':row[1],'excerpt':row[2],**json.loads(row[3])}
            if library.source_allowed(source):result.append(source)
            if len(result)==3:break
    return result
