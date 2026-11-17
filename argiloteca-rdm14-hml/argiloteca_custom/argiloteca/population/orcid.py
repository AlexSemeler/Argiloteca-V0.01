"""Reviewed ORCID additions to source previews, never to raw collection files."""
from copy import deepcopy
from datetime import datetime, timezone
import json

from invenio_db import db
from ..openalex.adapters import digest
from ..openalex.analytics import connect, path_for
from ..openalex.models import OpenAlexJob
from ..openalex.orcid import add_identifier, normalize_orcid
from ..openalex.preview import file_hash, iter_records


def checked_analysis(analysis):
    if not analysis or analysis.kind != 'stats_scan' or analysis.state != 'completed' or file_hash(path_for(analysis.id)) != analysis.snapshot.get('sha256'):
        raise ValueError('Retrato alterado ou indisponível. Atualize as estatísticas.')


def prepare(job):
    p = job.params; analysis = db.session.get(OpenAlexJob, p['analysis']); checked_analysis(analysis)
    orcid = normalize_orcid(p.get('orcid'))
    if not orcid: raise ValueError('ORCID inválido.')
    with connect(analysis) as c:
        row = c.execute('''SELECT a.*,r.review,r.row_key,r.payload FROM p_authors a
                           JOIN p_records r ON r.id=a.record WHERE a.key=? AND r.kind='recovered' AND r.conflict=0''', (p['key'],)).fetchone()
        if not row or not row['review']: raise ValueError('Prepare a revisão do lote e atualize o retrato antes de vincular ORCID.')
        creator = json.loads(row['creator']); source = db.session.get(OpenAlexJob, row['review'])
        if not source or source.kind not in ('prepare', 'pan_prepare', 'men_prepare', 'oai_prepare') or source.state != 'review':
            raise ValueError('Revisão de origem indisponível.')
        selected = list(iter_records(source.snapshot, {row['row_key']}))
        if len(selected) != 1 or digest(selected[0]['payload']) != digest(json.loads(row['payload'])):
            raise ValueError('A revisão não corresponde ao retrato. Atualize as estatísticas.')
        payload = selected[0]['payload']; creators = payload['metadata']['creators']
        if row['slot'] >= len(creators) or creators[row['slot']] != creator:
            raise ValueError('A posição do autor diverge da revisão.')
        evidence = p.get('evidence_job')
        if evidence:
            lookup = db.session.get(OpenAlexJob, evidence)
            if not lookup or lookup.kind not in ('orcid_lookup', 'orcid_search') or lookup.actor != job.actor or lookup.state != 'review' or lookup.params.get('population_key') != p['key'] or lookup.params.get('analysis') != analysis.id:
                raise ValueError('Consulta ORCID não corresponde a esta ocorrência.')
            candidate = next((x for x in lookup.snapshot.get('candidates', []) if x['orcid'] == orcid), None)
            if not candidate: raise ValueError('ORCID ausente da consulta revisada.')
            evidence = {'source': 'ORCID', 'job': lookup.id, 'candidate': candidate}
        else:
            existing = [normalize_orcid(x.get('identifier')) for x in creator['person_or_org'].get('identifiers', []) if x.get('scheme') == 'orcid']
            if existing != [orcid]: raise ValueError('Consulte o perfil ORCID antes de propor este vínculo.')
            evidence = {'source': 'Identificador declarado na fonte', 'orcid': orcid}
        after = add_identifier(creators, [row['slot']], orcid)
        job.snapshot = {'schema': 1, 'analysis': analysis.id, 'key': p['key'], 'name': row['name'], 'orcid': orcid,
                        'source_job': source.id, 'source_params_sha': digest(source.params), 'row_key': row['row_key'],
                        'payload_sha': digest(payload), 'before_creators': creators, 'after_creators': after, 'evidence': evidence}
        job.state = 'review'


def revised_job(preview, actor, note):
    plan = preview.snapshot
    source = db.session.get(OpenAlexJob, plan['source_job'])
    if preview.kind != 'pop_orcid_preview' or preview.state != 'review' or preview.actor != actor or not source or source.state != 'review' or digest(source.params) != plan['source_params_sha']:
        raise ValueError('Prévia inválida ou revisão alterada. Prepare novamente.')
    checked_analysis(db.session.get(OpenAlexJob, plan['analysis']))
    rows = list(iter_records(source.snapshot, {plan['row_key']}))
    if len(rows) != 1 or digest(rows[0]['payload']) != plan['payload_sha']:
        raise ValueError('Payload de origem alterado. Prepare novamente.')
    params = deepcopy(source.params)
    params.setdefault('corrections', {}).setdefault(plan['row_key'], {})['creators'] = deepcopy(plan['after_creators'])
    params['population_orcid_review'] = {'preview': preview.id, 'actor': actor, 'at': datetime.now(timezone.utc).isoformat(), 'note': note, 'plan_sha256': digest(plan)}
    return OpenAlexJob(kind=source.kind, actor=actor, params=params)
