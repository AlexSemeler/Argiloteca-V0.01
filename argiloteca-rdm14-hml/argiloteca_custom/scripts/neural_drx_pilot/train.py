"""Deterministic CPU training from frozen calculated references only."""
import collections
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
import torch

from model import CLASSES, GRID, MODEL_ID, ReferenceCNN, SEED, deterministic, predict, preprocess, state_digest
from prepare import OUT, sha, write


def synthesize(reference, rng, protocol):
    peaks = [(row['two_theta'], row['relative_intensity'] / 100.) for row in reference['peaks']
             if 1.5 <= row['two_theta'] <= 32.5 and row['relative_intensity'] > .01]
    shift = rng.uniform(*protocol['augmentation']['shift_degrees'])
    width = rng.uniform(*protocol['augmentation']['gaussian_sigma_degrees'])
    values = np.zeros(len(GRID), dtype=np.float64)
    for position, amplitude in peaks:
        height = amplitude * rng.lognormal(0, protocol['augmentation']['line_intensity_lognormal_sigma'])
        values += height * np.exp(-.5 * ((GRID - position - shift) / width) ** 2)
    return values


def dataset(references, per_class, seed, protocol):
    rng = np.random.default_rng(seed)
    by_class = {row['mineral_id']: row for row in references}
    values, labels = [], []
    classes = CLASSES[:-1]
    for name in CLASSES:
        for _ in range(per_class):
            if name != 'unknown':
                signal = synthesize(by_class[name], rng, protocol)
            else:
                mode = int(rng.integers(0, 4))
                signal = np.zeros(len(GRID))
                if mode == 0:
                    for _ in range(int(rng.integers(1, 14))):
                        position, width, height = rng.uniform(2, 32), rng.uniform(.04, .3), rng.uniform(.1, 1)
                        signal += height * np.exp(-.5 * ((GRID - position) / width) ** 2)
                elif mode == 1:
                    first, second = rng.choice(classes, size=2, replace=False)
                    signal = synthesize(by_class[first], rng, protocol) + synthesize(by_class[second], rng, protocol)
                elif mode == 2:
                    signal = rng.uniform(.1, 1.) * np.exp(-.5 * ((GRID - rng.uniform(5, 26)) / rng.uniform(1, 5)) ** 2)
            maximum = max(float(signal.max()), 1e-6)
            baseline = maximum * (rng.uniform(0, .3) + rng.uniform(0, .5) * np.exp(-(GRID - 2) / rng.uniform(2, 20)))
            counts = (signal + baseline) * rng.uniform(300, 5000) / maximum
            counts = rng.poisson(np.maximum(counts, 0)).astype(np.float64)
            counts += rng.uniform(0, 15, size=len(GRID))
            start = float(rng.choice(protocol['augmentation']['starts_degrees']))
            end = float(rng.choice(protocol['augmentation']['ends_degrees']))
            mask = (GRID >= start) & (GRID <= end)
            tensor, _ = preprocess(GRID[mask], counts[mask])
            target = CLASSES.index(name)
            # A template with no observable peak cannot be a positive example.
            if name != 'unknown' and signal[mask].max() < .01 * max(signal.max(), 1e-12):
                target = CLASSES.index('unknown')
            values.append(tensor)
            labels.append(target)
    order = rng.permutation(len(labels))
    return np.asarray(values, dtype=np.float32)[order], np.asarray(labels, dtype=np.int64)[order]


def train(run_name='training'):
    protocol = json.loads((OUT / 'protocol.json').read_text())
    assert sha(Path(__file__).with_name('model.py')) == protocol['inputs']['model_source_sha256']
    assert sha(OUT / 'training-references.json') == protocol['inputs']['training_references_sha256']
    destination = OUT / run_name
    if destination.exists():
        raise RuntimeError('Run directory already exists; do not overwrite a trained candidate')
    destination.mkdir()
    deterministic()
    started = time.monotonic()
    references = json.loads((OUT / 'training-references.json').read_text())
    x, y = dataset(references, protocol['training_examples_per_class'], SEED, protocol)
    vx, vy = dataset(references, protocol['synthetic_validation_per_class'], SEED + 1, protocol)
    np.savez_compressed(destination / 'synthetic-validation.npz', x=vx, y=vy)
    model = ReferenceCNN()
    optimizer = torch.optim.AdamW(model.parameters(), lr=protocol['learning_rate'], weight_decay=protocol['weight_decay'])
    criterion = torch.nn.CrossEntropyLoss(label_smoothing=.03)
    values, labels = torch.from_numpy(x), torch.from_numpy(y)
    generator = torch.Generator().manual_seed(SEED + 2)
    history = []
    print(json.dumps({'phase': 'training', 'examples': len(y), 'parameters': sum(p.numel() for p in model.parameters()),
                      'class_counts': dict(collections.Counter(CLASSES[int(i)] for i in y))}), flush=True)
    for epoch in range(protocol['epochs']):
        model.train()
        order = torch.randperm(len(labels), generator=generator)
        total, correct = 0., 0
        for start in range(0, len(labels), protocol['batch_size']):
            selected = order[start:start + protocol['batch_size']]
            optimizer.zero_grad(set_to_none=True)
            logits = model(values[selected])
            loss = criterion(logits, labels[selected])
            assert torch.isfinite(loss)
            loss.backward()
            optimizer.step()
            total += float(loss.detach()) * len(selected)
            correct += int((logits.argmax(dim=1) == labels[selected]).sum())
        model.eval()
        scores = predict(model, vx)
        row = {'epoch': epoch + 1, 'training_loss': total / len(labels), 'training_top1': correct / len(labels),
               'synthetic_validation_top1': float((scores.argmax(axis=1) == vy).mean()),
               'elapsed_seconds': round(time.monotonic() - started, 3)}
        history.append(row)
        if (epoch + 1) % 5 == 0:
            print(json.dumps(row), flush=True)
    torch.save(model.state_dict(), destination / 'weights.pt')
    write(destination / 'history.json', history)
    write(destination / 'model-manifest.json', {
        'model_id': MODEL_ID, 'classes': CLASSES, 'architecture': 'Conv1d(2,8,9,pad4)-ReLU-Conv1d(8,16,7,stride2,pad3)-ReLU-AvgPool4-Flatten-Linear1200x64-ReLU-Linear64x11',
        'weights_sha256': sha(destination / 'weights.pt'), 'state_digest': state_digest(model),
        'parameter_count': sum(p.numel() for p in model.parameters()), 'weights_bytes': (destination / 'weights.pt').stat().st_size,
        'protocol_sha256': sha(OUT / 'protocol.json'), 'training_source_sha256': sha(Path(__file__)),
        'runtime': {'python': platform.python_version(), 'torch': torch.__version__, 'numpy': np.__version__, 'scipy': scipy.__version__,
                    'device': 'cpu', 'threads': torch.get_num_threads(), 'deterministic_algorithms': True},
        'training_examples': len(y), 'training_elapsed_seconds': round(time.monotonic() - started, 3),
        'public_target_curves_used_in_training': 0, 'measured_test_profiles_used_in_training': 0,
        'checkpoint_selection': protocol['checkpoint_selection'], 'usage_policy': protocol['usage_policy'],
        'final_synthetic_validation_top1': history[-1]['synthetic_validation_top1'],
    })
    print(json.dumps({'saved': str(destination.relative_to(OUT)), 'state_digest': state_digest(model),
                      'elapsed_seconds': round(time.monotonic() - started, 3)}), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-name', default='training')
    train(parser.parse_args().run_name)
