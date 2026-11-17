"""Freeze a reference-only training protocol before inspecting predictions."""
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from model import CLASSES, GRID, MODEL_ID, RULE_ID, SEED

REPO = Path(__file__).resolve().parents[4]
OUT = REPO / "output/neural-replacement-20261023"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / 'protocol.json').exists():
        raise RuntimeError("Frozen protocol already exists; use its recorded version instead of overwriting")
    reference_path = REPO / 'argiloteca-rdm14-hml/argiloteca_custom/argiloteca/data/reference_pilot_v1.json'
    references = json.loads(reference_path.read_text())['references']
    unique = {}
    for row in references:
        unique.setdefault(row['structure_group'], row)
    assert len(unique) == 10
    training = [unique[key] for key in sorted(unique)]
    assert {row['mineral_id'] for row in training} == set(CLASSES) - {'unknown'}
    measured = {}
    exclusions = []
    old_manifest = REPO / 'argiloteca-rdm14-hml/argiloteca_custom/argiloteca/static/data/rruff_odr_argilominerais_20260619/rruff_odr_curves_manifest.json'
    candidates = [(Path('/Users/alexandresemeler/argilas') / row['local_path'], row['sha256'])
                  for row in json.loads(old_manifest.read_text()) if row['file_type'] == 'raw_xy']
    base = REPO / 'output/reference-evaluation-20261020'
    candidates += [(base / row['relative_path'], row['sha256'])
                   for row in json.loads((base / 'corpus-manifest.json').read_text())]
    for path, expected in candidates:
        content = path.read_bytes()
        assert sha(path) == expected
        headers = {line[2:].split('=', 1)[0]: line.split('=', 1)[1]
                   for line in content.decode().splitlines() if line.startswith('##') and '=' in line}
        key = headers['RRUFFID']
        if key in measured:
            assert measured[key]['sha256'] == expected, 'Multiple profiles per specimen require an explicit grouping policy'
            continue
        name = headers['NAMES'].strip().lower()
        status = headers.get('STATUS', '').lower()
        description = headers.get('DIFFRACTION SAMPLE DESCRIPTION', '').lower()
        if 'calculated' in description or 'unconfirmed' in status or 'not yet confirmed' in status:
            exclusions.append({'sample_id': key, 'mineral': name, 'reason': 'calculated_or_unconfirmed', 'sha256': expected})
            continue
        if 'chemical analysis' in status and 'only by chemical' in status:
            exclusions.append({'sample_id': key, 'mineral': name, 'reason': 'no_diffraction_confirmation', 'sha256': expected})
            continue
        if 'diffraction' not in status:
            exclusions.append({'sample_id': key, 'mineral': name, 'reason': 'missing_diffraction_confirmation', 'sha256': expected})
            continue
        points = []
        for line in content.decode().splitlines():
            if not line.strip() or line.startswith('#'):
                continue
            try:
                parts = line.replace(',', ' ').split()
                if len(parts) == 2:
                    points.append([float(parts[0]), float(parts[1])])
            except ValueError:
                continue
        array = np.asarray(points)
        if len(array) < 50 or not np.isfinite(array).all() or not np.all(np.diff(array[:, 0]) > 0):
            exclusions.append({'sample_id': key, 'mineral': name, 'reason': 'invalid_measured_axis', 'sha256': expected})
            continue
        measured[key] = {'sample_id': key, 'mineral': name, 'sha256': expected,
                         'status_source': headers['STATUS'], 'description': headers.get('DIFFRACTION SAMPLE DESCRIPTION'),
                         'source_url': 'https://rruff.info/' + key,
                         'points': points, 'in_training_classes': name in CLASSES}
    # Public target identities/measurements and all CPAA data stay out of training.
    targets = REPO / 'output/neural-reinference-20261023/input-manifest.json'
    write(OUT / 'training-references.json', training)
    write(OUT / 'measured-test-corpus.json', sorted(measured.values(), key=lambda row: row['sample_id']))
    write(OUT / 'measured-exclusions.json', exclusions)
    protocol = {
        'schema_version': 'argiloteca.drx.neural_training_protocol.v1',
        'model_id': MODEL_ID, 'rule_id': RULE_ID, 'seed': SEED,
        'classes': CLASSES, 'usage_policy': 'experimental_auxiliary_not_confirmatory',
        'training_source': '10 unique calculated AMCSD structures; duplicate COD representations deduplicated',
        'training_examples_per_class': 600, 'synthetic_validation_per_class': 120,
        'synthetic_validation_scope': 'same structure templates, different noise seeds; not independent mineral validation',
        'epochs': 40, 'batch_size': 64, 'optimizer': 'AdamW', 'learning_rate': .001, 'weight_decay': .0001,
        'checkpoint_selection': 'fixed final epoch, no selection using measured tests or 899 target curves',
        'grid': {'start': 2., 'end': 32., 'points': 601, 'step': .05},
        'preprocess': {'background': 'minimum_filter_81_then_gaussian_sigma8_on_observed_grid',
                       'normalization': 'sqrt_positive_residual_over_max', 'missing_angles': 'zero_signal_and_zero_coverage_channel',
                       'radiation_angstrom': 1.5406, 'radiation_tolerance': .005},
        'augmentation': {'shift_degrees': [-.12, .12], 'gaussian_sigma_degrees': [.035, .18],
                         'line_intensity_lognormal_sigma': .65, 'baseline_and_poisson_noise': True,
                         'starts_degrees': [2., 2.3, 3., 5.], 'ends_degrees': [15., 20., 28., 32.],
                         'unknown': 'random peaks, broad background, noise, two-template mixtures; not real OOD validation'},
        'decision': {'minimum_coverage': .5, 'minimum_ranking_score': .8, 'minimum_margin': .3},
        'promotion_gates': {'minimum_measured_in_class_specimens': 10,
                            'measured_in_class_top1_min': .8,
                            'measured_clay_family_top3_min': .9,
                            'measured_oov_false_accept_max': .1,
                            'synthetic_negative_false_accept_max': .05,
                            'cpaa_natural_family_top3_min': .9,
                            'all_899_finite_and_reproducible': True,
                            'note': 'Predeclared engineering gates for a limited auxiliary pilot, not scientific identification criteria'},
        'limitations': ['No independent curator ground truth for the 899 production curves',
                       'Calculated ideal powder structures do not describe all oriented N/G/C responses',
                       'Scores are not calibrated probabilities or mineral proportions',
                       'No automatic record updates or curator confirmation'],
        'inputs': {'reference_sha256': sha(reference_path), 'target_manifest_sha256': sha(targets),
                   'training_references_sha256': sha(OUT / 'training-references.json'),
                   'measured_test_corpus_sha256': sha(OUT / 'measured-test-corpus.json'),
                   'model_source_sha256': sha(Path(__file__).with_name('model.py'))},
        'sources': ['https://www.rruff.net/help/zip-download/',
                    'https://docs.pytorch.org/docs/2.14/notes/randomness.html'],
    }
    write(OUT / 'protocol.json', protocol)
    print(json.dumps({'training_structures': len(training), 'independent_measured_specimens': len(measured),
                      'in_class_measured': sum(row['in_training_classes'] for row in measured.values()),
                      'out_of_class_measured': sum(not row['in_training_classes'] for row in measured.values()),
                      'excluded': len(exclusions), 'protocol_sha256': sha(OUT / 'protocol.json')}))


if __name__ == '__main__':
    main()
