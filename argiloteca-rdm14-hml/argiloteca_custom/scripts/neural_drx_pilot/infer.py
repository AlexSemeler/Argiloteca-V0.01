"""Run the new checkpoint on 899 audited current-axis curves in quarantine.

This output deliberately is not the production index schema and cannot be
activated by configuring the web service's index path to this file.
"""
import collections
import hashlib
import json
from pathlib import Path
import struct
import time

import numpy as np

from model import CLASSES, MODEL_ID, RULE_ID, decision, deterministic, load_model, predict, state_digest
from model import preprocess
from prepare import OUT, REPO, sha, write
from inference_runtime import predict_stable


def infer():
    deterministic()
    protocol = json.loads((OUT / 'protocol.json').read_text())
    manifest_path = REPO / 'output/neural-reinference-20261023/input-manifest.json'
    assert sha(manifest_path) == protocol['inputs']['target_manifest_sha256']
    manifest = json.loads(manifest_path.read_text())
    baseline_path = REPO / 'output/neural-catalog-rag-20261023/public-neural/neural_evidence_index.json'
    baseline_hash = sha(baseline_path)
    assert baseline_hash == manifest['historical_index_sha256']
    baseline = json.loads(baseline_path.read_text())
    targets = {r['diffractogram_id'] for r in baseline['entries'] if r['status'] == 'historical_axis_mismatch'}
    assert len(targets) == len(manifest['entries']) == 899
    info = json.loads((OUT / 'training/model-manifest.json').read_text())
    assert info['protocol_sha256'] == sha(OUT / 'protocol.json')
    model = load_model(OUT / 'training/weights.pt', info['weights_sha256'])
    assert state_digest(model) == info['state_digest']
    import sys
    sys.path.insert(0, str(REPO / 'argiloteca-rdm14-hml/argiloteca_custom'))
    from argiloteca_drx_core.raw_lifecycle import parse_lifecycle_raw
    raw_dir = REPO / 'argiloteca-rdm14-hml/data/drx/lifecycle-v1-20261020/raw'
    values, metadata = [], []
    started = time.monotonic()
    for row in manifest['entries']:
        path = raw_dir / row['filename']
        assert sha(path) == row['source_sha256']
        parsed = parse_lifecycle_raw(path.read_bytes())
        canonical = b''.join(struct.pack('<dd', x, y) for x, y in zip(parsed.two_theta, parsed.intensity))
        assert hashlib.sha256(canonical).hexdigest() == row['numeric_float64_le_sha256']
        tensor, md = preprocess(parsed.two_theta, parsed.intensity, parsed.metadata['wavelength_angstrom'])
        values.append(tensor)
        metadata.append(md)
    values = np.asarray(values)
    preprocess_seconds = time.monotonic() - started
    # Keep the first float32 numerical failure visible, before using float64.
    original_scores = predict(model, values, batch_size=64)
    original_individual = predict(model, values, batch_size=1)
    original_difference = float(np.abs(original_scores - original_individual).max())
    write(OUT / 'float32-batch-validation.json', {
        'max_absolute_difference': original_difference, 'required_tolerance': 1e-6,
        'passed': original_difference <= 1e-6,
        'top1_changes': int((original_scores.argmax(1) != original_individual.argmax(1)).sum()),
        'correction': 'float64 arithmetic for inference only; trained float32 parameter values preserved exactly',
    })
    tick = time.monotonic()
    scores = predict_stable(model, values, batch_size=64)
    elapsed = time.monotonic() - tick
    repeated = predict_stable(model, values, batch_size=64)
    assert np.array_equal(scores, repeated), 'Repeated deterministic inference changed'
    individual = predict_stable(model, values, batch_size=1)
    batch_difference = float(np.abs(scores - individual).max())
    assert batch_difference <= 1e-6
    # Check a new safe checkpoint load and reversed order, guarding row association.
    reloaded = load_model(OUT / 'training/weights.pt', info['weights_sha256'])
    reverse = predict_stable(reloaded, values[::-1].copy(), batch_size=32)[::-1]
    reverse_difference = float(np.abs(scores - reverse).max())
    assert reverse_difference <= 1e-6
    results = []
    for row, md, distribution in zip(manifest['entries'], metadata, scores):
        order = np.argsort(-distribution, kind='stable')
        results.append({
            'diffractogram_id': row['diffractogram_id'], 'filename': row['filename'],
            'source_sha256': row['source_sha256'], 'numeric_float64_le_sha256': row['numeric_float64_le_sha256'],
            'model_id': MODEL_ID, 'rule_id': RULE_ID, 'weights_sha256': info['weights_sha256'],
            'preprocessing': md, 'decision': decision(distribution, md['coverage_fraction'], protocol),
            'ranking': [{'label': CLASSES[int(i)], 'score': float(distribution[i]), 'rank': rank + 1}
                        for rank, i in enumerate(order)],
            'usage_policy': 'quarantined_auxiliary_not_confirmatory',
        })
    assert {r['diffractogram_id'] for r in results} == targets
    assert sha(baseline_path) == baseline_hash
    assert all(sha(raw_dir / row['filename']) == row['source_sha256'] for row in manifest['entries'])
    report = {
        'model_id': MODEL_ID, 'target_curves': len(results), 'finite_outputs': True,
        'exact_repeatability': True, 'individual_batch_max_absolute_difference': batch_difference,
        'reloaded_reversed_batch_max_absolute_difference': reverse_difference,
        'preprocess_seconds': round(preprocess_seconds, 6), 'inference_seconds': round(elapsed, 6),
        'mean_inference_milliseconds_per_curve': elapsed * 1000 / len(results),
        'decision_counts': dict(collections.Counter(r['decision']['status'] for r in results)),
        'first_candidate_counts': dict(collections.Counter(r['decision']['first'] for r in results)),
        'source_raws_unchanged': True, 'historical_index_unchanged': True,
        'preserved_historical_entries': 325, 'production_modified': False,
        'weights_sha256': info['weights_sha256'], 'protocol_sha256': sha(OUT / 'protocol.json'),
        'inference_dtype': 'float64', 'inference_runtime_sha256': sha(Path(__file__).with_name('inference_runtime.py')),
        'trained_parameter_values_preserved': state_digest(model) == info['state_digest'],
        'float32_to_float64_max_absolute_difference': float(np.abs(scores - original_scores).max()),
        'float32_to_float64_top1_changes': int((scores.argmax(1) != original_scores.argmax(1)).sum()),
        'float32_to_float64_decision_changes': sum(decision(a, md['coverage_fraction'], protocol)['status'] != decision(b, md['coverage_fraction'], protocol)['status']
                                                 for a, b, md in zip(scores, original_scores, metadata)),
    }
    write(OUT / 'quarantined-predictions.json', {'schema_version': 'argiloteca.drx.quarantined_neural_run.v1',
          'deployment_eligible': False, 'technical_validation': report, 'results': results})
    write(OUT / 'technical-validation.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    infer()
