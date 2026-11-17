"""Persistent RAW/record associations. Similarity never establishes provenance.

Only anonymous identifiers and derivative hashes enter these tables. Original
identities remain in the private lifecycle map, outside public metadata.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import re

from flask import abort, current_app, g
from invenio_db import db
from invenio_rdm_records.proxies import current_rdm_records_service as service
from sqlalchemy import text

PID = re.compile(r'[a-z0-9]{5}-[a-z0-9]{5}')
ENGINE = 'argiloteca-record-drx-v3.1-20261020'
FIELD = 'arg:pacotes_analiticos'


def native_records_available():
    """The SQL association layer requires native Invenio record services."""
    return 'invenio-rdm-records' in current_app.extensions


def has_persisted_links(pid):
    return native_records_available() and DRXRecordLink.query.filter_by(record_id=pid).first() is not None


class DRXRecordLink(db.Model):
    __tablename__ = 'argiloteca_drx_record_link'
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.String(32), nullable=False, index=True)
    raw_id = db.Column(db.String(24), nullable=False, index=True)
    sha256 = db.Column(db.String(64), nullable=False)
    state = db.Column(db.String(24), nullable=False)  # pending / confirmed / removed
    evidence = db.Column(db.String(500), nullable=False)
    actor = db.Column(db.String(80), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    updated = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('record_id', 'raw_id'),)


class DRXAnalysisRevision(db.Model):
    __tablename__ = 'argiloteca_drx_analysis_revision'
    id = db.Column(db.Integer, primary_key=True)
    raw_id = db.Column(db.String(24), nullable=False, index=True)
    sha256 = db.Column(db.String(64), nullable=False)
    engine = db.Column(db.String(80), nullable=False)
    result = db.Column(db.JSON, nullable=False)
    created = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('raw_id', 'sha256', 'engine'),)


class DRXLinkEvent(db.Model):
    __tablename__ = 'argiloteca_drx_link_event'
    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.String(32), nullable=False, index=True)
    raw_id = db.Column(db.String(24), nullable=False)
    before = db.Column(db.JSON, nullable=True)
    after = db.Column(db.JSON, nullable=False)
    actor = db.Column(db.String(80), nullable=False)
    created = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


def install_tables():
    """Explicit additive migration; never recreate native tables."""
    for model in (DRXRecordLink, DRXAnalysisRevision, DRXLinkEvent):
        model.__table__.create(db.engine, checkfirst=True)


def record_for(identity, pid, *, write=False):
    if not PID.fullmatch(str(pid)):
        raise ValueError('invalid_record_id')
    from invenio_pidstore.errors import PIDDoesNotExistError
    from invenio_records_resources.services.errors import PermissionDenied
    try:
        result = service.read(identity, pid)
    except (PIDDoesNotExistError, PermissionDenied):
        abort(404)
    if write:
        try:
            service.require_permission(identity, 'edit', record=result._record)
        except PermissionDenied:
            abort(403)
    return result


def link_dict(link):
    return {k: getattr(link, k) for k in ('record_id', 'raw_id', 'sha256', 'state', 'evidence', 'revision')}


def set_link(identity, row, pid, *, state, evidence, expected_revision, actor):
    """Caller must enforce full administration permission and CSRF.

    Revision zero means create-only. Existing evidence cannot be overwritten by
    a stale form. The caller synchronizes native metadata in the same transaction.
    """
    if db.engine.dialect.name=='postgresql':
        db.session.execute(text('SELECT pg_advisory_xact_lock(1847331023)'))
    if state!='removed':
        from .raw_removal import retired
        if row['id'] in retired(fresh=True):raise ValueError('raw_retired')
    record_for(identity, pid, write=True)
    if state not in {'pending', 'confirmed', 'removed'} or not 5 <= len(evidence.strip()) <= 500:
        raise ValueError('curatorial_evidence_required')
    link = DRXRecordLink.query.filter_by(record_id=pid, raw_id=row['id']).with_for_update().one_or_none()
    before = link_dict(link) if link else None
    if (link.revision if link else 0) != expected_revision:
        raise ValueError('link_revision_conflict')
    if link and link.sha256 != row['sha256']:
        raise ValueError('raw_integrity_conflict')
    if link is None:
        link = DRXRecordLink(record_id=pid, raw_id=row['id'], sha256=row['sha256'], revision=1)
        db.session.add(link)
    else:
        link.revision += 1
    link.state, link.evidence, link.actor = state, evidence.strip(), str(actor)
    link.updated = datetime.now(timezone.utc)
    db.session.flush()
    db.session.add(DRXLinkEvent(record_id=pid, raw_id=row['id'], before=before,
                               after=link_dict(link), actor=str(actor)))
    return link


def visible_links(row, *, include_pending=False):
    """Resolve access on every request; a public RAW does not make its record public."""
    links = DRXRecordLink.query.filter_by(raw_id=row['id'], sha256=row['sha256']).all()
    output = []
    for link in links:
        if link.state == 'removed' or (not include_pending and link.state != 'confirmed'):
            continue
        cache = g.setdefault('drx_accessible_records', {})
        if link.record_id not in cache:
            try:
                cache[link.record_id] = record_for(g.identity, link.record_id)._record['metadata']['title']
            except Exception:
                cache[link.record_id] = None
        if cache[link.record_id] is None:
            continue
        output.append(dict(link_dict(link), title=cache[link.record_id],
            record_url='/records/' + link.record_id, package_url='/analises/' + link.record_id))
    return output


def analysis_for(row):
    revision = DRXAnalysisRevision.query.filter_by(raw_id=row['id'], sha256=row['sha256'], engine=ENGINE).one_or_none()
    return deepcopy(revision.result) if revision else None


def item_payload(row, *, link=None, include_pending=False):
    result = analysis_for(row)
    primary = result.get('primary', {}) if result else {}
    prep = {'N': 'natural', 'G': 'glicolado', 'C': 'calcinado', 'X': 'indeterminado'}[row['preparation']]
    links = visible_links(row, include_pending=include_pending)
    confirmed = next((x for x in links if x['state'] == 'confirmed'), None)
    return dict(id='linked:' + row['id'], diffractogram_id='linked:' + row['id'],
        raw_id=row['id'], source='snapshot_geral_raw', filename=row['filename'],
        sample_code=row['sample_code'], sample_base=row['sample_code'], preparation=prep,
        status='ok' if row['curve_available'] else 'error', access=row['access'],
        raw_sha256=row['sha256'], record_links=links, record_id=confirmed['record_id'] if confirmed else None,
        link_state=link.state if link else None,
        mineral_candidates=primary.get('candidates', row.get('candidates', [])),
        detected_peaks=primary.get('peaks', []),
        metadata=dict(points=row['points'], wavelength_angstrom=row.get('wavelength_angstrom'),
            classification_revision=ENGINE if result else 'historical_frozen',
            classification_policy='candidates_require_curation'),
        download_url='/scientific/drx/raws/' + row['id'] + '/download')


def record_package(pid, args, *, private=False):
    from .admin_raw_views import store
    record_for(g.identity, pid)
    links = DRXRecordLink.query.filter_by(record_id=pid).filter(DRXRecordLink.state != 'removed').all()
    rows = {r['id']: r for r in store().rows()}
    valid = [(link, rows[link.raw_id]) for link in links
             if link.raw_id in rows and link.sha256 == rows[link.raw_id]['sha256']]
    available = [(link, row) for link, row in valid if private or
                 (link.state == 'confirmed' and row['access'] == 'public_snapshot')]
    q = str(args.get('q') or '').casefold()[:100]
    prep = args.get('preparation') or ''
    mineral = str(args.get('argilomineral') or args.get('mineral') or '').casefold()
    names = {'N': 'natural', 'G': 'glicolado', 'C': 'calcinado', 'X': 'indeterminado'}
    filtered = [(link, row) for link, row in available if (not prep or names[row['preparation']] == prep) and
                (not q or q in (row['filename'] + ' ' + str(row['candidates'])).casefold())]
    if mineral:
        filtered = [(link, row) for link, row in filtered if mineral in
                    str((analysis_for(row) or {}).get('primary', {}).get('candidates', row['candidates'])).casefold()]
    limit = max(1, min(500, int(args.get('limit', 100)))); offset = max(0, int(args.get('offset', 0)))
    page = [item_payload(row, link=link, include_pending=private) for link, row in filtered[offset:offset+limit]]
    summary = dict(raw_files_total=len(valid), pending_links=sum(l.state == 'pending' for l, r in valid),
                   restricted_files=sum(r['access'] != 'public_snapshot' for l, r in valid),
                   visible_files=len(available))
    return dict(success=True, exists=bool(links), record_id=pid, analysis_type='drx',
        source={'type': 'persisted_anonymous_drx_links', 'policy': 'curation_required'},
        summary=summary, meta=summary, items=page,
        filters={'treatment': sorted({names[r['preparation']] for l, r in filtered})},
        pagination={'total': len(filtered), 'limit': limit, 'offset': offset, 'returned': len(page)})


def metadata_bundle(pid, rows):
    """Public allowlist: pending/restricted associations export counts, never file details."""
    links = DRXRecordLink.query.filter_by(record_id=pid).all()
    valid = [(l, rows[l.raw_id]) for l in links if l.state != 'removed' and
             l.raw_id in rows and l.sha256 == rows[l.raw_id]['sha256']]
    public = [(l, r) for l, r in valid if l.state == 'confirmed' and r['access'] == 'public_snapshot']
    current = DRXAnalysisRevision.query.filter_by(engine=ENGINE).filter(
        DRXAnalysisRevision.raw_id.in_([r['id'] for l, r in valid])).all()
    identities = {(r['id'], r['sha256']) for l, r in valid}
    current = [revision for revision in current if (revision.raw_id, revision.sha256) in identities]
    timestamps = [l.updated for l in links] + [revision.created for revision in current]
    return dict(pacote_id='drx-links-' + pid, record_id=pid, analysis_type='drx',
        generated_at=max((timestamp.replace(tzinfo=timezone.utc).isoformat() for timestamp in timestamps),
                         default=datetime.now(timezone.utc).isoformat()),
        versao_processamento=ENGINE, source={'type': 'persisted_anonymous_drx_links'},
        summary={'files': len(valid), 'public_files': len(public),
                 'restricted_files': sum(r['access'] != 'public_snapshot' for l, r in valid),
                 'pending_links': sum(l.state == 'pending' for l, r in valid),
                 'reprocessed_files': len(current),
                 'interpretation': 'computational_candidates_not_confirmed_identification'},
        items=[public_drx_metadata(l, r) for l, r in public])


def public_drx_metadata(link, row):
    """Allowlist matching arg_drx: scientific values without private paths/identities."""
    result = analysis_for(row) or {}
    primary, pilot = result.get('primary', {}), result.get('pilot', {})
    item = dict(analise_id='drx-' + row['id'], codigo_amostra=row['sample_code'],
        arquivo_raw=row['filename'], raw_sha256=row['sha256'], formato_raw=row.get('format', ''),
        preparo=row['preparation'], numero_pontos=row['points'],
        versao_processamento=result.get('engine', 'historical_frozen'),
        wavelength_angstrom=result.get('wavelength_angstrom', row.get('wavelength_angstrom')),
        axis_provenance=result.get('axis_provenance') or 'see_file_acquisition_metadata',
        primary_status=primary.get('status', 'historical_frozen_not_recomputed'),
        vinculo={'record_id': link.record_id, 'state': link.state, 'revision': link.revision},
        curva_url='/api/argiloteca/drx/difratogramas/linked:' + row['id'],
        arquivo_url='/scientific/drx/raws/' + row['id'] + '/download',
        picos=[{'two_theta': p['two_theta'], 'd_spacing': p.get('d'), 'intensidade': p.get('intensity')}
               for p in primary.get('peaks', [])],
        minerais_candidatos=[{'mineral': c['mineral'], 'score': c.get('score'),
                             'evidencia': 'computational_candidate_not_confirmed'}
                            for c in primary.get('candidates', [])],
        evidencias_estruturais={'mode': 'shadow', 'status': pilot.get('status', 'not_recomputed'),
            'rule_id': pilot.get('rule_id'),
            'candidates': [{k: c.get(k) for k in ('mineral_name','score','source','source_id','source_url')}
                           for c in pilot.get('candidates', [])]},
        observacoes='Automatic candidates are not confirmed identification or phase percentages. Original classifications preserved.')
    from .models import validator
    validator('arg_drx.schema.json').validate(item)
    return item


def sync_metadata(identity, pid, rows):
    """Narrow maintenance update of existing metadata, using native commit/signals.

    No service.publish, files, curated interpretations or draft changes. Native
    revision and updated timestamp advance. Index after the SQL transaction.
    """
    record = record_for(identity, pid, write=True)._record
    # Serialize maintenance with native edits and load the latest SQL revision
    # after obtaining the row lock; never overwrite unrelated concurrent edits.
    record.model.__class__.query.filter_by(id=record.id).with_for_update().one()
    db.session.expire(record.model)
    record = service.record_cls.get_record(record.id)
    fields = deepcopy(record.get('custom_fields', {}))
    others = [p for p in fields.get(FIELD, []) if p.get('pacote_id') != 'drx-links-' + pid]
    bundle = metadata_bundle(pid, rows)
    from .models import validator
    validator('arg_pacote_analitico.schema.json').validate(bundle)
    if fields.get(FIELD) == others + [bundle]:
        return record
    fields[FIELD] = others + [bundle]
    record['custom_fields'] = fields
    record.commit()
    return record
