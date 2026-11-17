"""Shared filter semantics for the interface and CSV exports."""
from ..openalex.analytics import name_key
from .snapshot import SOURCES


def scope(c, filters):
    c.create_function('fold', 1, name_key)
    conditions = []; args = []
    if filters.get('source'):
        conditions.append('EXISTS(SELECT 1 FROM p_sources s WHERE s.record=r.id AND s.source=?)'); args.append(filters['source'])
    stage = filters.get('stage')
    if stage == 'published': conditions.append('r.published=1')
    elif stage == 'draft': conditions.append('r.draft=1 AND r.published=0')
    elif stage == 'editing': conditions.append('r.draft=1 AND r.published=1')
    elif stage == 'recovered': conditions.append("r.kind='recovered'")
    if filters.get('q'):
        conditions.append('instr(fold(r.title),?)>0'); args.append(name_key(filters['q']))
    if filters.get('year'):
        conditions.append('r.year=?'); args.append(filters['year'])
    return ' WHERE ' + ' AND '.join(conditions) if conditions else '', args


def summary(c, filters):
    where, args = scope(c, filters)
    row = c.execute('''SELECT count(*) total,sum(published) published,
        sum(draft=1 AND published=0) drafts,sum(draft=1 AND published=1) editing,
        sum(kind='recovered') recovered,sum(conflict) conflicts FROM p_records r''' + where, args).fetchone()
    result = {k: (v or 0) for k, v in zip(('total', 'published', 'drafts', 'editing', 'recovered', 'conflicts'), row)}
    sql = ' FROM p_authors a JOIN p_records r ON r.id=a.record' + where
    stats = c.execute("SELECT count(*),count(DISTINCT a.gid),sum(a.status='linked'),sum(a.status='missing'),sum(a.status='conflict'),count(DISTINCT CASE WHEN a.status='linked' THEN a.orcid END)" + sql, args).fetchone()
    result.update({k: (v or 0) for k, v in zip(('authors', 'name_groups', 'linked', 'missing', 'orcid_conflicts', 'profiles'), stats)})
    result['years'] = [dict(r) for r in c.execute('SELECT year,count(*) n FROM p_records r' + where + ' GROUP BY year ORDER BY year DESC', args)]
    result['types'] = [dict(r) for r in c.execute('SELECT type,count(*) n FROM p_records r' + where + ' GROUP BY type ORDER BY n DESC', args)]
    return result


def source_summary(c):
    result = []
    for source, label in SOURCES.items():
        row = summary(c, {'source': source})
        row.update({'id': source, 'label': label,
                    'lots': c.execute('SELECT count(*) FROM p_lots WHERE source=?', (source,)).fetchone()[0],
                    'observations': c.execute('SELECT count(*) FROM p_entries WHERE source=?', (source,)).fetchone()[0]})
        result.append(row)
    return result


def listing(c, filters, authors=False, limit=25, offset=0):
    where, args = scope(c, {**filters, 'q': ''} if authors else filters)
    if authors:
        conditions = []; extra = []
        if filters.get('q'):
            conditions.append('(instr(fold(a.name),?)>0 OR instr(a.orcid,?)>0)'); extra.extend([name_key(filters['q']), filters['q']])
        status = filters.get('status')
        if status in ('linked', 'missing', 'conflict'):
            conditions.append('a.status=?'); extra.append(status)
        if status == 'suggested':
            conditions.append('EXISTS(SELECT 1 FROM candidates ca WHERE ca.occurrence=a.native_key)')
        if conditions: where += (' AND ' if where else ' WHERE ') + ' AND '.join(conditions)
        args += extra
        base = ' FROM p_authors a JOIN p_records r ON r.id=a.record' + where
        selection = '''SELECT a.*,r.title,r.rid,r.kind,r.review,r.published,r.draft,r.conflict,
            (SELECT group_concat(source,', ') FROM p_sources WHERE record=r.id) sources'''
        order = ' ORDER BY a.name,r.title,a.slot'
    else:
        base = ' FROM p_records r' + where
        selection = "SELECT r.id,r.rid,r.kind,r.title,r.year,r.type,r.published,r.draft,r.conflict,r.review,(SELECT group_concat(source,', ') FROM p_sources WHERE record=r.id) sources"
        order = ' ORDER BY r.year DESC,r.title,r.id'
    total = c.execute('SELECT count(*)' + base, args).fetchone()[0]
    return [dict(row) for row in c.execute(selection + base + order + ' LIMIT ? OFFSET ?', [*args, limit, offset])], total
