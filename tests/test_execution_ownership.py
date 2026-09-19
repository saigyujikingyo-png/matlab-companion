"""Execution ownership regressions with isolated stores and no native software."""

import os
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager

import pytest

import matlab_companion.core as core_module
from matlab_companion.contracts import JobSummary
from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, process_alive, process_start_identity, read_json

PARAMETERS = {
    "initial_concentration": 1,
    "rate_constant": 0.1,
    "time_end": 10,
    "points": 10,
    "concentration_unit": "mmol/L",
    "time_unit": "s",
}


class LostResponseBackend:
    def __init__(self, entered=None, release=None):
        self.calls = []
        self.entered, self.release = entered, release
        self.thread_id = None

    def available(self):
        return True

    async def execute(self, job):
        self.calls.append(job.name)
        self.thread_id = threading.get_ident()
        if self.entered:
            self.entered.set()
        if self.release:
            assert self.release.wait(5)
        raise RuntimeError("Simulated lost native response")


def submit(core, key):
    result = core.call(
        "matlab_run",
        {
            "operation": "first_order_kinetics",
            "parameters": PARAMETERS,
            "idempotency_key": key,
        },
    )
    assert result["ok"], result
    return result["job_id"]


def test_failure_is_quarantined_before_another_coordinator_acquires_execution(
    tmp_path, monkeypatch
):
    entered, release, second_finished = (threading.Event() for _ in range(3))
    first_backend = LostResponseBackend(entered, release)
    second_backend = LostResponseBackend()
    first = Core(tmp_path, backend=first_backend)
    second = Core(tmp_path, backend=second_backend)
    real_lock = core_module.file_lock
    quarantine_at_release = []

    @contextmanager
    def observe_release(path, timeout=0):
        try:
            with real_lock(path, timeout=timeout):
                yield
        finally:
            if path.name == ".execution.lock" and threading.get_ident() == first_backend.thread_id:
                quarantine_at_release.append((tmp_path / "executor-quarantine.json").exists())
                # Give the already queued second coordinator this exact release window.
                assert second_finished.wait(5)

    monkeypatch.setattr(core_module, "file_lock", observe_release)
    try:
        first_id = submit(first, "first")
        assert entered.wait(5)
        second_id = submit(second, "second")
        second.futures[second_id].add_done_callback(lambda _: second_finished.set())
        release.set()
        first.futures[first_id].result(timeout=10)
        second.futures[second_id].result(timeout=10)
        assert quarantine_at_release == [True]
        assert first.wait(first_id, timeout=10)["state"] == "unknown"
        assert second.wait(second_id, timeout=10)["state"] == "failed"
        assert second_backend.calls == [], "No second dispatch may pass an unresolved native job"
    finally:
        release.set()
        first.close()
        second.close()


def test_malformed_native_receipt_also_blocks_the_next_dispatch(tmp_path):
    class MalformedBackend(LostResponseBackend):
        async def execute(self, job):
            self.calls.append(job.name)
            atomic_json(job / "receipt.json", {"job_id": job.name})

    backend = MalformedBackend()
    core = Core(tmp_path, backend=backend)
    try:
        job_id = submit(core, "malformed")
        assert core.wait(job_id, timeout=5)["state"] == "unknown"
        # A terminal state is visible before the worker finishes publishing its
        # quarantine under the still-held execution lock. Join that same worker.
        core.futures[job_id].result(timeout=5)
        assert (tmp_path / "executor-quarantine.json").is_file()
        rejected = core.call(
            "matlab_run",
            {
                "operation": "first_order_kinetics",
                "parameters": PARAMETERS,
                "idempotency_key": "after-malformed",
            },
        )
        assert not rejected["ok"]
        assert backend.calls == [job_id]
    finally:
        core.close()


