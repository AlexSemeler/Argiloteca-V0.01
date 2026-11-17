"""Canonical, dependency-light scientific API for the Argiloteca DRX panel.

Legacy modules remain importable, but new integrations should use the
versioned contracts and entry points exported here.
"""

from .contracts import (
    CuratorialReview,
    DrxPattern,
    Evidence,
    MineralCandidate,
    NgcComparison,
    Peak,
    PreparationProtocol,
    XrdFile,
)
from .method_manifest import build_method_manifest
from .ngc_diagnostics import interpret_ngc

__all__ = [
    "CuratorialReview",
    "DrxPattern",
    "Evidence",
    "MineralCandidate",
    "NgcComparison",
    "Peak",
    "PreparationProtocol",
    "XrdFile",
    "build_method_manifest",
    "interpret_ngc",
]
