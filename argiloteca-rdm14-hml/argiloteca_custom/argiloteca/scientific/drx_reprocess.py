"""Append-only, radiation-aware classification revisions for linked anonymous RAWs."""
import hashlib
import json
import math

from argiloteca_drx_core.raw_recovery import read_recoverable_pattern
from argiloteca.drx.services.mineral_matcher import (
    extract_peaks, match_reference, normalize_reference_payload, CU_KA1, SOURCE_SHA256, two_theta_to_d,
)
from argiloteca.drx.services.reference_pilot_v2_service import evaluate_reference_pilot_v2
from .drx_links import DRXAnalysisRevision, ENGINE


def calculate(repository, row, references):
    content = repository.content(row)  # verifies derivative hash, never modifies bytes
    curve = read_recoverable_pattern(content)
    wave = curve.metadata.get('wavelength_angstrom')
    result = dict(engine=ENGINE, mode='shadow', source_sha256=row['sha256'],
        original_classification_preserved=True, axis_kind=curve.metadata.get('axis_kind'),
        axis_provenance=curve.metadata.get('axis_provenance'), wavelength_angstrom=wave,
        primary={'status': 'requires_declared_wavelength', 'candidates': [], 'rule_sha256': SOURCE_SHA256},
        pilot={'status': 'requires_declared_wavelength', 'candidates': []},
        ngc={'status': 'requires_complete_confirmed_trio'})
    if curve.metadata.get('axis_kind') != 'two_theta_degrees' or not wave or not math.isfinite(wave):
        return result
    peaks = extract_peaks(curve.x, curve.intensity, max_peaks=14)
    # The historical extractor calculates d with Cu. Preserve its positions and
    # intensities but recompute displayed d with the actual declared radiation.
    for peak in peaks:
        peak['d'] = round(two_theta_to_d(peak['two_theta'], wave), 5)
    result['primary'] = dict(status='not_applicable_wavelength', candidates=[], peaks=peaks, rule_sha256=SOURCE_SHA256)
    if abs(wave - CU_KA1) <= 0.0001:
        result['primary'].update(status='evaluated', candidates=match_reference(peaks, references))
    result['pilot'] = evaluate_reference_pilot_v2(curve.x, curve.intensity, wavelength_angstrom=wave,
        enabled=True, preparation=row['preparation'], source_sha256=row['sha256'],
        corrections={'automatic_axis_offset': False, 'axis_rule': curve.metadata.get('axis_provenance')})
    # Reject non-finite/non-JSON output before writing a revision.
    json.dumps(result, allow_nan=False)
    return result


def reprocess(repository, rows, *, progress=None):
    from invenio_db import db
    references = normalize_reference_payload(json.loads((repository.library / 'reference.json').read_text()),
                                             'frozen_local_reference')['records']
    summary = {'created': 0, 'reused': 0, 'failed': 0, 'primary_evaluated': 0, 'pilot_evaluated': 0,
               'wavelength_or_axis_review': 0}
    for index, row in enumerate(rows):
        previous = DRXAnalysisRevision.query.filter_by(raw_id=row['id'], sha256=row['sha256'], engine=ENGINE).one_or_none()
        if previous:
            summary['reused'] += 1
            result = previous.result
        else:
            try:
                result = calculate(repository, row, references)
            except (ValueError, OSError, KeyError) as error:
                summary['failed'] += 1
                # No fabricated classification and no incomplete revision saved.
                if progress:
                    progress(index + 1, len(rows), dict(summary))
                continue
            db.session.add(DRXAnalysisRevision(raw_id=row['id'], sha256=row['sha256'], engine=ENGINE, result=result))
            db.session.commit()
            summary['created'] += 1
        summary['primary_evaluated'] += result['primary']['status'] == 'evaluated'
        summary['pilot_evaluated'] += result['pilot']['status'] not in {'requires_declared_wavelength', 'unavailable'}
        summary['wavelength_or_axis_review'] += result['primary']['status'] == 'requires_declared_wavelength'
        if progress and (index % 25 == 0 or index == len(rows)-1):
            progress(index + 1, len(rows), dict(summary))
    return summary