def test_malformed_receipt_keeps_execution_owned_until_quarantine(tmp_path, monkeypatch):
    publishing, release, second_waiting = (threading.Event() for _ in range(3))

    class MalformedBackend(LostResponseBackend):
        async def execute(self, job):
            self.thread_id = threading.get_ident()
            self.calls.append(job.name)
            atomic_json(job / "receipt.json", {"job_id": job.name})

    first_backend, second_backend = MalformedBackend(), LostResponseBackend()
    first = Core(tmp_path, backend=first_backend)
    second = Core(tmp_path, backend=second_backend)
    original_publish = first._publish_quarantine
    original_lock = core_module.file_lock

    def hold_publication(job_id, reason):
        publishing.set()
        assert release.wait(5), "The test must release its own quarantine publication gate"
        return original_publish(job_id, reason)

    @contextmanager
    def observe_execution_attempt(path, timeout=0):
        if (
            path.name == ".execution.lock"
            and publishing.is_set()
            and threading.get_ident() != first_backend.thread_id
        ):
            second_waiting.set()
        with original_lock(path, timeout=timeout):
            yield

    monkeypatch.setattr(first, "_publish_quarantine", hold_publication)
    monkeypatch.setattr(core_module, "file_lock", observe_execution_attempt)
    try:
        first_id = submit(first, "malformed-window-first")
        assert publishing.wait(5)
        assert first.wait(first_id, timeout=5)["state"] == "unknown"
        state_bytes = (first._job_path(first_id) / "state.json").read_bytes()
        assert not (tmp_path / "executor-quarantine.json").exists()
        assert read_json(tmp_path / "executor-active.json")["job_id"] == first_id
        with pytest.raises(TimeoutError), original_lock(tmp_path / ".execution.lock", timeout=0):
            pytest.fail("Unknown state must not release execution before quarantine publication")

        # Admission may queue another job during this window. Its worker must
        # still acquire execution ownership before it can reach the backend.
        second_id = submit(second, "malformed-window-second")
        assert second_waiting.wait(5)
        assert not second.futures[second_id].done()
        assert second_backend.calls == []

        release.set()
        first.futures[first_id].result(timeout=5)
        second.futures[second_id].result(timeout=5)
        assert read_json(tmp_path / "executor-quarantine.json")["job_id"] == first_id
        assert not (tmp_path / "executor-active.json").exists()
        assert (first._job_path(first_id) / "state.json").read_bytes() == state_bytes
        assert second.wait(second_id, timeout=5)["state"] == "failed"
        assert first_backend.calls == [first_id]
        assert second_backend.calls == [], "No second backend dispatch may pass the held barrier"
    finally:
        release.set()
        first.close()
        second.close()


def test_reused_pid_does_not_hide_an_orphaned_dispatch(tmp_path):
    job_id = str(uuid.uuid4())
    job = tmp_path / "jobs" / job_id
    atomic_json(
        job / "state.json",
        JobSummary(
            job_id=job_id,
            operation="first_order_kinetics",
            state="running",
            summary="A different process once used this PID",
        ).model_dump(mode="json"),
    )
    atomic_json(
        job / "dispatch.json",
        {
            "coordinator_pid": os.getpid(),
            "coordinator_identity": {
                "instance_id": str(uuid.uuid4()),
                "process_start": "old-process",
            },
        },
    )
    backend = LostResponseBackend()
    core = Core(tmp_path, backend=backend)
    try:
        state = read_json(job / "state.json")
        assert state["state"] == "unknown"
        assert (tmp_path / "executor-quarantine.json").is_file()
        assert backend.calls == []
    finally:
        core.close()


def test_quarantine_write_failure_retains_a_barrier_for_an_existing_coordinator(
    tmp_path, monkeypatch
):
    import pytest

    first_backend, second_backend = LostResponseBackend(), LostResponseBackend()
    first = Core(tmp_path, backend=first_backend)
    second = Core(tmp_path, backend=second_backend)
    real_atomic = core_module.atomic_json

    def unavailable_quarantine(path, value):
        if path.name == "executor-quarantine.json":
            raise OSError("Simulated failed quarantine persistence")
        return real_atomic(path, value)

    monkeypatch.setattr(core_module, "atomic_json", unavailable_quarantine)
    try:
        job_id = submit(first, "persistence-failure")
        with pytest.raises(OSError, match="quarantine persistence"):
            first.futures[job_id].result(timeout=5)
        active = read_json(tmp_path / "executor-active.json")
        assert active["job_id"] == job_id
        assert active["dispatch_id"]
        assert active["coordinator_identity"]["instance_id"]
        assert active["coordinator_identity"]["process_start"]
        # Restore only the simulated storage outage, not any job or marker.
        monkeypatch.setattr(core_module, "atomic_json", real_atomic)
        next_id = submit(second, "after-persistence-failure")
        assert second.wait(next_id, timeout=5)["state"] == "failed"
        assert second_backend.calls == []
        assert read_json(tmp_path / "executor-quarantine.json")["job_id"] == job_id
    finally:
        first.close()
        second.close()


