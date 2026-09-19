"""Portable coordinator recovery regressions; no MATLAB process is started.

The fake artifact bytes are intentionally not MAT/FIG files. These tests exercise
the coordinator's response to trusted-backend receipts, not native acceptance.
"""

from __future__ import annotations

import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

import matlab_companion.core as core_module
from matlab_companion.contracts import JobSummary
from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, digest, read_json, utc_now

PROFILE_ARTIFACTS = {
    "input.csv": ("original_input", "text/csv"),
    "analysis.mat": ("native_data", "application/x-matlab-data"),
    "results.csv": ("data_export", "text/csv"),
    "method.json": ("method", "application/json"),
}
FIGURE_ARTIFACTS = {
    "figure.fig": ("native_figure", "application/vnd.mathworks.matlab.fig"),
    "figure.png": ("preview", "image/png"),
    "figure.pdf": ("figure_export", "application/pdf"),
    "reproduce.m": ("script", "text/x-matlab"),
}


class ReceiptBackend:
    def __init__(self, *, numerical: bool = True, omit: str | None = None):
        self.calls: list[str] = []
        self.numerical = numerical
        self.omit = omit

    def available(self) -> bool:
        return True

    async def execute(self, job: Path) -> None:
        request = read_json(job / "request.json")
        self.calls.append(request["job_id"])
        operation = request["operation"]
        is_profile = operation == "data_profile"
        spec = PROFILE_ARTIFACTS | ({} if is_profile else FIGURE_ARTIFACTS)
        artifacts = []
        for name, (role, media_type) in spec.items():
            if name == self.omit:
                continue
            content = b"PORTABLE TEST DOUBLE - not a native MATLAB artifact\n"
            if name == "input.csv":
                content = Path(request["input_path"]).read_bytes()
            elif name == "results.csv":
                content = b"x,y\n1,3\n2,5\n"
            elif name == "method.json":
                content = json.dumps({"test_double": True}).encode()
            (job / "outputs" / name).write_bytes(content)
            artifacts.append({"name": name, "role": role, "media_type": media_type})
        if is_profile:
            details = {
                "rows": 2,
                "columns": [
                    {
                        "name": name,
                        "numeric": True,
                        "finite_count": 2,
                        "missing_count": 0,
                        "nonfinite_count": 0,
                        "minimum": low,
                        "maximum": high,
                    }
                    for name, low, high in [("concentration", 1.0, 2.0), ("absorbance", 3.0, 5.0)]
                ],
            }
        else:
            details = {
                "rows": 2,
                "x_column": "concentration",
                "y_column": "absorbance",
                "x_unit": "mmol/L",
                "y_unit": "1",
            }
        atomic_json(
            job / "receipt.json",
            {
                "contract_version": "1.0",
                "job_id": request["job_id"],
                "operation": operation,
                "state": "completed",
                "observed_at": utc_now(),
                "matlab_version": "portable-test-double",
                "matlab_release": "portable-test-double",
                "summary": "Portable fake backend receipt",
                "metrics": [],
                "artifacts": artifacts,
                "verification": {
                    "native_reopen": True,
                    "numerical": False if is_profile else self.numerical,
                    "script_rerun": not is_profile,
                },
                "details": details,
                "error": None,
            },
        )


@pytest.fixture
def core_factory(tmp_path):
    instances = []

    def factory(backend=None):
        case = tmp_path / str(len(instances))
        inputs = case / "inputs"
        inputs.mkdir(parents=True)
        source = inputs / "experiment.csv"
        source.write_text("concentration,absorbance\n1,3\n2,5\n", encoding="utf-8")
        core = Core(case / "store", [inputs], [case / "delivered"], backend or ReceiptBackend())
        instances.append(core)
        inspected = core.call("matlab_inspect", {"path": str(source)})
        assert inspected["ok"], inspected
        return core, inspected["input"]["input_id"]

    yield factory
    for core in instances:
        core.close()


def run_fake(core, input_id, operation="data_profile"):
    parameters = {}
    if operation == "plot_xy":
        parameters = {
            "x_column": "concentration",
            "y_column": "absorbance",
            "x_unit": "mmol/L",
            "y_unit": "1",
        }
    result = core.call(
        "matlab_run",
        {
            "operation": operation,
            "input_id": input_id,
            "parameters": parameters,
            "idempotency_key": "recovery-regression",
        },
    )
    assert result["ok"], result
    state = core.wait(result["job_id"], timeout=5)
    return result["job_id"], state


