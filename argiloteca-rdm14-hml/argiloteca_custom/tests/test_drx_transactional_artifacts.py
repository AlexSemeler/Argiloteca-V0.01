"""Contract tests for transactional filesystem-backed DRX artifacts."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import pytest

from argiloteca.drx.repositories import InvalidArtifactId, JsonArtifactRepository
from argiloteca.services.drx_external_jobs import get_external_job
from argiloteca.services.drx_runs import persist_drx_run


@pytest.mark.parametrize("identifier", ["", "../job", "job/child", ".hidden", "job.json"])
def test_repository_rejects_unbounded_identifiers(tmp_path, identifier):
    repository = JsonArtifactRepository(tmp_path)

    with pytest.raises(InvalidArtifactId):
        repository.path(identifier)


def test_atomic_write_preserves_previous_artifact_if_replace_fails(tmp_path):
    repository = JsonArtifactRepository(tmp_path)
    repository.write("run-1", {"version": 1})

    with mock.patch("argiloteca.drx.repositories.json_artifact.os.replace", side_effect=OSError("interrupted")):
        with pytest.raises(OSError, match="interrupted"):
            repository.write("run-1", {"version": 2})

    assert repository.read("run-1") == {"version": 1}
    assert list(tmp_path.glob("*.tmp")) == []


def test_concurrent_writes_produce_complete_json_artifacts(tmp_path):
    repository = JsonArtifactRepository(tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda index: repository.write(f"run-{index}", {"index": index}), range(32)))

    assert sorted(payload["index"] for payload in repository.list_payloads()) == list(range(32))


def test_run_service_rejects_path_traversal_in_explicit_id(tmp_path):
    with mock.patch("argiloteca.services.drx_runs.DEFAULT_RUNS_DIR", Path(tmp_path)):
        with pytest.raises(InvalidArtifactId):
            persist_drx_run(run_id="../outside", analysis_run={"input": {}})

    assert not (tmp_path.parent / "outside.json").exists()


def test_job_reader_maps_invalid_id_to_existing_not_found_contract(tmp_path):
    with mock.patch("argiloteca.services.drx_external_jobs.DEFAULT_JOBS_DIR", Path(tmp_path)):
        result = get_external_job("../outside")

    assert result == {"success": False, "error": "Job DRX externo nao encontrado."}
