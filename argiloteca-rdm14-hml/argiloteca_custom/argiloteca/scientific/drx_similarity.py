"""Measured-curve retrieval, separate from mineral identification and curation."""
from functools import lru_cache
import hashlib
import json

import numpy as np
from argiloteca_drx_core.raw_recovery import read_recoverable_pattern

# q = 1/d, Å^-1. Interpolate only on measured overlap; no automatic shift,
# stretch, extrapolation or inferred radiation. Scores are retrieval indicators.
GRID = np.linspace(0.015, 0.8, 4096)


def vector(x, y, wavelength):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (len(x) < 10 or len(x) != len(y) or not np.isfinite(x).all() or not np.isfinite(y).all()
            or not np.all(np.diff(x) > 0) or not np.all((x > 0) & (x < 180))
            or not wavelength or not np.isfinite(wavelength) or wavelength <= 0):
        raise ValueError('declared_monotonic_two_theta_and_wavelength_required')
    q = 2 * np.sin(np.deg2rad(x / 2)) / wavelength
    covered = (GRID >= q[0]) & (GRID <= q[-1])
    v = np.interp(GRID, q, y)
    baseline = np.percentile(v[covered], 10) if covered.any() else 0
    v = np.maximum(v - baseline, 0)
    v[~covered] = 0
    return v, covered


@lru_cache(maxsize=12000)
def _cached_curve(library, uploads, raw_id, sha256):
    from .admin_raw_store import AdminRawStore
    repository = AdminRawStore(library, uploads)
    row = repository.get(raw_id)
    if row['sha256'] != sha256:
        raise ValueError('raw_integrity_conflict')
    content = repository.content(row)
    curve = read_recoverable_pattern(content)
    wave = curve.metadata.get('wavelength_angstrom')
    if curve.metadata.get('axis_kind') != 'two_theta_degrees':
        raise ValueError('unverified_axis')
    v, mask = vector(curve.x, curve.intensity, wave)
    return v, mask


def compare_library(record_id, *, raw_sha256=None, metadata=None, two_theta=None,
                    intensity=None, limit=5, global_package_scan=True, **unused):
    from flask import g
    from flask_babel import get_locale
    from .admin_raw_views import store
    from .restricted_review import can_review
    from .drx_links import DRXRecordLink, item_payload, record_for
    repository = store()
    rows = repository.rows()
    selected_ids = set()
    if record_id:
        record_for(g.identity, record_id)
        selected_ids = {l.raw_id for l in DRXRecordLink.query.filter_by(record_id=record_id)
                        if l.state != 'removed'}
    private = can_review()
    rows = [r for r in rows if r['curve_available'] and
            ((global_package_scan and r['access'] == 'public_snapshot') or
             (r['id'] in selected_ids and (private or r['access'] == 'public_snapshot')))]
    meta = metadata or {}
    wave = meta.get('wavelength_angstrom') or meta.get('wavelength_A')
    try:
        incoming, incoming_mask = vector(two_theta, intensity, wave)
    except (ValueError, TypeError):
        incoming, incoming_mask = None, None
    ranked, skipped = [], 0
    for row in rows:
        exact = bool(raw_sha256 and raw_sha256 == row['sha256'])
        overlap, score = 0.0, None
        if exact:
            score = 1.0
        elif incoming is not None:
            try:
                candidate, mask = _cached_curve(str(repository.library), str(repository.uploads), row['id'], row['sha256'])
                shared = incoming_mask & mask
                overlap = float(shared.sum() / max(1, incoming_mask.sum()))
                if overlap < 0.6 or shared.sum() < 64:
                    skipped += 1
                    continue
                a, b = incoming[shared], candidate[shared]
                denom = float(np.linalg.norm(a) * np.linalg.norm(b))
                if denom <= 0:
                    skipped += 1
                    continue
                score = min(1.0, max(0.0, float(np.dot(a, b) / denom)))
            except (ValueError, OSError, KeyError):
                skipped += 1
        if score is not None:
            ranked.append((score, exact, overlap, row))
    ranked.sort(key=lambda x: (x[1], x[0], x[3]['id']), reverse=True)
    matches = []
    for score, exact, overlap, row in ranked[:max(1, min(10, limit))]:
        item = item_payload(row, include_pending=private)
        matches.append(dict(sample_code=row['sample_code'], filename=row['filename'],
            preparation=item['preparation'], diffractogram_id=item['id'], raw_id=row['id'],
            score=round(score, 6), curve_score=round(score, 6), exact=exact,
            shared_range_fraction=round(overlap, 4), record_links=item['record_links'],
            record_id=item['record_id'], record_url='/records/' + item['record_id'] if item['record_id'] else None,
            mineral_candidates=item['mineral_candidates'], source='anonymous_measured_raw_library',
            evidence=['sha256_identical' if exact else 'cosine_on_measured_reciprocal_spacing_overlap']))
    best = matches[0] if matches else None
    return dict(available=bool(matches), source='anonymous_measured_raw_library',
        status='igual' if best and best['exact'] else ('parecido' if best else 'requires_compatible_curve'),
        message=('Comparação de curvas medidas; similaridade não confirma mineralogia nem vínculo ao registro.'
                 if get_locale() and get_locale().language == 'pt' else
                 'Measured-curve comparison; similarity does not confirm mineralogy or record association.'),
        method='cosine_q_grid_4096_p10_baseline_overlap_0.6_no_axis_shift',
        wavelength_angstrom=wave, record_id=record_id, matches=matches, record_matches=matches,
        best_match=best, total_items_checked=len(rows), skipped_incompatible=skipped,
        global_package_scan=global_package_scan)