def test_completed_figure_tampering_cannot_be_retrusted_by_reconcile(core_factory):
    core, input_id = core_factory()
    job_id, state = run_fake(core, input_id, "plot_xy")
    assert state["state"] == "completed", state
    job = core._job_path(job_id)
    original_manifest = (job / "artifacts.json").read_bytes()
    figure = next(
        record
        for record in read_json(job / "artifacts.json")["artifacts"]
        if record["role"] == "native_figure"
    )
    path = job / "outputs" / figure["name"]
    path.write_bytes(b"Modified bytes must not inherit the previous native verification\n")
    assert digest(path) != figure["sha256"]

    before = core.call(
        "matlab_artifacts",
        {
            "job_id": job_id,
            "action": "read",
            "artifact_id": figure["artifact_id"],
        },
    )
    assert not before["ok"], before
    core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
    assert (job / "artifacts.json").read_bytes() == original_manifest
    after = core.call(
        "matlab_artifacts",
        {
            "job_id": job_id,
            "action": "read",
            "artifact_id": figure["artifact_id"],
        },
    )
    assert not after["ok"], after
    revised = core.call(
        "matlab_run",
        {
            "operation": "revise_figure",
            "parameters": {"title": "Must not execute modified FIG"},
            "idempotency_key": "tampered-figure",
            "source_job_id": job_id,
            "source_artifact_id": figure["artifact_id"],
            "expected_revision": job_id,
        },
    )
    assert not revised["ok"], revised


def test_cancel_cannot_overwrite_a_concurrently_completed_job(core_factory, monkeypatch):
    core, input_id = core_factory()
    job_id, completed = run_fake(core, input_id)
    assert completed["state"] == "completed"
    # Recreate the state immediately before worker completion. The actual fake
    # execution has ended, so only the two explicitly coordinated threads write.
    atomic_json(
        core._job_path(job_id) / "state.json",
        completed
        | {
            "state": "running",
            "summary": "Paused immediately before completion",
            "phase": "executing",
        },
    )
    initial_read = threading.Event()
    resume_cancel = threading.Event()
    completion_done = threading.Event()
    original_state = core._state
    cancel_thread = None
    trapped = False

    def pause_after_cancel_snapshot(requested_id):
        nonlocal trapped
        snapshot = original_state(requested_id)
        if threading.get_ident() == cancel_thread and not trapped:
            trapped = True
            initial_read.set()
            assert resume_cancel.wait(3), "Cancellation interleave did not resume"
        return snapshot

    monkeypatch.setattr(core, "_state", pause_after_cancel_snapshot)

    def cancel():
        nonlocal cancel_thread
        cancel_thread = threading.get_ident()
        return core.call("matlab_job", {"job_id": job_id, "action": "cancel"})

    def complete():
        state = core._save_state(job_id, state="completed", summary="Worker completed")
        completion_done.set()
        return state

    with ThreadPoolExecutor(max_workers=2) as threads:
        cancel_future = threads.submit(cancel)
        try:
            assert initial_read.wait(3), "Cancellation did not read the initial state"
            complete_future = threads.submit(complete)
            # With atomic cancellation, completion may wait behind its lock.
            # With split read/write, it finishes here and exposes the old race.
            completion_done.wait(0.2)
        finally:
            resume_cancel.set()
        cancel_result = cancel_future.result(timeout=3)
        complete_future.result(timeout=3)
    assert cancel_result["ok"], cancel_result
    assert original_state(job_id)["state"] == "completed"


def test_nonprofile_receipt_without_numerical_verification_cannot_complete(core_factory):
    core, input_id = core_factory(ReceiptBackend(numerical=False))
    _, state = run_fake(core, input_id, "plot_xy")
    assert state["state"] in {"failed", "unknown"}, state
    assert state["error"] is not None


@pytest.mark.parametrize("missing", list(PROFILE_ARTIFACTS))
def test_profile_receipt_requires_its_complete_native_bundle(core_factory, missing):
    core, input_id = core_factory(ReceiptBackend(omit=missing))
    _, state = run_fake(core, input_id)
    assert state["state"] in {"failed", "unknown"}, state
    assert state["error"] is not None