def test_new_service_recovers_a_crash_barrier_without_replaying(tmp_path):
    # A real child coordinator exits while owning a durable pre-dispatch barrier.
    # The OS releases its lock; no backend or MATLAB process is started.
    job_id = str(uuid.uuid4())
    code = """
import os, sys
from pathlib import Path
from matlab_companion.storage import atomic_json, file_lock, process_start_identity
root, job_id = Path(sys.argv[1]), sys.argv[2]
with file_lock(root / '.execution.lock'):
    atomic_json(root / 'executor-active.json', {
        'job_id': job_id, 'coordinator_pid': os.getpid(),
        'coordinator_identity': {'instance_id': job_id, 'process_start': process_start_identity(os.getpid())},
        'dispatch_id': job_id,
    })
    os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), job_id], timeout=10, check=False
    )
    assert result.returncode == 23
    backend = LostResponseBackend()
    core = Core(tmp_path, backend=backend)
    try:
        assert read_json(tmp_path / "executor-quarantine.json")["job_id"] == job_id
        assert (tmp_path / "executor-active.json").exists()
        rejected = core.call(
            "matlab_run",
            {
                "operation": "first_order_kinetics",
                "parameters": PARAMETERS,
                "idempotency_key": "after-crash",
            },
        )
        assert not rejected["ok"]
        assert backend.calls == []
    finally:
        core.close()


def test_process_incarnation_probe_observes_an_owned_child_without_signalling():
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    try:
        identity = process_start_identity(child.pid)
        assert identity and identity == process_start_identity(child.pid)
        assert identity != process_start_identity(os.getpid())
        assert process_alive(child.pid)
        assert child.poll() is None
    finally:
        child.communicate(timeout=10)
    assert not process_alive(child.pid)
    # Windows may retain a terminated process object while Popen holds its
    # handle. A creation timestamp is identity evidence, not proof of liveness.
    assert process_start_identity(child.pid) in {None, identity}


def test_late_reconciliation_cannot_be_downgraded_by_a_timeout(tmp_path, monkeypatch):
    from test_recovery import ReceiptBackend

    # Use a valid receipt produced by the same portable backend used in the
    # recovery suite; no fabricated native claim escapes this isolated test.
    inputs = tmp_path / "input"
    inputs.mkdir()
    source = inputs / "data.csv"
    source.write_text("concentration,absorbance\n1,3\n2,5\n")
    entered, release = threading.Event(), threading.Event()
    backend = LostResponseBackend(entered, release)
    core = Core(tmp_path / "store", [inputs], backend=backend)
    input_id = core.call("matlab_inspect", {"path": str(source)})["input"]["input_id"]
    result = core.call(
        "matlab_run",
        {
            "operation": "data_profile",
            "input_id": input_id,
            "parameters": {},
            "idempotency_key": "late-receipt",
        },
    )
    assert result["ok"]
    job_id = result["job_id"]
    assert entered.wait(5)
    real_save = core._save_state
    late_backend = ReceiptBackend()

    def reconcile_before_unknown(requested_id, *args, **kwargs):
        if kwargs.get("summary") == "Execution outcome needs reconciliation":
            import asyncio

            asyncio.run(late_backend.execute(core._job_path(job_id)))
            observed = core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
            assert observed["job"]["state"] == "completed"
        return real_save(requested_id, *args, **kwargs)

    monkeypatch.setattr(core, "_save_state", reconcile_before_unknown)
    try:
        release.set()
        core.futures[job_id].result(timeout=5)
        assert core._state(job_id)["state"] == "completed"
        assert (core.root / "executor-quarantine.json").exists()
        assert backend.calls == [job_id]
    finally:
        release.set()
        core.close()


def test_reconcile_finishes_a_manifest_commit_after_transient_storage_failure(
    tmp_path, monkeypatch
):
    from test_recovery import ReceiptBackend

    backend = ReceiptBackend()
    inputs = tmp_path / "input"
    inputs.mkdir()
    source = inputs / "data.csv"
    source.write_text("concentration,absorbance\n1,3\n2,5\n")
    core = Core(tmp_path / "store", [inputs], backend=backend)
    real_atomic = core_module.atomic_json

    def fail_observation(path, value):
        if path.name == "native-observation.json":
            raise OSError("Transient failure after immutable manifest was saved")
        return real_atomic(path, value)

    input_id = core.call("matlab_inspect", {"path": str(source)})["input"]["input_id"]
    monkeypatch.setattr(core_module, "atomic_json", fail_observation)
    try:
        arguments = {
            "operation": "data_profile",
            "input_id": input_id,
            "parameters": {},
            "idempotency_key": "commit-recovery",
        }
        accepted = core.call("matlab_run", arguments)
        assert accepted["ok"]
        job_id = accepted["job_id"]
        core.futures[job_id].result(timeout=5)
        assert core._state(job_id)["state"] == "unknown"
        job = core._job_path(job_id)
        preserved = {
            name: (job / name).read_bytes()
            for name in ("artifacts.json", "request.json", "dispatch.json", "receipt.json")
        }
        monkeypatch.setattr(core_module, "atomic_json", real_atomic)
        result = core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
        assert result["job"]["state"] == "completed"
        assert all((job / name).read_bytes() == value for name, value in preserved.items())
        assert core.call("matlab_run", arguments)["job_id"] == job_id
        assert backend.calls == [job_id]
        assert (core.root / "executor-quarantine.json").exists()
    finally:
        core.close()
