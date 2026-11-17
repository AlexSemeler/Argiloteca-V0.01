"""Fail closed before preparing any index for activation.

This command writes only an audit decision. It never modifies Compose, a
production index, application configuration, model parameters or records.
"""
import collections
import json
import math
from pathlib import Path

from model import CLASSES
from prepare import OUT, REPO, sha, write


def check_release():
    protocol = json.loads((OUT / 'protocol.json').read_text())
    evaluation = json.loads((OUT / 'evaluation.json').read_text())
    technical = json.loads((OUT / 'technical-validation.json').read_text())
    run = json.loads((OUT / 'quarantined-predictions.json').read_text())
    first = json.loads((OUT / 'training/model-manifest.json').read_text())
    repeated = json.loads((OUT / 'reproduction/model-manifest.json').read_text())
    inputs = json.loads((REPO / 'output/neural-reinference-20261023/input-manifest.json').read_text())
    baseline = REPO / 'output/neural-catalog-rag-20261023/public-neural/neural_evidence_index.json'
    expected = {row['diffractogram_id']: row for row in inputs['entries']}
    checks = dict(evaluation['scientific_gates'])
    checks.update({
        'training_reproduces_same_parameter_values': first['state_digest'] == repeated['state_digest'],
        'model_source_unchanged': sha(Path(__file__).with_name('model.py')) == protocol['inputs']['model_source_sha256'],
        'checkpoint_integrity': first['weights_sha256'] == sha(OUT / 'training/weights.pt'),
        'protocol_unchanged': first['protocol_sha256'] == evaluation['protocol_sha256'] == technical['protocol_sha256'] == sha(OUT / 'protocol.json'),
        'model_identity_consistent': first['model_id'] == evaluation['model_id'] == technical['model_id'],
        'no_target_curves_or_test_specimens_in_training': first['public_target_curves_used_in_training'] == first['measured_test_profiles_used_in_training'] == 0,
        'finite_and_reproducible_899': technical['target_curves'] == 899 and technical['finite_outputs'] and technical['exact_repeatability'],
        'batch_tolerance': technical['individual_batch_max_absolute_difference'] <= 1e-6 and technical['reloaded_reversed_batch_max_absolute_difference'] <= 1e-6,
        'parameters_unchanged_by_precision_fix': technical['trained_parameter_values_preserved'],
        'baseline_index_unchanged': sha(baseline) == inputs['historical_index_sha256'],
        'quarantine_not_production_schema': run['schema_version'] == 'argiloteca.drx.quarantined_neural_run.v1' and 'entries' not in run,
    })
    rows = run['results']
    checks['exact_unique_target_set'] = len(rows) == len(expected) == len({r['diffractogram_id'] for r in rows}) == 899 and set(expected) == {r['diffractogram_id'] for r in rows}
    checks['all_result_identities_and_scores_valid'] = all(
        row['source_sha256'] == expected[row['diffractogram_id']]['source_sha256']
        and row['weights_sha256'] == first['weights_sha256']
        and row['usage_policy'] == 'quarantined_auxiliary_not_confirmatory'
        and {r['label'] for r in row['ranking']} == set(CLASSES)
        and len(row['ranking']) == len(CLASSES)
        and all(math.isfinite(r['score']) and 0 <= r['score'] <= 1 for r in row['ranking'])
        and abs(sum(r['score'] for r in row['ranking']) - 1) < 1e-12
        for row in rows)
    text = (OUT / 'quarantined-predictions.json').read_text()
    checks['no_private_source_paths_in_predictions'] = '/Users/' not in text and 'source_curve' not in text
    report = {
        'schema_version': 'argiloteca.drx.neural_pilot_release_gate.v1', 'activation_allowed': all(checks.values()),
        'checks': checks, 'failed_checks': [name for name, passed in checks.items() if not passed],
        'model_id': first['model_id'], 'weights_sha256': first['weights_sha256'],
        'protocol_sha256': sha(OUT / 'protocol.json'), 'predictions_sha256': sha(OUT / 'quarantined-predictions.json'),
        'evaluation_sha256': sha(OUT / 'evaluation.json'),
        'inferences_executed': len(rows), 'production_deployment_performed': False,
        'action': 'eligible_for_separate_integration_validation' if all(checks.values()) else 'keep_quarantined_do_not_activate',
    }
    write(OUT / 'release-gate.json', report)
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == '__main__':
    report = check_release()
    raise SystemExit(0 if report['activation_allowed'] else 3)