@pytest.mark.parametrize("missing", list(FIGURE_ARTIFACTS))
def test_plot_receipt_requires_its_complete_native_bundle(core_factory, missing):
    core, input_id = core_factory(ReceiptBackend(omit=missing))
    _, state = run_fake(core, input_id, "plot_xy")
    assert state["state"] in {"failed", "unknown"}, state
    assert state["error"] is not None


def test_dead_dispatched_owner_becomes_unknown_without_replay(tmp_path, monkeypatch):
    store = tmp_path / "store"
    job_id = str(uuid.uuid4())
    job = store / "jobs" / job_id
    (job / "outputs").mkdir(parents=True)
    state = JobSummary(
        job_id=job_id,
        operation="first_order_kinetics",
        state="running",
        summary="Persisted dispatched job whose coordinator has ended",
    ).model_dump(mode="json")
    atomic_json(job / "state.json", state)
    atomic_json(
        job / "dispatch.json",
        {
            "coordinator_pid": 999_999,
            "coordinator_identity": None,
            "dispatched_at": utc_now(),
        },
    )
    parameters = {
        "initial_concentration": 1.0,
        "rate_constant": 0.1,
        "time_end": 10.0,
        "points": 101,
        "concentration_unit": "mmol/L",
        "time_unit": "s",
        "title": "",
    }
    atomic_json(
        job / "request.json",
        {
            "contract_version": "1.0",
            "job_id": job_id,
            "operation": "first_order_kinetics",
            "parameters": parameters,
            "input_path": None,
            "output_dir": str(job / "outputs"),
            "cancel_path": str(job / "cancel.flag"),
        },
    )
    # The root implementation imports the OS liveness probe into core. The
    # fake dead owner is deterministic and never sends signals to real PIDs.
    monkeypatch.setattr(core_module, "process_alive", lambda pid: False, raising=False)
    backend = ReceiptBackend()
    core = Core(store, backend=backend)
    try:
        recovered = core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
        assert recovered["ok"], recovered
        assert recovered["job"]["state"] == "unknown", recovered
        assert recovered["job"]["error"]["code"] == "OUTCOME_UNKNOWN"
        assert backend.calls == []
        assert (store / "executor-quarantine.json").is_file()
        rejected = core.call(
            "matlab_run",
            {
                "operation": "first_order_kinetics",
                "parameters": parameters,
                "idempotency_key": "must-wait-for-owned-executor-recovery",
            },
        )
        assert not rejected["ok"], rejected
        assert backend.calls == []
    finally:
        core.close()


def test_recovery_finishes_commit_after_manifest_was_saved(core_factory, monkeypatch):
    backend = ReceiptBackend()
    core, input_id = core_factory(backend)
    job_id, completed = run_fake(core, input_id, "plot_xy")
    assert completed["state"] == "completed"
    core.close()
    job = core._job_path(job_id)
    committed_manifest = (job / "artifacts.json").read_bytes()
    committed_result = (job / "result.json").read_bytes()
    native_receipt = (job / "receipt.json").read_bytes()
    figure = next(
        artifact
        for artifact in read_json(job / "artifacts.json")["artifacts"]
        if artifact["role"] == "native_figure"
    )
    # Emulate the durable state at a coordinator crash between committing the
    # artifact manifest/result and committing the final completed job state.
    atomic_json(
        job / "state.json",
        completed
        | {
            "state": "running",
            "summary": "Coordinator stopped between manifest and final state commits",
            "phase": "validating",
        },
    )
    atomic_json(
        job / "dispatch.json",
        {
            "coordinator_pid": 999_999,
            "coordinator_identity": None,
            "dispatched_at": utc_now(),
        },
    )
    monkeypatch.setattr(core_module, "process_alive", lambda pid: False, raising=False)
    recovered_core = Core(core.root, core.allowed_roots, core.output_roots, backend=backend)
    try:
        reconciled = recovered_core.call("matlab_job", {"job_id": job_id, "action": "reconcile"})
        assert reconciled["ok"], reconciled
        assert reconciled["job"]["state"] == "completed", reconciled
        assert reconciled["job"]["error"] is None
        assert reconciled["job"]["verification"] == completed["verification"]
        assert (job / "artifacts.json").read_bytes() == committed_manifest
        assert (job / "result.json").read_bytes() == committed_result
        assert (job / "receipt.json").read_bytes() == native_receipt
        record, path = recovered_core.artifact_path(job_id, figure["artifact_id"])
        assert record["sha256"] == figure["sha256"] == digest(path)
        assert backend.calls == [job_id], "Recovery must not execute the original write again"
    finally:
        recovered_core.close()


