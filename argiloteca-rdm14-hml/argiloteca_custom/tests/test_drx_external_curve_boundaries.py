from pathlib import Path
from unittest import mock

import pytest

from argiloteca.drx.services.gsas2_validation_service import validate_with_gsas2
from argiloteca.drx.services.similarity_service import SimilarityRequest, compare_external_curve


def similarity_request(scope="all", record_id="r1"):
    return SimilarityRequest(record_id, scope, "curve.raw", "a" * 64, {}, [1.0], [2.0], [], [])


@pytest.mark.parametrize("scope", ["all", "global", "packages", "pacotes"])
def test_global_similarity_scopes_omit_record_id(scope):
    compare = mock.Mock(return_value={"success": True})
    compare_external_curve(similarity_request(scope), compare)

    assert compare.call_args.args[0] is None
    assert compare.call_args.kwargs["global_package_scan"] is True


def test_local_similarity_scope_preserves_record_id():
    compare = mock.Mock(return_value={"success": True})
    compare_external_curve(similarity_request("record"), compare)

    assert compare.call_args.args[0] == "r1"
    assert compare.call_args.kwargs["global_package_scan"] is False


def test_gsas2_adapter_rejects_path_outside_temporary_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    outside = tmp_path / "outside.raw"
    outside.write_bytes(b"raw")

    with pytest.raises(ValueError, match="fora da raiz"):
        validate_with_gsas2(
            temporary_path=outside, temporary_root=root, original_filename="outside.raw",
            detected_peaks=[], seed_builder=mock.Mock(), submit=mock.Mock(),
        )


def test_gsas2_adapter_preserves_seed_and_submit_contract(tmp_path):
    path = tmp_path / "curve.raw"
    path.write_bytes(b"raw")
    seed_builder = mock.Mock(return_value=[{"position": 12.3}])
    submit = mock.Mock(return_value={"available": True})

    result = validate_with_gsas2(
        temporary_path=path, temporary_root=Path(tmp_path), original_filename="curve.raw",
        detected_peaks=[{"two_theta": 12.3}], seed_builder=seed_builder, submit=submit,
    )

    assert result == {"available": True}
    seed_builder.assert_called_once_with([{"two_theta": 12.3}])
    assert submit.call_args.kwargs["seed_peaks"] == [{"position": 12.3}]
