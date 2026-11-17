import hashlib
import struct
from concurrent.futures import ThreadPoolExecutor

import pytest

from argiloteca.drx.contracts.external_curve import ExternalCurveRequest
from argiloteca.drx.repositories import TemporaryUploadRepository
from argiloteca.drx.services.temporary_curve_service import (
    ExternalCurveValidationError,
    prepare_external_curve,
)


def raw_legacy(points, start=3.0, step=0.02):
    header = bytearray(156)
    header[0:4] = b"RAW "
    header[4:8] = struct.pack("<I", len(points))
    header[8:12] = struct.pack("<f", start)
    header[12:16] = struct.pack("<f", step)
    return bytes(header) + struct.pack("<" + "f" * len(points), *points)


def test_glycolated_external_raw_alignment_preserves_intensity():
    content = raw_legacy(tuple(range(100, 160)))
    prepared = prepare_external_curve(ExternalCurveRequest(
        content=content,
        filename="NP02C-G.raw",
    ))

    assert prepared.parsed.metadata["two_theta_start"] == 2.0
    assert prepared.parsed.metadata["two_theta_alignment_method"] == "ngc_external_glycolated_start_heuristic"
    assert prepared.parsed.intensity == [float(value) for value in range(100, 160)]
    assert prepared.source_sha256 == hashlib.sha256(content).hexdigest()


def test_text_curve_is_parsed_without_raw_axis_heuristic():
    content = ("x,y\n" + "\n".join(f"{4 + i * .1},{10 + i}" for i in range(20))).encode()
    prepared = prepare_external_curve(ExternalCurveRequest(content=content, filename="curve.csv"))

    assert prepared.is_raw is False
    assert prepared.parsed.metadata["parser_format"] == "text_curve"
    assert "two_theta_offset_applied" not in prepared.parsed.metadata


@pytest.mark.parametrize("kwargs", [{"content": b""}, {"max_points": 0}, {"max_points": 5001}, {"wavelength_angstrom": 0}])
def test_external_curve_request_bounds(kwargs):
    values = {"content": b"content", "filename": "curve.csv", **kwargs}
    with pytest.raises(ExternalCurveValidationError):
        prepare_external_curve(ExternalCurveRequest(**values))


def test_temporary_repository_is_idempotent_and_concurrency_safe(tmp_path):
    repository = TemporaryUploadRepository(tmp_path)
    content = b"validated curve bytes"
    sha256 = hashlib.sha256(content).hexdigest()

    with ThreadPoolExecutor(max_workers=8) as executor:
        paths = list(executor.map(
            lambda _: repository.persist(content, filename="curve.raw", sha256=sha256),
            range(16),
        ))

    assert len(set(paths)) == 1
    assert paths[0].read_bytes() == content
    assert list(tmp_path.glob("*.tmp")) == []