def test_registration_and_recovery_cannot_dispatch_one_job_twice(core_factory, monkeypatch):
    backend = ReceiptBackend()
    core, input_id = core_factory(backend)
    queued_written = threading.Event()
    finish_registration = threading.Event()
    recovery_started = threading.Event()
    recovery_finished = threading.Event()
    real_atomic = core_module.atomic_json
    intercepted = False

    def pause_registration(path, value):
        nonlocal intercepted
        real_atomic(path, value)
        if not intercepted and path.name == "state.json" and value.get("state") == "queued":
            intercepted = True
            queued_written.set()
            assert finish_registration.wait(3), "Registration interleave did not resume"

    monkeypatch.setattr(core_module, "atomic_json", pause_registration)

    def open_second_coordinator():
        recovery_started.set()
        other = Core(core.root, core.allowed_roots, core.output_roots, backend)
        recovery_finished.set()
        return other

    second = None
    with ThreadPoolExecutor(max_workers=2) as threads:
        submitted = threads.submit(
            core.call,
            "matlab_run",
            {
                "operation": "data_profile",
                "parameters": {},
                "input_id": input_id,
                "idempotency_key": "registration-recovery-interleave",
            },
        )
        try:
            assert queued_written.wait(3)
            opening = threads.submit(open_second_coordinator)
            assert recovery_started.wait(3)
            # The second coordinator must not recover the partially published
            # request. Finishing registration releases the common recovery lock.
            recovery_finished.wait(0.2)
            finish_registration.set()
            accepted = submitted.result(timeout=5)
            second = opening.result(timeout=5)
            assert accepted["ok"], accepted
            state = core.wait(accepted["job_id"], timeout=5)
            assert state["state"] == "completed", state
            core.close()
            second.close()
            assert backend.calls == [accepted["job_id"]]
        finally:
            finish_registration.set()
            if second is not None:
                second.close()


def test_an_already_completed_job_cannot_be_dispatched_again(core_factory):
    backend = ReceiptBackend()
    core, input_id = core_factory(backend)
    job_id, state = run_fake(core, input_id)
    assert state["state"] == "completed"
    core._execute(job_id)
    assert backend.calls == [job_id]
    assert core._state(job_id)["state"] == "completed"


def test_normal_backend_return_without_receipt_becomes_unknown(core_factory):
    class MissingReceiptBackend(ReceiptBackend):
        async def execute(self, job):
            self.calls.append(read_json(job / "request.json")["job_id"])

    backend = MissingReceiptBackend()
    core, input_id = core_factory(backend)
    job_id, state = run_fake(core, input_id)
    assert state["state"] == "unknown", state
    assert state["error"]["code"] == "OUTCOME_UNKNOWN"
    job = core._job_path(job_id)
    assert (job / "dispatch.json").is_file()
    assert (job / "request.json").is_file()
    assert (job / "cancel.flag").is_file()
    assert (core.root / "executor-quarantine.json").is_file()
    duplicate, repeated_state = run_fake(core, input_id)
    assert duplicate == job_id
    assert repeated_state["state"] == "unknown"
    assert backend.calls == [job_id]


