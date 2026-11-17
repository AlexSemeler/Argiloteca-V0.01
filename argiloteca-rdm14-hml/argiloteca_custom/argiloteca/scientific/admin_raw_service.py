"""New-trio classification only; frozen historical results are never rewritten."""
from datetime import datetime, timezone
import hashlib
import json
import math
import secrets

from argiloteca_drx_core.raw_recovery import anonymize_recoverable, read_recoverable_pattern
from argiloteca_drx_core.raw_lifecycle import anonymize_raw101
from argiloteca.drx.services.mineral_matcher import extract_peaks, match_reference, normalize_reference_payload, CU_KA1, SOURCE_SHA256
from argiloteca.drx.services.reference_pilot_v2_service import evaluate_reference_pilot_v2
from argiloteca.drx.services.reference_pilot_ngc_shadow_service import evaluate_reference_pilot_ngc_shadow

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_POINTS = 100000


def submit_trio(store, files, *, preparation_confirmed, actor, test_only=False):
    """Validate all three before creating any files; atomically append one submission."""
    if not preparation_confirmed or set(files) != {'N', 'G', 'C'}:
        raise ValueError('complete_confirmed_trio_required')
    code = 'ARC-' + secrets.token_hex(8).upper()
    rows, originals, derivatives, identity, parsed, ngc_files, fingerprints = [], {}, {}, [], {}, [], set()
    timestamp = datetime.now(timezone.utc).isoformat()
    test_only = bool(test_only or any(b'ARGILOTECA_SYNTHETIC_TEST_V1' in content[:1016] for _, content in files.values()))
    for role in 'NGC':
        original_name, content = files[role]
        if not original_name.lower().endswith('.raw') or not 0 < len(content) <= MAX_FILE_BYTES:
            raise ValueError('invalid_raw_or_size')
        anonymous, extension, curve = anonymize_recoverable(content, code, role)
        if content.startswith(b'RAW1.01'):
            # New compatible acquisitions use the same anonymous header contract
            # enforced by native publication; source and numerical bytes are preserved.
            anonymous = anonymize_raw101(content, code, role)
        if extension != '.raw' or curve.metadata['axis_kind'] != 'two_theta_degrees':
            raise ValueError('raw_two_theta_required')
        if not 10 <= len(curve.x) <= MAX_POINTS or not all(0 < x < 180 for x in curve.x):
            raise ValueError('curve_range_requires_review')
        wavelength = curve.metadata.get('wavelength_angstrom')
        if not wavelength or not math.isfinite(wavelength):
            raise ValueError('declared_wavelength_required')
        fingerprint = hashlib.sha256(json.dumps([curve.x, curve.intensity], separators=(',', ':')).encode()).hexdigest()
        if fingerprint in fingerprints:
            raise ValueError('duplicate_profiles')
        fingerprints.add(fingerprint)
        filename = code + '_' + role + extension
        digest = hashlib.sha256(anonymous).hexdigest()
        originals[role], derivatives[filename], parsed[role] = content, anonymous, curve
        identity.append({'role': role, 'original_filename': original_name[:255],
                         'original_sha256': hashlib.sha256(content).hexdigest(), 'derivative_sha256': digest})
        rows.append({'id': hashlib.sha256(filename.encode()).hexdigest()[:24], 'filename': filename,
            'sample_code': code, 'preparation': role, 'curve_available': True, 'access': 'restricted',
            'status': 'new_provisional', 'format': curve.metadata['detected_format'], 'points': len(curve.x),
            'wavelength_angstrom': wavelength, 'classified_at': timestamp, 'classification_status': 'pending',
            'candidates': [], 'classification_kind': 'new_provisional', 'sha256': digest, 'test_only': test_only})
        ngc_files.append({'treatment': role, 'content': anonymous})
    refs = normalize_reference_payload(json.loads((store.library / 'reference.json').read_text()), 'frozen_local_reference')['records']
    analysis = {'mode': 'shadow', 'policy': 'provisional_candidates_not_confirmation',
                'existing_classifications_modified': False, 'by_preparation': {}}
    for row in rows:
        role = row['preparation']; curve = parsed[role]; wave = row['wavelength_angstrom']
        # The frozen primary matcher assumes Cu. Do not silently run it on Co/other radiation.
        primary = {'status': 'not_applicable_wavelength', 'candidates': [], 'rule_sha256': SOURCE_SHA256}
        if abs(wave - CU_KA1) <= 0.0001:  # header precision around Cu Kα1, not a mineral tolerance
            peaks = extract_peaks(curve.x, curve.intensity, max_peaks=14)
            primary.update(status='evaluated', candidates=match_reference(peaks, refs), peaks=peaks)
        try:
            pilot = evaluate_reference_pilot_v2(curve.x, curve.intensity, wavelength_angstrom=wave,
                enabled=True, preparation=role, source_sha256=row['sha256'],
                corrections={'automatic_axis_offset': False, 'axis_rule': curve.metadata['axis_provenance']})
        except Exception:
            pilot = {'status': 'unavailable', 'candidates': [], 'rule_id': 'pilot-cosine-peak-evidence-v2'}
        row['candidates'] = primary['candidates']
        row['classification_status'] = 'evaluated' if primary['status'] == 'evaluated' else 'pilot_only'
        row['pilot_candidates'] = [{k: c.get(k) for k in ('mineral_name', 'score', 'source', 'source_id', 'source_url')}
                                   for c in pilot.get('candidates', [])]
        row['pilot_status'] = pilot.get('status')
        analysis['by_preparation'][role] = {'primary': primary, 'pilot': pilot}
    try:
        analysis['ngc'] = evaluate_reference_pilot_ngc_shadow(ngc_files, enabled=True)
    except ValueError:
        analysis['ngc'] = {'status': 'requires_review', 'family_context': [],
                           'reason': 'ngc_requires_supported_raw101_consistent_wavelength_and_protocol'}
    except Exception:
        analysis['ngc'] = {'status': 'unavailable', 'family_context': []}
    provenance = {'created_at': timestamp, 'actor_id': str(actor), 'preparation_confirmation': True,
                  'source_files': identity, 'record_publications': 0, 'sample_code': code, 'test_only': test_only}
    provenance['submission_fingerprint'] = hashlib.sha256(json.dumps(
        {r['role']:r['original_sha256'] for r in identity}, sort_keys=True).encode()).hexdigest()
    return store.commit_trio(code=code, rows=rows, originals=originals, derivatives=derivatives,
                             provenance=provenance, analysis=analysis)


def preview(store, item_id):
    row = store.get(item_id)
    curve = read_recoverable_pattern(store.content(row))
    # A bounded min/max envelope keeps narrow peaks visible in the browser.
    indices = {0, len(curve.x)-1}
    step = max(1, math.ceil(len(curve.x)/1500))
    for start in range(0, len(curve.x), step):
        end = min(len(curve.x), start+step)
        indices.add(min(range(start,end), key=lambda i: curve.intensity[i]))
        indices.add(max(range(start,end), key=lambda i: curve.intensity[i]))
    indices = sorted(indices)
    return {'filename': row['filename'], 'sample_code': row['sample_code'],
        'x': [curve.x[i] for i in indices], 'intensity': [curve.intensity[i] for i in indices],
        'original_points': len(curve.x), 'axis_kind': curve.metadata['axis_kind'],
        'wavelength_angstrom': curve.metadata.get('wavelength_angstrom'),
        'representation': 'min_max_envelope_no_axis_offset', 'classification_kind': row['classification_kind']}
