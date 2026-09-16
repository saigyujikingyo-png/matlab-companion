"""A failed worker remains accounted for until its durable outcome is settled."""

import asyncio
import time

import pytest

import matlab_companion.core as core_module
from matlab_companion.core import Core
from matlab_companion.storage import file_lock


class LostBackend:
    def __init__(self):
        self.calls = []

    def available(self):
        return True

    async def execute(self, job):
        self.calls.append(job.name)
        raise RuntimeError("Portable backend response loss")


@pytest.fixture
def failed_worker(tmp_path, monkeypatch):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "data.csv"
    source.write_text("concentration,absorbance\n1,3\n2,5\n", encoding="utf-8")
    backend = LostBackend()
    core = Core(tmp_path / "store", [inputs], backend=backend)
    original_atomic = core_module.atomic_json

    def unavailable_quarantine(path, payload):
        if path.name == "executor-quarantine.json":
            raise OSError("Portable quarantine persistence failure")
        original_atomic(path, payload)

    monkeypatch.setattr(core_module, "atomic_json", unavailable_quarantine)
    try:
        inspected = core.call("matlab_inspect", {"path": str(source)})
        assert inspected["ok"]
        accepted = core.call(
            "matlab_run",
            {
                "operation": "data_profile",
                "input_id": inspected["input"]["input_id"],
                "parameters": {},
                "idempotency_key": "worker-settlement",
            },
        )
        assert accepted["ok"]
        job_id = accepted["job_id"]
        future = core.futures[job_id]
        assert isinstance(future.exception(timeout=5), OSError)
        assert core._state(job_id)["state"] == "running"
        assert (core.root / "executor-active.json").exists()
        yield core, backend, job_id, future, original_atomic
    finally:
        core.close()


def test_failed_worker_is_settled_under_execution_ownership_then_can_idle(
    failed_worker, monkeypatch
):
    core, backend, job_id, future, original_atomic = failed_worker
    job = core._job_path(job_id)
    dispatch = (job / "dispatch.json").read_bytes()
    monkeypatch.setattr(core_module, "atomic_json", original_atomic)
    original_settle = core._execution_failed
    settlements = []

    def settle_while_locked(identifier, directory, error):
        with pytest.raises(TimeoutError), file_lock(core.root / ".execution.lock"):
            raise AssertionError("Idle settlement must retain execution ownership")
        settlements.append(identifier)
        return original_settle(identifier, directory, error)

    monkeypatch.setattr(core, "_execution_failed", settle_while_locked)
    assert core.has_active_work() is False
    assert settlements == [job_id]
    assert job_id not in core.futures
    assert future.done()
    settled = core._state(job_id)
    assert settled["state"] == "unknown"
    assert settled["error"]["code"] == "OUTCOME_UNKNOWN"
    assert (core.root / "executor-quarantine.json").exists()
    assert (job / "dispatch.json").read_bytes() == dispatch
    assert backend.calls == [job_id]
    assert core.has_active_work() is False
    assert core._state(job_id) == settled
    assert settlements == [job_id]


def test_persistent_storage_failure_keeps_the_failed_future_and_barrier(failed_worker):
    core, backend, job_id, future, _ = failed_worker
    state_path = core._job_path(job_id) / "state.json"
    before = state_path.read_bytes()
    barrier = (core.root / "executor-active.json").read_bytes()
    for _attempt in range(2):
        assert core.has_active_work() is True
        assert core.futures[job_id] is future
        assert isinstance(future.exception(), OSError)
    assert state_path.read_bytes() == before
    assert (core.root / "executor-active.json").read_bytes() == barrier
    assert backend.calls == [job_id]


def test_busy_execution_owner_defers_settlement_without_blocking(failed_worker, monkeypatch):
    core, backend, job_id, future, original_atomic = failed_worker
    monkeypatch.setattr(core_module, "atomic_json", original_atomic)
    with file_lock(core.root / ".execution.lock"):
        started = time.monotonic()
        assert core.has_active_work() is True
        assert time.monotonic() - started < 0.5
        assert core.futures[job_id] is future
        assert core._state(job_id)["state"] == "running"
    assert core.has_active_work() is False
    assert core._state(job_id)["state"] == "unknown"
    assert backend.calls == [job_id]


def test_late_completed_receipt_stays_completed_when_failed_worker_is_settled(
    failed_worker, monkeypatch
):
    from test_recovery import ReceiptBackend

    core, backend, job_id, _future, original_atomic = failed_worker
    monkeypatch.setattr(core_module, "atomic_json", original_atomic)
    asyncio.run(ReceiptBackend().execute(core._job_path(job_id)))
    late = core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
    assert late["ok"] and late["job"]["state"] == "completed"
    observed = late["job"]
    assert core.has_active_work() is False
    assert core._state(job_id) == observed
    assert (core.root / "executor-quarantine.json").exists()
    assert backend.calls == [job_id]
