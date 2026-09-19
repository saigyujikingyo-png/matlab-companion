"""Exit evidence is independent of response, cancellation and reused PIDs."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from matlab_companion import native_session
from matlab_companion.backend import OfficialBackend
from matlab_companion.native_session import NativeSessionUnconfirmed, NativeSessionWatcher
from matlab_companion.storage import atomic_json, read_json


class FakeProcess:
    def __init__(self, executable: Path):
        self.identity = {
            "pid": 1234,
            "process_start": "windows-filetime:owned-test-process",
            "created_at_ns": time.time_ns(),
            "executable": str(executable.resolve()),
        }
        self.has_exited = False
        self.closed = False

    def exited(self):
        return self.has_exited

    def close(self):
        self.closed = True


@pytest.fixture
def owned(tmp_path, monkeypatch):
    job = tmp_path / str(uuid.uuid4())
    job.mkdir()
    installation = tmp_path / "MATLAB"
    nonce = str(uuid.uuid4())
    watcher = NativeSessionWatcher(job, nonce)
    process = FakeProcess(installation / "bin" / "win64" / "MATLAB.exe")
    monkeypatch.setattr(native_session, "observation_supported", lambda: True)
    monkeypatch.setattr(native_session, "WindowsProcess", lambda pid: process)
    monkeypatch.setattr(native_session, "POLL_INTERVAL", 0.001)
    marker = {
        "contract_version": "1.0",
        "job_id": job.name,
        "session_id": nonce,
        "matlab_pid": process.identity["pid"],
    }
    return job, installation, watcher, process, marker


@pytest.mark.skipif(os.name != "nt", reason="Windows held-handle oracle")
def test_owned_short_process_handle_records_actual_exit():
    # Use the real interpreter, not the venv redirector's different child PID.
    child = subprocess.Popen(
        [sys._base_executable, "-I", "-B", "-c", "import time; time.sleep(0.5)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    observed = None
    try:
        observed = native_session.WindowsProcess(child.pid)
        original = dict(observed.identity)
        assert original["pid"] == child.pid
        assert original["created_at_ns"] > 0
        assert Path(original["executable"]).resolve() == Path(sys._base_executable).resolve()
        assert observed.exited() is False
        assert child.wait(timeout=5) == 0
        assert observed.exited() is True
        assert observed.identity == original
    finally:
        if observed:
            observed.close()
        if child.poll() is None:
            child.terminate()  # Exact short process created by this test, never MATLAB.
            child.wait(timeout=5)


def test_response_and_exit_are_independent_observations(owned):
    job, installation, watcher, process, marker = owned

    async def exercise():
        watcher.begin()
        watcher.start(installation)
        atomic_json(job / "native-session.json", marker)
        await asyncio.sleep(0.01)
        watcher.rpc_response_observed()
        intermediate = read_json(job / "native-lifecycle.json")
        assert intermediate["rpc_response_observed"] is True
        assert intermediate["backend_returned"] is False
        assert intermediate["native_exited"] is False
        process.has_exited = True
        final = await watcher.finish(backend_returned=True, timeout=0.1)
        assert final["native_exited"] is True
        assert final["backend_returned"] is True
        assert final["reason_code"] is None
        assert process.closed

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", str(uuid.uuid4())),
        ("job_id", str(uuid.uuid4())),
        ("matlab_pid", True),
        ("matlab_pid", None),
        ("matlab_pid", 0),
    ],
)
def test_wrong_launcher_identity_never_authorizes_process_observation(owned, field, value):
    job, installation, watcher, process, marker = owned
    marker[field] = value

    async def exercise():
        watcher.begin()
        watcher.start(installation)
        atomic_json(job / "native-session.json", marker)
        # This case asserts identity rejection, not a 100 ms scheduling budget.
        # Wait for the same fake observer; dedicated timeout cases remain separate.
        await asyncio.wait_for(asyncio.shield(watcher.task), timeout=5)
        result = await watcher.finish(backend_returned=True, timeout=0.1)
        assert result["native_exited"] is None
        assert result["native_identity"] is None
        assert result["reason_code"] == "NATIVE_IDENTITY_REJECTED"
        assert not process.closed  # The mismatching marker was rejected before opening a handle.

    asyncio.run(exercise())


@pytest.mark.parametrize("mismatch", ["preexisting", "reused_pid", "executable"])
def test_existing_or_reused_process_cannot_inherit_ownership(owned, mismatch):
    job, installation, watcher, process, marker = owned

    async def exercise():
        watcher.begin()
        watcher.start(installation)
        atomic_json(job / "native-session.json", marker)
        if mismatch == "preexisting":
            process.identity["created_at_ns"] = watcher.started_ns - 1_000_000_000
        elif mismatch == "reused_pid":
            process.identity["created_at_ns"] = time.time_ns() + 1_000_000_000
        else:
            process.identity["executable"] = str(installation / "another.exe")
        process.has_exited = True
        # This case asserts identity rejection, not a 100 ms scheduling budget.
        # Wait for the same fake observer; dedicated timeout cases remain separate.
        await asyncio.wait_for(asyncio.shield(watcher.task), timeout=5)
        result = await watcher.finish(backend_returned=True, timeout=0.1)
        assert result["native_exited"] is None
        assert result["reason_code"] == "NATIVE_IDENTITY_REJECTED"
        assert process.closed

    asyncio.run(exercise())


def test_denied_observation_is_not_native_stop(owned, monkeypatch):
    job, installation, watcher, _, marker = owned

    def denied(pid):
        raise PermissionError("Access denied to native process")

    monkeypatch.setattr(native_session, "WindowsProcess", denied)

    async def exercise():
        watcher.begin()
        watcher.start(installation)
        atomic_json(job / "native-session.json", marker)
        result = await watcher.finish(
            backend_returned=False, backend_error_type="TimeoutError", timeout=0.1
        )
        assert result["native_exited"] is None
        assert result["backend_returned"] is False
        assert result["backend_error_type"] == "TimeoutError"
        assert result["reason_code"] == "NATIVE_OBSERVATION_UNAVAILABLE"

    asyncio.run(exercise())


@pytest.mark.parametrize("marker_present", [True, False])
def test_bounded_wait_preserves_unconfirmed_exit(owned, marker_present):
    job, installation, watcher, process, marker = owned

    async def exercise():
        watcher.begin()
        watcher.start(installation)
        if marker_present:
            atomic_json(job / "native-session.json", marker)
        result = await watcher.finish(backend_returned=True, timeout=0.01)
        assert result["native_exited"] is (False if marker_present else None)
        assert result["reason_code"] == (
            "NATIVE_EXIT_UNCONFIRMED" if marker_present else "NATIVE_IDENTITY_UNOBSERVED"
        )
        assert process.closed == marker_present
        assert watcher.task.done()

    asyncio.run(exercise())


def test_unsupported_observer_prevents_native_rpc(owned, monkeypatch):
    _job, installation, watcher, _, _ = owned
    monkeypatch.setattr(native_session, "observation_supported", lambda: False)

    async def exercise():
        watcher.begin()
        with pytest.raises(NativeSessionUnconfirmed):
            watcher.start(installation)
        result = await watcher.finish(backend_returned=False)
        assert result["reason_code"] == "NATIVE_OBSERVATION_UNSUPPORTED"
        assert result["native_exited"] is None
        assert watcher.task is None

    asyncio.run(exercise())


@pytest.mark.parametrize("transport_error", [False, True])
def test_backend_never_returns_normally_without_exit_and_keeps_original_error(
    owned, monkeypatch, transport_error
):
    job, installation, _, process, _ = owned
    monkeypatch.setattr(native_session, "MAX_EXIT_WAIT", 0.01)

    class OriginalTransportFailure(RuntimeError):
        pass

    original = OriginalTransportFailure("The original transport failure")

    class ObservedBackend(OfficialBackend):
        async def _execute(self, job, session_id, watcher):
            watcher.start(installation)
            process.identity["created_at_ns"] = time.time_ns()
            atomic_json(
                job / "native-session.json",
                {
                    "contract_version": "1.0",
                    "job_id": job.name,
                    "session_id": session_id,
                    "matlab_pid": process.identity["pid"],
                },
            )
            if transport_error:
                raise original
            watcher.rpc_response_observed()

    expected = OriginalTransportFailure if transport_error else NativeSessionUnconfirmed
    with pytest.raises(expected) as raised:
        asyncio.run(ObservedBackend(job.parent).execute(job))
    if transport_error:
        assert raised.value is original
    result = read_json(job / "native-lifecycle.json")
    assert result["backend_returned"] is not transport_error
    assert result["rpc_response_observed"] is not transport_error
    assert result["native_exited"] is False
    assert process.closed


@pytest.mark.parametrize("later_failure", [None, RuntimeError, asyncio.CancelledError])
def test_confirmed_exit_preserves_response_and_later_failure_separately(owned, later_failure):
    job, installation, _, process, _ = owned
    original = later_failure("After an actual RPC response") if later_failure else None

    class ObservedBackend(OfficialBackend):
        async def _execute(self, job, session_id, watcher):
            watcher.start(installation)
            process.identity["created_at_ns"] = time.time_ns()
            atomic_json(
                job / "native-session.json",
                {
                    "contract_version": "1.0",
                    "job_id": job.name,
                    "session_id": session_id,
                    "matlab_pid": process.identity["pid"],
                },
            )
            watcher.rpc_response_observed()
            process.has_exited = True
            if original:
                raise original

    if later_failure:
        with pytest.raises(later_failure) as raised:
            asyncio.run(ObservedBackend(job.parent).execute(job))
        assert raised.value is original
    else:
        assert asyncio.run(ObservedBackend(job.parent).execute(job)) is None
    result = read_json(job / "native-lifecycle.json")
    assert result["native_exited"] is True
    assert result["rpc_response_observed"] is True
    assert result["backend_returned"] is (later_failure is None)
    assert result["backend_error_type"] == (later_failure.__name__ if later_failure else None)
    assert process.closed


def test_failure_before_native_call_still_has_a_private_lifecycle_record(tmp_path, monkeypatch):
    monkeypatch.setattr(native_session, "observation_supported", lambda: True)
    job = tmp_path / str(uuid.uuid4())
    job.mkdir()
    with pytest.raises(FileNotFoundError):
        asyncio.run(OfficialBackend(tmp_path).execute(job))
    result = read_json(job / "native-lifecycle.json")
    assert result["backend_returned"] is False
    assert result["rpc_response_observed"] is False
    assert result["native_exited"] is None
    assert result["backend_error_type"] == "FileNotFoundError"
    assert result["reason_code"] == "NATIVE_CALL_NOT_STARTED"


def test_unsupported_platform_rejects_before_starting_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(native_session, "observation_supported", lambda: False)
    job = tmp_path / str(uuid.uuid4())
    job.mkdir()

    async def forbidden(*args):
        raise AssertionError("Unsupported observation must not initialize the native backend")

    monkeypatch.setattr(OfficialBackend, "_execute", forbidden)
    with pytest.raises(NativeSessionUnconfirmed, match="unsupported"):
        asyncio.run(OfficialBackend(tmp_path).execute(job))
    result = read_json(job / "native-lifecycle.json")
    assert result["reason_code"] == "NATIVE_OBSERVATION_UNSUPPORTED"
    assert result["native_exited"] is None
    assert result["rpc_response_observed"] is False


def test_unsupported_platform_does_not_admit_scientific_job(tmp_path, monkeypatch):
    from matlab_companion.core import Core
    from matlab_companion.diagnostics import passive_status

    monkeypatch.setattr(native_session, "observation_supported", lambda: False)
    monkeypatch.setattr(OfficialBackend, "available", lambda self: True)
    core = Core(tmp_path)
    try:
        result = core.call(
            "matlab_run",
            {
                "operation": "first_order_kinetics",
                "parameters": {
                    "initial_concentration": 1,
                    "rate_constant": 0.1,
                    "time_end": 10,
                    "points": 10,
                    "concentration_unit": "mmol/L",
                    "time_unit": "s",
                },
                "idempotency_key": "unsupported-platform",
            },
        )
        assert not result["ok"]
        assert result["error"]["code"] == "CAPABILITY_UNSUPPORTED"
        assert result["job_id"] is None
        assert list((tmp_path / "jobs").iterdir()) == []
        assert not (tmp_path / "executor-active.json").exists()
        assert not (tmp_path / "idempotency.json").exists()
        status = passive_status(tmp_path)
        assert status["backend"]["state"] == "unsupported"
        assert all(item["state"] == "unsupported" for item in status["capabilities"])
    finally:
        core.close()
