"""Offline, experimental reference-pattern CNN. Never imported by web routes.

Outputs are uncalibrated ranking scores, not mineral fractions or confirmation.
The measured coverage mask is a separate channel; absent angles are not data.
"""
import hashlib
import json
import random

import numpy as np
from scipy.ndimage import gaussian_filter1d, minimum_filter1d
import torch
from torch import nn

MODEL_ID = "argiloteca-drx-reference-cnn-v1-20261023"
RULE_ID = "reference-cnn-mask-2-32-v1"
CLASSES = ["albite", "calcite", "clinochlore", "hematite", "illite", "kaolinite",
           "montmorillonite", "palygorskite", "quartz", "sepiolite", "unknown"]
GRID = np.linspace(2.0, 32.0, 601, dtype=np.float64)
SEED = 20261023


def deterministic(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)


def preprocess(two_theta, intensity, wavelength=1.5406):
    """Crop/interpolate observed angles only, subtract a declared local envelope.

    81 grid points = 4 degrees. This is an engineering transformation, not a
    physical background estimate. No axis alignment or mineral-specific offset.
    """
    xs, ys = np.asarray(two_theta, dtype=np.float64), np.asarray(intensity, dtype=np.float64)
    if xs.ndim != 1 or ys.shape != xs.shape or len(xs) < 50:
        raise ValueError("invalid_shape_or_insufficient_points")
    if not np.isfinite(xs).all() or not np.isfinite(ys).all() or not np.all(np.diff(xs) > 0):
        raise ValueError("nonfinite_or_nonmonotonic_input")
    if not np.isfinite(wavelength) or abs(wavelength - 1.5406) > .005:
        raise ValueError("unsupported_radiation")
    mask = (GRID >= xs[0] - 1e-9) & (GRID <= xs[-1] + 1e-9)
    indices = np.flatnonzero(mask)
    if len(indices) < 100:
        raise ValueError("insufficient_observed_grid")
    observed = np.interp(GRID[mask], xs, ys)
    if np.ptp(observed) <= max(1e-12, 1e-10 * np.abs(observed).max()):
        raise ValueError("flat_input")
    envelope = gaussian_filter1d(minimum_filter1d(observed, size=81, mode="nearest"), 8, mode="nearest")
    residual = np.maximum(observed - envelope, 0)
    maximum = residual.max()
    if maximum <= 1e-12:
        raise ValueError("no_residual_signal")
    signal = np.zeros(len(GRID), dtype=np.float32)
    signal[mask] = np.sqrt(np.minimum(residual / maximum, 1)).astype(np.float32)
    tensor = np.stack([signal, mask.astype(np.float32)])
    return tensor, {"covered_points": int(mask.sum()), "grid_points": len(GRID),
                    "coverage_fraction": float(mask.mean()), "rule_id": RULE_ID,
                    "input_tensor_sha256": hashlib.sha256(tensor.astype('<f4').tobytes()).hexdigest()}


class ReferenceCNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(2, 8, 9, padding=4), nn.ReLU(),
            nn.Conv1d(8, 16, 7, stride=2, padding=3), nn.ReLU(),
            nn.AvgPool1d(4), nn.Flatten(),
        )
        self.classifier = nn.Sequential(nn.Linear(16 * 75, 64), nn.ReLU(), nn.Linear(64, len(CLASSES)))

    def forward(self, values):
        return self.classifier(self.features(values))


def state_digest(model):
    h = hashlib.sha256()
    for key, value in sorted(model.state_dict().items()):
        h.update(key.encode())
        h.update(value.detach().cpu().numpy().astype('<f4').tobytes())
    return h.hexdigest()


def load_model(path, expected_sha256=None):
    if expected_sha256:
        with open(path, 'rb') as stream:
            if hashlib.sha256(stream.read()).hexdigest() != expected_sha256:
                raise ValueError("checkpoint_digest_mismatch")
    model = ReferenceCNN()
    model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True), strict=True)
    model.eval()
    if not all(torch.isfinite(tensor).all() for tensor in model.state_dict().values()):
        raise ValueError("nonfinite_model")
    return model


def predict(model, values, batch_size=64):
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 3 or values.shape[1:] != (2, 601) or not np.isfinite(values).all():
        raise ValueError("invalid_model_input")
    outputs = []
    with torch.inference_mode():
        for start in range(0, len(values), batch_size):
            outputs.append(torch.softmax(model(torch.from_numpy(values[start:start + batch_size])), dim=1).numpy())
    scores = np.concatenate(outputs) if outputs else np.empty((0, len(CLASSES)))
    if not np.isfinite(scores).all() or not np.allclose(scores.sum(axis=1), 1, atol=1e-6):
        raise ValueError("invalid_model_output")
    return scores


def decision(scores, coverage, protocol):
    order = np.argsort(-scores, kind="stable")
    first, second = int(order[0]), int(order[1])
    reasons = []
    if CLASSES[first] == "unknown":
        reasons.append("unknown_pattern")
    if coverage < protocol['decision']['minimum_coverage']:
        reasons.append("limited_observed_range")
    if scores[first] < protocol['decision']['minimum_ranking_score']:
        reasons.append("low_uncalibrated_score")
    if scores[first] - scores[second] < protocol['decision']['minimum_margin']:
        reasons.append("ambiguous_ranking")
    return {"status": "abstained" if reasons else "experimental_candidate", "reasons": reasons,
            "first": CLASSES[first], "top3": [CLASSES[int(i)] for i in order[:3]],
            "ranking_score": float(scores[first]), "margin": float(scores[first] - scores[second])}
