"""Central limits for the canonical DRX scientific API."""

from argiloteca_drx_core.parser_limits import (
    MAX_CURVE_BYTES,
    MAX_CURVE_POINTS,
    MAX_TEXT_LINE_BYTES,
    MAX_TEXT_LINES,
    MIN_POINTS,
)

MAX_RENDER_POINTS = 3_000
MAX_EXPORTED_PEAKS = 100
MAX_RESULT_CANDIDATES = 12


class DrxLimits:
    """Immutable namespace used by manifests and validation code."""

    max_curve_bytes = MAX_CURVE_BYTES
    max_curve_points = MAX_CURVE_POINTS
    max_text_lines = MAX_TEXT_LINES
    max_text_line_bytes = MAX_TEXT_LINE_BYTES
    min_points = MIN_POINTS
    max_render_points = MAX_RENDER_POINTS
    max_exported_peaks = MAX_EXPORTED_PEAKS
    max_result_candidates = MAX_RESULT_CANDIDATES
