from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from argiloteca.drx.repositories import RawRepository
from argiloteca.drx.services.upload_service import UploadValidationError, read_validated_upload
from argiloteca.services import drx


@pytest.mark.parametrize("filename", ["../curve.raw", "/tmp/curve.raw", "folder/curve.raw", "", "curve.exe"])
def test_upload_validation_rejects_unsafe_or_unsupported_names(filename):
    with pytest.raises(UploadValidationError):
        read_validated_upload(BytesIO(b"RAW bytes"), filename=filename, max_bytes=100)


def test_upload_validation_rejects_empty_and_oversized_content():
    with pytest.raises(UploadValidationError, match="vazio"):
        read_validated_upload(BytesIO(b""), filename="curve.raw", max_bytes=5)
    with pytest.raises(UploadValidationError, match="limite"):
        read_validated_upload(BytesIO(b"123456"), filename="curve.raw", max_bytes=5)


def test_raw_repository_writes_new_bytes_without_temporary_residue(tmp_path):
    target = RawRepository(tmp_path).write_new("abc123", "curve.raw", b"validated")

    assert target.read_bytes() == b"validated"
    assert list(tmp_path.glob("*.tmp")) == []


def test_invalid_raw_upload_is_not_persisted(tmp_path):
    storage = mock.Mock(filename="broken.raw", stream=BytesIO(b"not a supported RAW"))
    with mock.patch.object(drx, "DRX_RAW_DIR", Path(tmp_path)), pytest.raises(drx.RawParseError):
        drx.import_raw_upload("record-1", storage)

    assert list(tmp_path.iterdir()) == []
