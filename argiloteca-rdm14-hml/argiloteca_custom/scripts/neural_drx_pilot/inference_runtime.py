"""Float64 CPU evaluation of the unchanged float32 trained parameters.

Float32 convolutions can use different accumulation orders for singleton and
batched inputs. The production gate's 1e-6 tolerance is kept unchanged; float64
evaluation reduces this numerical discrepancy without retraining or tuning.
"""
import numpy as np
import torch


def predict_stable(model, values, batch_size=64):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 3 or values.shape[1:] != (2, 601) or not np.isfinite(values).all():
        raise ValueError('invalid_model_input')
    model = model.to(dtype=torch.float64).eval()
    outputs = []
    with torch.inference_mode():
        for start in range(0, len(values), batch_size):
            logits = model(torch.from_numpy(values[start:start + batch_size]))
            outputs.append(torch.softmax(logits, dim=1).numpy())
    scores = np.concatenate(outputs) if outputs else np.empty((0, 11))
    if not np.isfinite(scores).all() or not np.allclose(scores.sum(axis=1), 1., atol=1e-12):
        raise ValueError('invalid_model_output')
    return scores