def test_queued_registration_recovers_its_missing_idempotency_index(core_factory, monkeypatch):
    backend = ReceiptBackend()
    core, input_id = core_factory(backend)
    real_atomic = core_module.atomic_json

    def stop_before_index_commit(path, value):
        if path == core.root / "idempotency.json":
            raise OSError("Simulated coordinator stop before index commit")
        return real_atomic(path, value)

    arguments = {
        "operation": "data_profile",
        "parameters": {},
        "input_id": input_id,
        "idempotency_key": "persisted-registration-intent",
    }
    monkeypatch.setattr(core_module, "atomic_json", stop_before_index_commit)
    interrupted = core.call("matlab_run", arguments)
    assert not interrupted["ok"]
    core.close()
    assert backend.calls == []
    job = next((core.root / "jobs").iterdir())
    scheduler = read_json(job / "scheduler.json")
    atomic_json(job / "scheduler.json", scheduler | {"coordinator_pid": 999_999})
    monkeypatch.setattr(core_module, "atomic_json", real_atomic)
    monkeypatch.setattr(core_module, "process_alive", lambda pid: pid != 999_999)
    recovered = Core(core.root, core.allowed_roots, core.output_roots, backend)
    try:
        state = recovered.wait(job.name, timeout=5)
        assert state["state"] == "completed", state
        retry = recovered.call("matlab_run", arguments)
        assert retry["ok"] and retry["job_id"] == job.name, retry
        assert backend.calls == [job.name]
    finally:
        recovered.close()


def test_execution_lock_timeout_does_not_quarantine_an_undispatched_job(core_factory, monkeypatch):
    backend = ReceiptBackend()
    core, input_id = core_factory(backend)
    real_lock = core_module.file_lock

    @contextmanager
    def contend_execution_lock(path, timeout=0):
        if path.name == ".execution.lock":
            raise TimeoutError("Simulated execution-lock contention deadline")
        with real_lock(path, timeout=timeout):
            yield

    monkeypatch.setattr(core_module, "file_lock", contend_execution_lock)
    job_id, state = run_fake(core, input_id)
    job = core._job_path(job_id)
    assert state["state"] == "failed", state
    assert state["error"]["code"] == "EXECUTOR_BUSY"
    assert backend.calls == []
    assert not (job / "dispatch.json").exists()
    assert not (job / "cancel.flag").exists()
    assert not (core.root / "executor-quarantine.json").exists()
    monkeypatch.setattr(core_module, "file_lock", real_lock)
    next_job = core.call(
        "matlab_run",
        {
            "operation": "data_profile",
            "parameters": {},
            "input_id": input_id,
            "idempotency_key": "after-execution-lock-contention",
        },
    )
    assert next_job["ok"], next_job
    assert core.wait(next_job["job_id"], timeout=5)["state"] == "completed"
    assert backend.calls == [next_job["job_id"]]


def test_execution_lock_failure_keeps_an_existing_dispatch_unknown(core_factory, monkeypatch):
    backend = ReceiptBackend()
    core, _ = core_factory(backend)
    job_id = str(uuid.uuid4())
    job = core._job_path(job_id)
    (job / "outputs").mkdir(parents=True)
    atomic_json(
        job / "state.json",
        JobSummary(
            job_id=job_id,
            operation="data_profile",
            state="running",
            summary="Earlier native dispatch has no confirmed receipt",
        ).model_dump(mode="json"),
    )
    atomic_json(
        job / "dispatch.json",
        {"coordinator_pid": 999_999, "coordinator_identity": None, "dispatched_at": utc_now()},
    )
    dispatch = (job / "dispatch.json").read_bytes()
    real_lock = core_module.file_lock

    @contextmanager
    def contend_execution_lock(path, timeout=0):
        if path.name == ".execution.lock":
            raise TimeoutError("Simulated contention with an existing dispatch")
        with real_lock(path, timeout=timeout):
            yield

    monkeypatch.setattr(core_module, "file_lock", contend_execution_lock)
    core._execute(job_id)
    state = core._state(job_id)
    assert state["state"] == "unknown", state
    assert state["error"]["code"] == "OUTCOME_UNKNOWN"
    assert (job / "dispatch.json").read_bytes() == dispatch
    assert (job / "cancel.flag").is_file()
    assert (core.root / "executor-quarantine.json").is_file()
    assert backend.calls == []
    monkeypatch.setattr(core_module, "file_lock", real_lock)
    core._execute(job_id)
    assert core._state(job_id)["state"] == "unknown"
    assert backend.calls == []


