"""Independent measured-profile and exploratory CPAA evaluation, no tuning.

All RRUFF specimens are held out of training. CPAA Phase 1 is a previously
examined user-provided label, not independently confirmed curator ground truth.
"""
import collections
import json
from pathlib import Path
import sys

import numpy as np

from model import CLASSES, decision, deterministic, load_model
from model import preprocess
from inference_runtime import predict_stable as predict
from prepare import OUT, REPO, sha, write

FAMILIES = {'kaolinite': 'kaolin_group', 'montmorillonite': 'smectite_group', 'clinochlore': 'chlorite_group'}
PHASE = {'caulinita': 'kaolin_group', 'esmectita': 'smectite_group', 'clorita': 'chlorite_group'}


def rate(rows, field):
    return sum(bool(row[field]) for row in rows) / len(rows) if rows else None


def evaluate():
    deterministic()
    protocol = json.loads((OUT / 'protocol.json').read_text())
    manifest = json.loads((OUT / 'training/model-manifest.json').read_text())
    assert manifest['protocol_sha256'] == sha(OUT / 'protocol.json')
    assert sha(OUT / 'measured-test-corpus.json') == protocol['inputs']['measured_test_corpus_sha256']
    model = load_model(OUT / 'training/weights.pt', manifest['weights_sha256'])
    corpus = json.loads((OUT / 'measured-test-corpus.json').read_text())
    measured = []
    for row in corpus:
        array = np.asarray(row['points'])
        tensors, metadata = preprocess(array[:, 0], array[:, 1])
        scores = predict(model, tensors[None])[0]
        result = decision(scores, metadata['coverage_fraction'], protocol)
        rank = [CLASSES[int(i)] for i in np.argsort(-scores, kind='stable')]
        expected = row['mineral']
        family = FAMILIES.get(expected, expected)
        measured.append({
            **{key: row[key] for key in ['sample_id', 'mineral', 'sha256', 'status_source', 'source_url', 'in_training_classes']},
            'coverage': metadata, 'decision': result,
            'scores': {name: float(value) for name, value in zip(CLASSES, scores)},
            'species_top1': rank[0] == expected, 'species_top3': expected in rank[:3],
            'family_top1': FAMILIES.get(rank[0], rank[0]) == family,
            'family_top3': family in [FAMILIES.get(name, name) for name in rank[:3]],
            'false_accept': expected not in CLASSES and result['status'] == 'experimental_candidate',
            'accepted_and_correct': result['status'] == 'experimental_candidate' and rank[0] == expected,
        })
    in_class = [r for r in measured if r['in_training_classes']]
    clay = [r for r in in_class if r['mineral'] in FAMILIES or r['mineral'] == 'sepiolite']
    outside = [r for r in measured if not r['in_training_classes']]
    cpaa = []
    sys.path.insert(0, str(REPO / 'argiloteca-rdm14-hml/argiloteca_custom'))
    from argiloteca_drx_core.raw_lifecycle import parse_lifecycle_raw
    base = REPO / 'output/cpaa-reference-evaluation-20261020'
    audit = json.loads((base / 'input-audit.json').read_text())
    for group in audit['groups']:
        if not group['has_files']:
            continue
        natural = [row for row in group['files'] if row['treatment'] == 'N']
        assert len(natural) == 1
        file = natural[0]
        content = (base / file['relative_path']).read_bytes()
        assert sha(base / file['relative_path']) == file['sha256']
        parsed = parse_lifecycle_raw(content)
        tensor, metadata = preprocess(parsed.two_theta, parsed.intensity, parsed.metadata['wavelength_angstrom'])
        scores = predict(model, tensor[None])[0]
        result = decision(scores, metadata['coverage_fraction'], protocol)
        expected_family = PHASE[group['phase1']]
        # Do not publish original sample names or paths in candidate artifacts.
        cpaa.append({'input_sha256': file['sha256'], 'phase1': group['phase1'],
                     'label_status': 'user_provided_previously_exposed_not_independent_curator_confirmation',
                     'decision': result, 'family_top1': FAMILIES.get(result['first'], result['first']) == expected_family,
                     'family_top3': expected_family in [FAMILIES.get(name, name) for name in result['top3']]})
    data = np.load(OUT / 'training/synthetic-validation.npz', allow_pickle=False)
    scores = predict(model, data['x'])
    negative = []
    for i in np.flatnonzero(data['y'] == CLASSES.index('unknown')):
        result = decision(scores[i], float(data['x'][i, 1].mean()), protocol)
        negative.append({'false_accept': result['status'] == 'experimental_candidate'})
    summary = {
        'measured_in_class_specimens': len(in_class), 'measured_out_of_class_specimens': len(outside),
        'measured_in_class_top1': rate(in_class, 'species_top1'), 'measured_in_class_top3': rate(in_class, 'species_top3'),
        'measured_clay_family_top3': rate(clay, 'family_top3'),
        'measured_oov_false_accept_rate': rate(outside, 'false_accept'),
        'measured_accepted_correct': sum(r['accepted_and_correct'] for r in in_class),
        'measured_accepted_wrong': sum(r['decision']['status'] == 'experimental_candidate' and not r['species_top1'] for r in in_class),
        'synthetic_negative_count': len(negative), 'synthetic_negative_false_accept_rate': rate(negative, 'false_accept'),
        'cpaa_natural_curves': len(cpaa), 'cpaa_natural_family_top1': rate(cpaa, 'family_top1'),
        'cpaa_natural_family_top3': rate(cpaa, 'family_top3'),
        'cpaa_scope': 'exploratory convenience sample, not 30 independently curated compositions',
        'measured_by_mineral': {name: {'n': len(rows), 'top1': rate(rows, 'species_top1'), 'top3': rate(rows, 'species_top3')}
                                for name in sorted({r['mineral'] for r in measured})
                                for rows in [[r for r in measured if r['mineral'] == name]]},
    }
    gates = protocol['promotion_gates']
    checks = {
        'minimum_measured_in_class_specimens': len(in_class) >= gates['minimum_measured_in_class_specimens'],
        'measured_in_class_top1_min': summary['measured_in_class_top1'] >= gates['measured_in_class_top1_min'],
        'measured_clay_family_top3_min': summary['measured_clay_family_top3'] >= gates['measured_clay_family_top3_min'],
        'measured_oov_false_accept_max': summary['measured_oov_false_accept_rate'] <= gates['measured_oov_false_accept_max'],
        'synthetic_negative_false_accept_max': summary['synthetic_negative_false_accept_rate'] <= gates['synthetic_negative_false_accept_max'],
        'cpaa_natural_family_top3_min': summary['cpaa_natural_family_top3'] >= gates['cpaa_natural_family_top3_min'],
    }
    report = {'schema_version': 'argiloteca.drx.neural_pilot_evaluation.v1',
              'model_id': manifest['model_id'], 'weights_sha256': manifest['weights_sha256'],
              'inference_dtype': 'float64', 'inference_runtime_sha256': sha(Path(__file__).with_name('inference_runtime.py')),
              'protocol_sha256': sha(OUT / 'protocol.json'), 'summary': summary,
              'scientific_gates': checks, 'scientific_gates_passed': all(checks.values()),
              'promotion_allowed': False, 'promotion_note': 'Technical checks and 899-input inference must also pass before any activation',
              'measured': measured, 'cpaa': cpaa}
    write(OUT / 'evaluation.json', report)
    print(json.dumps({'summary': {k: v for k, v in summary.items() if k != 'measured_by_mineral'}, 'gates': checks,
                      'scientific_gates_passed': all(checks.values())}, ensure_ascii=False))


if __name__ == '__main__':
    evaluate()
