"""Public job snapshots, bounded waits and durable event semantics."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from matlab_companion.contracts import JobSummary
from matlab_companion.core import Core
from matlab_companion.storage import atomic_json


@pytest.fixture
def job(tmp_path):
    core = Core(tmp_path)
    identifier = str(uuid.uuid4())
    original = {
        "job_id": identifier,
        "operation": "data_profile",
        "state": "queued",
        "summary": "Accepted",
    }
    atomic_json(tmp_path / "jobs" / identifier / "state.json", original)
    yield core, identifier
    core.close()


def test_legacy_observation_is_passive_and_wait_deadline_is_success(job):
    core, identifier = job
    path = core._job_path(identifier) / "state.json"
    before = path.read_bytes()
    started = time.monotonic()
    output = core.call(
        "matlab_job", {"job_id": identifier, "action": "wait", "timeout_seconds": 0.1}
    )
    assert output["ok"] and output["job"]["event_seq"] == 0
    assert output["job"]["phase"] is None and path.read_bytes() == before
    assert 0.08 <= time.monotonic() - started < 1


def test_wait_returns_meaningful_change_and_repeated_cancel_does_not_increment(job):
    core, identifier = job
    entered = threading.Event()

    def observe():
        entered.set()
        return core.call(
            "matlab_job",
            {"job_id": identifier, "action": "wait", "after_event_seq": 0, "timeout_seconds": 5},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(observe)
        assert entered.wait(1)
        first = core.call("matlab_job", {"job_id": identifier, "action": "cancel"})
        observed = waiting.result(timeout=1)
    again = core.call("matlab_job", {"job_id": identifier, "action": "cancel"})
    assert first["job"] == again["job"] == observed["job"]
    assert first["job"]["event_seq"] == 1
    assert first["job"]["phase"] == "cancel_requested"


def test_out_of_date_and_future_cursors_and_unknown_are_distinct(job):
    core, identifier = job
    core._save_state(
        identifier,
        state="unknown",
        summary="Outcome not observed",
        error={"code": "OUTCOME_UNKNOWN", "message": "Do not replay"},
    )
    for cursor in (0, 1):
        started = time.monotonic()
        output = core.call(
            "matlab_job",
            {
                "job_id": identifier,
                "action": "wait",
                "after_event_seq": cursor,
                "timeout_seconds": 10,
            },
        )
        assert output["ok"] and output["job"]["state"] == "unknown"
        assert time.monotonic() - started < 0.5
    bad = core.call("matlab_job", {"job_id": identifier, "action": "wait", "after_event_seq": 2})
    assert not bad["ok"] and bad["job_id"] == identifier


@pytest.mark.parametrize(
    "options",
    [
        {"timeout_seconds": 11},
        {"timeout_seconds": True},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": -1},
        {"after_event_seq": True},
        {"after_event_seq": -1},
    ],
)
def test_wait_rejects_invalid_bounds_without_side_effect(job, options):
    core, identifier = job
    before = (core._job_path(identifier) / "state.json").read_bytes()
    result = core.call("matlab_job", {"job_id": identifier, "action": "wait", **options})
    assert not result["ok"] and result["job_id"] == identifier
    assert (core._job_path(identifier) / "state.json").read_bytes() == before


def test_event_sequence_persists_and_compare_and_set_rejection_does_not_change(job):
    core, identifier = job
    first = core._save_state(identifier, state="running", summary="Backend dispatch")
    assert first["event_seq"] == 1 and first["phase"] == "executing"
    rejected = core._save_state(identifier, expected_states={"queued"}, state="failed")
    assert rejected == first
    second = core._save_state(identifier, phase="validating")
    stored = JobSummary.model_validate_json((core._job_path(identifier) / "state.json").read_text())
    assert stored.event_seq == second["event_seq"] == 2 and stored.phase == "validating"