@pytest.mark.parametrize("after_ready_replace", [False, True])
def test_startup_ready_failure_cannot_release_recovering_core_or_replay_job(
    core_factory, monkeypatch, after_ready_replace
):
    """Real Core recovers one queued job; only its backend artifacts are fake."""
    import asyncio
    from types import SimpleNamespace

    from matlab_companion import coordinator as coordinator_module
    from matlab_companion.client import CoordinatorClient
    from matlab_companion.core import WorkflowError
    from matlab_companion.storage import file_lock

    original, input_id = core_factory()
    real_atomic = core_module.atomic_json

    def stop_before_index(path, value):
        if path == original.root / "idempotency.json":
            raise OSError("Injected interruption before queue index commit")
        real_atomic(path, value)

    arguments = {
        "operation": "data_profile",
        "parameters": {},
        "input_id": input_id,
        "idempotency_key": "startup-recovery-once",
    }
    monkeypatch.setattr(core_module, "atomic_json", stop_before_index)
    assert not original.call("matlab_run", arguments)["ok"]
    original.close()
    job = next((original.root / "jobs").iterdir())
    atomic_json(
        job / "scheduler.json", read_json(job / "scheduler.json") | {"coordinator_pid": 999_999}
    )
    monkeypatch.setattr(core_module, "atomic_json", real_atomic)
    old_alive = core_module.process_alive
    monkeypatch.setattr(
        core_module, "process_alive", lambda pid: False if pid == 999_999 else old_alive(pid)
    )
    entered, release, closing = threading.Event(), threading.Event(), threading.Event()
    counts = {"popen": 0, "core": 0, "fake_dispatch": 0}
    failures = []
    order = []

    class BlockedReceipt(ReceiptBackend):
        async def execute(self, job):
            counts["fake_dispatch"] += 1
            entered.set()
            for _ in range(1200):
                if release.is_set():
                    break
                await asyncio.sleep(0.025)
            else:
                raise TimeoutError("The harmless backend release was not observed")
            await super().execute(job)

    class ObservedCore(Core):
        def __init__(self, *args, **kwargs):
            counts["core"] += 1
            super().__init__(*args, **kwargs)

        def close(self):
            order.append("close_entered")
            closing.set()
            with file_lock(original.root / ".coordinator-start.lock", timeout=0):
                pass
            with (
                pytest.raises(TimeoutError),
                file_lock(original.root / ".coordinator.lock", timeout=0),
            ):
                pytest.fail("Lifetime lock released before real Core settlement")
            super().close()
            order.append("close_finished")

    def forbid_spawn(*args, **kwargs):
        counts["popen"] += 1
        raise AssertionError("An unready recovery owner must not be replaced")

    def fail_ready(path, value):
        if path.name == "coordinator.json":
            assert entered.wait(5), "The real recovery worker never entered the fake backend"
            if after_ready_replace:
                real_atomic(path, value)
            raise OSError("Injected readiness publication failure after recovery dispatch")
        real_atomic(path, value)

    monkeypatch.setattr(coordinator_module, "Core", ObservedCore)
    monkeypatch.setattr(coordinator_module, "atomic_json", fail_ready)
    monkeypatch.setattr("matlab_companion.client.spawn_coordinator", forbid_spawn)
    clock = [0.0]
    monkeypatch.setattr(
        "matlab_companion.client.time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ),
    )
    backend = BlockedReceipt()
    owner = coordinator_module.Coordinator(
        original.root, original.allowed_roots, original.output_roots, backend=backend
    )

    def run():
        try:
            owner.run()
        except OSError as error:
            failures.append(error)
        finally:
            order.append("lifetime_released")

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(5)
        assert closing.wait(5)
        with pytest.raises(WorkflowError) as error:
            CoordinatorClient(
                original.root, original.allowed_roots, original.output_roots
            )._ensure()
        assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
        assert counts == {"popen": 0, "core": 1, "fake_dispatch": 1}
        assert worker.is_alive()
        assert not (job / "cancel.flag").exists()
        assert read_json(original.root / "coordinator-start.json")["phase"] == "stopping"
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert len(failures) == 1 and "readiness publication" in str(failures[0])
    assert order == ["close_entered", "close_finished", "lifetime_released"]
    assert read_json(job / "state.json")["state"] == "completed"
    assert backend.calls == [job.name]
    assert counts == {"popen": 0, "core": 1, "fake_dispatch": 1}
    with file_lock(original.root / ".coordinator.lock", timeout=0):
        pass
