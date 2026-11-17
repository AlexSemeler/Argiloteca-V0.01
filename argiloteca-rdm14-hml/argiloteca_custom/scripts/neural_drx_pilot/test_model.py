"""Scientific-boundary and numerical regression tests for the offline pilot."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from inference_runtime import predict_stable
from model import CLASSES, GRID, ReferenceCNN, decision, deterministic, load_model, preprocess, state_digest


class ModelBoundaryTests(unittest.TestCase):
    def setUp(self):
        deterministic()
        self.signal = 10 + 300 * np.exp(-.5 * ((GRID - 12.4) / .15) ** 2) + 170 * np.exp(-.5 * ((GRID - 24.9) / .15) ** 2)
        self.protocol = {'decision': {'minimum_coverage': .5, 'minimum_ranking_score': .8, 'minimum_margin': .3}}

    def test_missing_angles_are_masked_and_never_extrapolated(self):
        mask = (GRID >= 3.) & (GRID <= 15.)
        value, metadata = preprocess(GRID[mask], self.signal[mask])
        self.assertTrue(np.array_equal(value[1], mask))
        self.assertTrue(np.all(value[0, ~mask] == 0))
        self.assertEqual(metadata['covered_points'], int(mask.sum()))

    def test_positive_gain_and_constant_offset_do_not_change_ranking_input(self):
        first, _ = preprocess(GRID, self.signal)
        second, _ = preprocess(GRID, self.signal * 17 + 300)
        np.testing.assert_allclose(first, second, atol=2e-6, rtol=0)

    def test_axis_reversal_and_nan_fail_instead_of_receiving_candidates(self):
        for x, y in [(GRID[::-1], self.signal), (GRID, np.where(GRID == GRID[10], np.nan, self.signal))]:
            with self.assertRaisesRegex(ValueError, 'nonfinite_or_nonmonotonic'):
                preprocess(x, y)

    def test_flat_and_short_curves_fail(self):
        with self.assertRaisesRegex(ValueError, 'flat_input'):
            preprocess(GRID, np.ones_like(GRID))
        with self.assertRaisesRegex(ValueError, 'insufficient_points'):
            preprocess(GRID[:12], self.signal[:12])

    def test_unsupported_radiation_is_not_treated_as_cu(self):
        with self.assertRaisesRegex(ValueError, 'unsupported_radiation'):
            preprocess(GRID, self.signal, wavelength=1.789)

    def test_ambiguous_unknown_and_short_range_outputs_abstain(self):
        probabilities = np.zeros(len(CLASSES))
        probabilities[-1] = .99
        self.assertIn('unknown_pattern', decision(probabilities, 1, self.protocol)['reasons'])
        probabilities[:] = 1 / len(CLASSES)
        self.assertIn('ambiguous_ranking', decision(probabilities, 1, self.protocol)['reasons'])
        probabilities[:] = 0
        probabilities[CLASSES.index('kaolinite')] = .99
        self.assertIn('limited_observed_range', decision(probabilities, .4, self.protocol)['reasons'])

    def test_checkpoint_digest_is_checked_before_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'weights.pt'
            torch.save(ReferenceCNN().state_dict(), path)
            with self.assertRaisesRegex(ValueError, 'checkpoint_digest_mismatch'):
                load_model(path, expected_sha256='0' * 64)

    def test_evaluation_preserves_weights_and_batch_order(self):
        model = ReferenceCNN()
        original = state_digest(model)
        data = np.stack([preprocess(GRID, self.signal)[0], preprocess(GRID, self.signal[::-1])[0]])
        single = predict_stable(model, data, batch_size=1)
        batch = predict_stable(model, data[::-1].copy(), batch_size=2)[::-1]
        np.testing.assert_allclose(single, batch, atol=1e-12, rtol=0)
        self.assertEqual(state_digest(model), original)


if __name__ == '__main__':
    unittest.main()
