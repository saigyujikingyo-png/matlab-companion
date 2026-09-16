"""Passive, bounded accounting never reads science or removes retained jobs."""

import os
import uuid

import pytest

from matlab_companion import diagnostics
from matlab_companion.contracts import RuntimeStatistics
from matlab_companion.storage import atomic_json


def retained_job(root, state="queued"):
    identifier = str(uuid.uuid4())
    directory = root / "jobs" / identifier
    atomic_json(
        directory / "state.json",
        {"job_id": identifier, "operation": "data_profile", "state": state, "summary": "Accepted"},
    )
    (directory / "original.csv").write_bytes(b"x\n1\n")
    return directory


def test_accounting_matches_regular_bytes_without_reading_originals(tmp_path, monkeypatch):
    directory = retained_job(tmp_path)
    expected = sum(path.stat().st_size for path in directory.iterdir())
    original_read = diagnostics.read_json
    read_paths = []

    def read_metadata(path):
        read_paths.append(path)
        assert path.name == "state.json"
        return original_read(path)

    monkeypatch.setattr(diagnostics, "read_json", read_metadata)
    value = RuntimeStatistics.model_validate(diagnostics.storage_observation(tmp_path))
    assert value.storage_complete and value.active_jobs == value.retained_jobs == 1
    assert value.storage_bytes == expected and len(read_paths) == 1
    assert value.retention == "explicit_removal_only" and not value.automatic_cleanup
    assert (directory / "original.csv").read_bytes() == b"x\n1\n"


def test_scan_limit_and_malformed_state_do_not_claim_complete_counts(tmp_path):
    directory = retained_job(tmp_path)
    limited = RuntimeStatistics.model_validate(
        diagnostics.storage_observation(tmp_path, max_entries=1)
    )
    assert not limited.storage_complete and limited.active_jobs is None
    (directory / "state.json").write_text("invalid metadata", encoding="utf-8")
    malformed = RuntimeStatistics.model_validate(diagnostics.storage_observation(tmp_path))
    assert not malformed.storage_complete and malformed.active_jobs is None


def test_missing_store_is_not_created(tmp_path):
    missing = tmp_path / "missing"
    result = RuntimeStatistics.model_validate(diagnostics.storage_observation(missing))
    assert result.storage_complete and result.storage_bytes == result.retained_jobs == 0
    assert not missing.exists()


@pytest.mark.skipif(
    os.name == "nt", reason="Windows unprivileged symlink availability is device-dependent"
)
def test_linked_scientific_files_are_not_counted_or_followed(tmp_path):
    directory = retained_job(tmp_path)
    outside = tmp_path / "outside.dat"
    outside.write_bytes(b"private" * 1000)
    (directory / "linked.dat").symlink_to(outside)
    value = RuntimeStatistics.model_validate(diagnostics.storage_observation(tmp_path))
    assert not value.storage_complete and value.active_jobs is None
    assert value.storage_bytes < outside.stat().st_size
