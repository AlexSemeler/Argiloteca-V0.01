"""Canonical Bragg geometry facade with explicit wavelength policy."""

from argiloteca_drx_core.geometry import (
    BraggCalculation,
    bragg_from_two_theta,
    geometry_explanation,
    two_theta_from_d_spacing,
)

__all__ = [
    "BraggCalculation",
    "bragg_from_two_theta",
    "geometry_explanation",
    "two_theta_from_d_spacing",
]
