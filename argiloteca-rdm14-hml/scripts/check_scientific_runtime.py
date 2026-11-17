"""Check unmodified NumPy/SciPy imports in a fresh, time-bounded interpreter.

No import hooks, numerical substitutions or documentation shortcuts are used.
This check covers the floating remainder hang observed on HML amd64/Rosetta.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

CHECK = r'''
import importlib.metadata
import inspect
import json
import sys
import time

started = time.monotonic()
import numpy as np
assert np.float64(2) % 2 == 0
assert np.array_equal(np.remainder([2., 3., -3.], 2.), [0., 1., 1.])

import scipy
from scipy.signal import find_peaks, savgol_filter
from scipy.stats import Normal
from scipy.stats import _distribution_infrastructure as infrastructure

assert not any('scipy_docs_test_hook' in name for name in sys.modules)
assert not any('DocumentationOnly' in type(finder).__name__ for finder in sys.meta_path)
assert inspect.signature(infrastructure._combine_docs).parameters['include_examples'].default is True
assert 'Examples' in Normal.__doc__ and 'X.variance()' in Normal.__doc__
assert Normal(mu=0, sigma=1).variance() == 1
assert Normal(mu=0, sigma=1).moment(order=4, kind='central') == 3
assert find_peaks([0., 1., 0., 2., 0.])[0].tolist() == [1, 3]
assert np.allclose(savgol_filter(np.arange(11.)**2, 9, 2), np.arange(11.)**2)

print(json.dumps({
    'status': 'passed', 'numpy': np.__version__, 'scipy': scipy.__version__,
    'numpy_path': np.__file__, 'scipy_path': scipy.__file__,
    'elapsed_seconds': time.monotonic() - started,
    'documentation_examples_intact': True, 'import_workaround': False,
    'remainder_scalar_array': 'passed', 'normal_moments': 'passed',
    'peak_detection_and_smoothing': 'passed',
}), flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        process = subprocess.run([sys.executable, "-c", CHECK], capture_output=True,
                                 text=True, timeout=args.timeout)
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "failed", "reason": "scientific_import_timeout",
                          "timeout_seconds": args.timeout}), flush=True)
        return 1
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
