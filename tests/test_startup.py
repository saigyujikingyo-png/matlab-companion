"""Harmless startup ownership regressions; no MATLAB or scientific dispatch."""

import os
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from matlab_companion import __version__, coordinator
from matlab_companion import startup as startup_module
from matlab_companion.client import CoordinatorClient
from matlab_companion.coordinator import PROTOCOL_VERSION, Coordinator, resolved_configuration
from matlab_companion.core import WorkflowError
from matlab_companion.startup import Observation, Startup, StartupError, observe
from matlab_companion.storage import atomic_json, file_lock, read_json


def test_unconfirmed_start_is_not_spawned_again_by_next_client(tmp_path, monkeypatch):
    launches = []
    clock = [0.0]

    def spawn(*args, **kwargs):
        launches.append(kwargs)
        return SimpleNamespace(pid=123456789, poll=lambda: None)

    monkeypatch.setattr("matlab_companion.client.spawn_coordinator", spawn)
    monkeypatch.setattr(
        "matlab_companion.client.time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ),
    )
    for _ in range(2):
        with pytest.raises(WorkflowError) as error:
            CoordinatorClient(tmp_path)._ensure()
        assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
    # The first possible spawn remains unconfirmed across frontend calls.
    assert len(launches) == 1


def manager(root):
    _, fingerprint = resolved_configuration(root)
    return Startup(root, fingerprint, __version__, PROTOCOL_VERSION)


def fast_client_clock(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(
        "matlab_companion.client.time",
        SimpleNamespace(
            monotonic=lambda: clock[0],
            sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        ),
    )


@pytest.fixture
def harmless(monkeypatch):
    counts = {"popen": 0, "core": 0, "fake_dispatch": 0, "close": 0, "reaper": 0}
    events = []
    children = []

    def popen(*args, **kwargs):
        counts["popen"] += 1
        events.append("popen")
        child = SimpleNamespace(pid=os.getpid(), wait=lambda: 0, poll=lambda: None)
        children.append(child)
        return child

    class Reaper:
        def __init__(self, **kwargs):
            self.target = kwargs["target"]

        def start(self):
            counts["reaper"] += 1
            events.append("reaper")
            # The Popen fixture is this test process; it has no actual child.

    class Listener:
        def __init__(self, *args, **kwargs):
            self.endpoint = SimpleNamespace(kind="unix", address="fixture-only")

        def close(self):
            events.append("listener_close")

    class FakeCore:
        def __init__(self, root, *args, **kwargs):
            self.root = Path(root)
            counts["core"] += 1
            counts["fake_dispatch"] += 1
            events.append("core")
            assert_locks_during_core(self.root)

        def has_active_work(self):
            return False

        def close(self):
            assert_locks_during_core(self.root)
            counts["close"] += 1
            events.append("core_close")

    monkeypatch.setattr(coordinator.subprocess, "Popen", popen)
    monkeypatch.setattr(
        coordinator,
        "threading",
        SimpleNamespace(
            Thread=Reaper, Lock=threading.Lock, BoundedSemaphore=threading.BoundedSemaphore
        ),
    )
    monkeypatch.setattr(coordinator, "LocalListener", Listener)
    monkeypatch.setattr(coordinator, "Core", FakeCore)
    fast_client_clock(monkeypatch)
    yield counts, events, children
    for key, child in list(coordinator._launches.items()):
        if child in children:
            coordinator._launches.pop(key)


def assert_locks_during_core(root):
    with file_lock(root / ".coordinator-start.lock", timeout=0):
        pass
    with pytest.raises(TimeoutError), file_lock(root / ".coordinator.lock", timeout=0):
        pytest.fail("Lifetime ownership was released before Core settlement")


def launch_intent(startup):
    with startup.locked():
        attempt = startup.intent()
        attempt = startup.update(
            attempt, phase="spawn_requested", last_observation="spawn_requested"
        )
        coordinator.spawn_coordinator(startup.root, startup=startup, attempt=attempt)
        return startup.read()


def fake_owner(startup, attempt_id):
    owner = Coordinator(startup.root, startup_attempt_id=attempt_id, idle_seconds=0.1)
    owner.last_request = -1
    return owner


def assert_counts(harmless, *, popen, core=0, fake_dispatch=0, close=0):
    counts = harmless[0]
    assert {key: counts[key] for key in ("popen", "core", "fake_dispatch", "close")} == {
        "popen": popen,
        "core": core,
        "fake_dispatch": fake_dispatch,
        "close": close,
    }


@pytest.mark.parametrize("phase", ["intent", "spawn_requested"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_parent_publication_fault_never_authorizes_ambiguous_second_launch(
    tmp_path, monkeypatch, harmless, phase, after_replace
):
    real_atomic = startup_module.atomic_json

    def fail(path, value):
        if path.name == "coordinator-start.json" and value["phase"] == phase:
            if after_replace:
                real_atomic(path, value)
            raise OSError("Injected durable publication failure")
        real_atomic(path, value)

    monkeypatch.setattr(startup_module, "atomic_json", fail)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=0)
    startup = manager(tmp_path)
    previous = startup.read()
    monkeypatch.setattr(startup_module, "atomic_json", real_atomic)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=0 if previous else 1)
    if previous:
        assert startup.read().attempt_id == previous.attempt_id


@pytest.mark.parametrize("after_replace", [False, True])
def test_launcher_publication_fault_preserves_returned_child_before_reaper(
    tmp_path, monkeypatch, harmless, after_replace
):
    real_atomic = startup_module.atomic_json

    def fail(path, value):
        if path.name == "coordinator-start.json" and value["launcher"] is not None:
            if after_replace:
                real_atomic(path, value)
            raise OSError("Injected returned-launcher publication failure")
        real_atomic(path, value)

    monkeypatch.setattr(startup_module, "atomic_json", fail)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    startup = manager(tmp_path)
    attempt = startup.read()
    assert coordinator._launches[attempt.attempt_id] is harmless[2][0]
    assert harmless[1] == ["popen", "reaper"]
    monkeypatch.setattr(startup_module, "atomic_json", real_atomic)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert startup.read().attempt_id == attempt.attempt_id
    assert_counts(harmless, popen=1)


@pytest.mark.parametrize("window", ["construct", "start"])
def test_reaper_creation_failure_keeps_popen_and_durable_launcher(
    tmp_path, monkeypatch, harmless, window
):
    class FailedReaper:
        def __init__(self, **kwargs):
            if window == "construct":
                raise RuntimeError("Injected thread construction failure")

        def start(self):
            raise RuntimeError("Injected thread start failure")

    monkeypatch.setattr(coordinator.threading, "Thread", FailedReaper)
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    attempt = manager(tmp_path).read()
    assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
    assert attempt.attempt_id in error.value.message
    assert attempt.launcher.pid == os.getpid()
    assert coordinator._launches[attempt.attempt_id] is harmless[2][0]
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=1)


def test_creation_exception_has_no_fallback_or_cross_call_retry(tmp_path, monkeypatch, harmless):
    def denied(*args, **kwargs):
        harmless[0]["popen"] += 1
        raise OSError(13, "Injected breakaway denial")

    monkeypatch.setattr(coordinator.subprocess, "Popen", denied)
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    attempt = manager(tmp_path).read()
    assert error.value.code == "COORDINATOR_START_BLOCKED"
    assert attempt.attempt_id in error.value.message
    assert attempt.phase == "spawn_requested" and attempt.launcher is None
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=1)


@pytest.mark.parametrize("phase", ["owner_claimed", "core_admitted"])
@pytest.mark.parametrize("after_replace", [False, True])
def test_child_publication_fault_precedes_core_and_fake_dispatch(
    tmp_path, monkeypatch, harmless, phase, after_replace
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    real_atomic = startup_module.atomic_json

    def fail(path, value):
        if path.name == "coordinator-start.json" and value["phase"] == phase:
            if after_replace:
                real_atomic(path, value)
            raise OSError("Injected child publication failure")
        real_atomic(path, value)

    monkeypatch.setattr(startup_module, "atomic_json", fail)
    with pytest.raises(OSError):
        fake_owner(startup, attempt.attempt_id).run()
    with file_lock(tmp_path / ".coordinator.lock", timeout=0):
        pass
    assert_counts(harmless, popen=1)
    monkeypatch.setattr(startup_module, "atomic_json", real_atomic)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=1)
    assert startup.read().attempt_id == attempt.attempt_id


@pytest.mark.parametrize("after_replace", [False, True])
@pytest.mark.parametrize("stopping_fault", [False, True])
def test_ready_publication_fault_settles_core_under_lifetime_lock(
    tmp_path, monkeypatch, harmless, after_replace, stopping_fault
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    real_atomic = coordinator.atomic_json

    def fail(path, value):
        if path.name == "coordinator.json":
            if after_replace:
                real_atomic(path, value)
            raise OSError("Injected readiness publication failure")
        real_atomic(path, value)

    monkeypatch.setattr(coordinator, "atomic_json", fail)
    if stopping_fault:
        write = startup_module.atomic_json

        def fail_stopping(path, value):
            if value.get("phase") == "stopping":
                raise OSError("Injected stopping diagnostic failure")
            write(path, value)

        monkeypatch.setattr(startup_module, "atomic_json", fail_stopping)
    with pytest.raises(OSError):
        fake_owner(startup, attempt.attempt_id).run()
    assert_counts(harmless, popen=1, core=1, fake_dispatch=1, close=1)
    assert harmless[1][-2:] == ["listener_close", "core_close"]
    with file_lock(tmp_path / ".coordinator.lock", timeout=0):
        pass
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert_counts(harmless, popen=1, core=1, fake_dispatch=1, close=1)


def test_readback_failure_after_core_admitted_write_still_precedes_core(
    tmp_path, monkeypatch, harmless
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    original = Startup.read

    def read(self):
        result = original(self)
        if result and result.phase == "core_admitted":
            raise StartupError(
                "COORDINATOR_START_RECORD_INVALID", "Injected readback failure", result.attempt_id
            )
        return result

    monkeypatch.setattr(Startup, "read", read)
    with pytest.raises(StartupError):
        fake_owner(startup, attempt.attempt_id).run()
    assert_counts(harmless, popen=1)
    monkeypatch.setattr(Startup, "read", original)
    assert startup.read().phase == "core_admitted"


def ready_value(startup, attempt=None):
    identity = observe(os.getpid()).identity
    owner = attempt.owner if attempt else None
    return {
        "protocol": PROTOCOL_VERSION,
        "instance_id": owner.instance_id if owner else str(uuid.uuid4()),
        "pid": owner.pid if owner else identity.pid,
        "process_start": owner.process_start if owner else identity.process_start,
        "executable": owner.executable if owner else identity.executable,
        "version": __version__,
        "root": str(startup.root),
        "configuration_sha256": startup.fingerprint,
        "state": "ready",
        "endpoint": {"kind": "unix", "address": "fixture-only"},
    } | ({"startup_attempt_id": attempt.attempt_id} if attempt else {})


def admitted_fixture(startup, harmless):
    attempt = launch_intent(startup)
    with file_lock(startup.root / ".coordinator.lock", timeout=0):
        return startup.admit(attempt.attempt_id, str(uuid.uuid4()))


def test_late_ready_reuses_original_claim_without_new_spawn(tmp_path, harmless):
    startup = manager(tmp_path)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    attempt = startup.read()
    with file_lock(tmp_path / ".coordinator.lock", timeout=0):
        admitted = startup.admit(attempt.attempt_id, str(uuid.uuid4()))
        atomic_json(startup.ready_path, ready_value(startup, admitted))
        ready = CoordinatorClient(tmp_path)._ensure()
    assert ready["startup_attempt_id"] == attempt.attempt_id
    assert_counts(harmless, popen=1)


def test_only_exact_self_claim_is_idempotent_and_admission_cannot_repeat(
    tmp_path, harmless, monkeypatch
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    instance = str(uuid.uuid4())
    with startup.locked():
        claimed = startup.claim(attempt, instance)
        assert startup.claim(claimed, instance) == claimed
        assert startup.read().revision == claimed.revision
        with pytest.raises(StartupError):
            startup.claim(claimed, str(uuid.uuid4()))
    # Even a reported old exit does not allow another instance to bind this UUID.
    real_observe = startup_module.observe
    monkeypatch.setattr(
        startup_module,
        "observe",
        lambda pid, expected=None: (
            Observation("exited", expected) if expected else real_observe(pid)
        ),
    )
    with startup.locked(), pytest.raises(StartupError):
        startup.claim(claimed, str(uuid.uuid4()))
    monkeypatch.setattr(startup_module, "observe", real_observe)
    with file_lock(tmp_path / ".coordinator.lock", timeout=0):
        startup.admit(attempt.attempt_id, instance)
        with pytest.raises(StartupError):
            startup.admit(attempt.attempt_id, instance)
    assert_counts(harmless, popen=1)


def test_stale_timeout_observer_cannot_overwrite_new_owner_or_admission(tmp_path, harmless):
    startup = manager(tmp_path)
    old = launch_intent(startup)
    with startup.locked():
        new = startup.claim(old, str(uuid.uuid4()))
        assert startup.note(old, "ready_timeout") == new
        before = startup.path.read_bytes()
        with pytest.raises(StartupError):
            startup.update(old, last_observation="ready_timeout")
        assert startup.path.read_bytes() == before
    with file_lock(tmp_path / ".coordinator.lock", timeout=0):
        admitted = startup.admit(old.attempt_id, new.owner.instance_id)
    with startup.locked():
        assert startup.note(new, "ready_timeout") == admitted
        assert startup.read() == admitted


@pytest.mark.parametrize(
    "field",
    [
        "startup_attempt_id",
        "instance_id",
        "pid",
        "process_start",
        "executable",
        "root",
        "configuration_sha256",
        "version",
        "protocol",
    ],
)
def test_new_ready_requires_every_attempt_owner_and_scope_field(tmp_path, harmless, field):
    startup = manager(tmp_path)
    attempt = admitted_fixture(startup, harmless)
    ready = ready_value(startup, attempt)
    if field in {"startup_attempt_id", "instance_id"}:
        ready[field] = str(uuid.uuid4())
    elif isinstance(ready[field], int):
        ready[field] += 1
    else:
        ready[field] += "-mismatch"
    atomic_json(startup.ready_path, ready)
    before = (startup.path.read_bytes(), startup.ready_path.read_bytes())
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert before == (startup.path.read_bytes(), startup.ready_path.read_bytes())
    assert_counts(harmless, popen=1)


@pytest.mark.parametrize(
    "value",
    [b"{", b"[]", b"x" * (64 * 1024 + 1), b'{"schema_version":1,"schema_version":1}'],
    ids=["truncated", "not-object", "oversized", "duplicate-key"],
)
def test_malformed_journal_never_falls_back_to_legacy_ready(tmp_path, harmless, value):
    startup = manager(tmp_path)
    atomic_json(startup.ready_path, ready_value(startup))
    startup.path.write_bytes(value)
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert startup.path.read_bytes() == value
    assert_counts(harmless, popen=0)


def test_legacy_reuse_is_only_available_without_any_journal(tmp_path, harmless):
    startup = manager(tmp_path)
    legacy = ready_value(startup)
    atomic_json(startup.ready_path, legacy)
    assert CoordinatorClient(tmp_path)._ensure() == legacy
    assert not startup.path.exists()
    with startup.locked():
        startup.intent()
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert_counts(harmless, popen=0)


def test_new_ready_without_journal_is_not_legacy(tmp_path, harmless):
    startup = manager(tmp_path)
    atomic_json(
        startup.ready_path, ready_value(startup) | {"startup_attempt_id": str(uuid.uuid4())}
    )
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert_counts(harmless, popen=0)


@pytest.mark.parametrize("state", ["unknown", "exited", "different"])
def test_unclaimed_wrapper_cannot_expire_even_when_launcher_retires(
    tmp_path, monkeypatch, harmless, state
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    real_observe = startup_module.observe
    monkeypatch.setattr(
        startup_module,
        "observe",
        lambda pid, expected=None: Observation(state, expected) if expected else real_observe(pid),
    )
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
    assert attempt.attempt_id in error.value.message
    assert startup.read().attempt_id == attempt.attempt_id
    assert startup.read().phase == "spawn_requested"
    assert_counts(harmless, popen=1)


def test_pending_scope_conflict_and_two_roots_are_independent(tmp_path, harmless):
    root_a, root_b = tmp_path / "a", tmp_path / "b"
    for root in (root_a, root_b, root_a):
        with pytest.raises(WorkflowError):
            CoordinatorClient(root)._ensure()
    first, second = manager(root_a).read(), manager(root_b).read()
    assert first.attempt_id != second.attempt_id
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(root_a, [tmp_path])._ensure()
    assert error.value.code == "COORDINATOR_CONFIGURATION_CHANGED"
    assert manager(root_a).read().attempt_id == first.attempt_id
    assert_counts(harmless, popen=2)


def test_unlabelled_legacy_lifetime_owner_blocks_with_zero_wait(tmp_path, harmless):
    with (
        file_lock(tmp_path / ".coordinator.lock", timeout=0),
        pytest.raises(WorkflowError) as error,
    ):
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
    assert not manager(tmp_path).path.exists()
    assert_counts(harmless, popen=0)


def test_startup_lock_contention_has_bounded_diagnostic_with_attempt_id(
    tmp_path, monkeypatch, harmless
):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    real_lock = startup_module.file_lock

    @contextmanager
    def busy(path, timeout=0):
        if path.name == ".coordinator-start.lock":
            assert timeout == 10
            raise TimeoutError("Injected contention without sleeping")
        with real_lock(path, timeout=timeout):
            yield

    monkeypatch.setattr(startup_module, "file_lock", busy)
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_BUSY"
    assert attempt.attempt_id in error.value.message
    assert_counts(harmless, popen=1)


@pytest.mark.parametrize("fault", [None, "before", "after", "conflict"])
def test_retired_chain_archives_before_successor_and_archive_fault_blocks(
    tmp_path, monkeypatch, harmless, fault
):
    startup = manager(tmp_path)
    admitted = admitted_fixture(startup, harmless)
    atomic_json(startup.ready_path, ready_value(startup, admitted))
    real_observe = startup_module.observe
    monkeypatch.setattr(
        startup_module,
        "observe",
        lambda pid, expected=None: (
            Observation("different", expected) if expected else real_observe(pid)
        ),
    )
    real_atomic = startup_module.atomic_json
    archive = tmp_path / "coordinator-start-history" / (admitted.attempt_id + ".json")
    if fault == "conflict":
        atomic_json(archive, {"conflict": True})
    elif fault:

        def fail(path, value):
            if path == archive:
                if fault == "after":
                    real_atomic(path, value)
                raise OSError("Injected archive publication failure")
            real_atomic(path, value)

        monkeypatch.setattr(startup_module, "atomic_json", fail)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    if fault:
        assert startup.read().attempt_id == admitted.attempt_id
        assert_counts(harmless, popen=1)
    else:
        snapshot = read_json(archive)
        assert snapshot["attempt"]["attempt_id"] == admitted.attempt_id
        assert snapshot["attempt"]["phase"] == "owner_exited"
        assert snapshot["ready"]["startup_attempt_id"] == admitted.attempt_id
        assert startup.read().attempt_id != admitted.attempt_id
        assert_counts(harmless, popen=2)


def test_explicit_run_has_no_bypass_and_releases_startup_before_core(tmp_path, harmless):
    startup = manager(tmp_path)
    owner = fake_owner(startup, None)
    owner.run()
    assert_counts(harmless, popen=0, core=1, fake_dispatch=1, close=1)
    assert startup.read().origin == "explicit_in_process"
    assert startup.read().phase == "stopping"
    with pytest.raises(StartupError):
        fake_owner(startup, None).run()
    assert_counts(harmless, popen=0, core=1, fake_dispatch=1, close=1)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-schema",
        "boolean-schema",
        "future-schema",
        "extra",
        "invalid-phase",
        "missing-launcher",
        "owner-without-identity",
        "relative-root",
    ],
)
def test_strict_journal_schema_rejects_unreadable_ownership(tmp_path, harmless, mutation):
    startup = manager(tmp_path)
    attempt = launch_intent(startup)
    value = attempt.model_dump(mode="json")
    if mutation == "missing-schema":
        value.pop("schema_version")
    elif mutation == "boolean-schema":
        value["schema_version"] = True
    elif mutation == "future-schema":
        value["schema_version"] = 2
    elif mutation == "extra":
        value["lease_expires"] = "never-authoritative"
    elif mutation == "invalid-phase":
        value["phase"] = "ready"
    elif mutation == "missing-launcher":
        value.pop("launcher")
    elif mutation == "owner-without-identity":
        value["phase"] = "core_admitted"
        value["owner"] = {"pid": os.getpid(), "instance_id": str(uuid.uuid4())}
    else:
        value["root"] = "relative"
    atomic_json(startup.path, value)
    before = startup.path.read_bytes()
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert startup.path.read_bytes() == before
    assert_counts(harmless, popen=1)


def test_confirmed_pre_invocation_failure_can_be_archived_for_new_attempt(
    tmp_path, monkeypatch, harmless
):
    startup = manager(tmp_path)
    with startup.locked():
        attempt = startup.intent()
        attempt = startup.update(
            attempt, phase="spawn_requested", last_observation="spawn_requested"
        )
        with pytest.raises(StartupError):
            coordinator.spawn_coordinator(
                tmp_path, [tmp_path / "different"], startup=startup, attempt=attempt
            )
    failed = startup.read()
    assert failed.phase == "failed_before_spawn"
    assert failed.terminal_evidence == "popen_not_invoked"
    assert_counts(harmless, popen=0)
    with pytest.raises(WorkflowError):
        CoordinatorClient(tmp_path)._ensure()
    assert startup.read().attempt_id != attempt.attempt_id
    assert (tmp_path / "coordinator-start-history" / (attempt.attempt_id + ".json")).is_file()
    assert_counts(harmless, popen=1)


@pytest.mark.parametrize("state", ["unknown", "live"])
def test_ready_reuse_requires_current_full_owner_identity(tmp_path, monkeypatch, harmless, state):
    startup = manager(tmp_path)
    attempt = admitted_fixture(startup, harmless)
    atomic_json(startup.ready_path, ready_value(startup, attempt))
    real_observe = startup_module.observe
    monkeypatch.setattr(
        startup_module,
        "observe",
        lambda pid, expected=None: Observation(state, expected) if expected else real_observe(pid),
    )
    if state == "live":
        assert CoordinatorClient(tmp_path)._ensure()["startup_attempt_id"] == attempt.attempt_id
    else:
        with pytest.raises(WorkflowError) as error:
            CoordinatorClient(tmp_path)._ensure()
        assert error.value.code == "COORDINATOR_START_UNCONFIRMED"
    assert_counts(harmless, popen=1)


@pytest.mark.skipif(os.name != "nt", reason="Windows query-only handle observation")
@pytest.mark.parametrize("code", [5, 87])
def test_windows_query_denial_is_unknown_and_only_confirmed_absence_is_exit(monkeypatch, code):
    from matlab_companion import native_session
    from matlab_companion.startup import Identity

    def unavailable(pid):
        raise OSError(code, "Native process handle unavailable")

    monkeypatch.setattr(native_session, "WindowsProcess", unavailable)
    assert observe(os.getpid()).state == ("exited" if code == 87 else "unknown")
    assert observe(os.getpid(), Identity(pid=os.getpid())).state == "unknown"


def test_missing_attempt_token_reaches_neither_core_nor_fake_dispatch(tmp_path, harmless):
    owner = fake_owner(manager(tmp_path), str(uuid.uuid4()))
    with pytest.raises(StartupError):
        owner.run()
    assert_counts(harmless, popen=0)
    assert not manager(tmp_path).path.exists()


@pytest.mark.parametrize("target", ["journal", "ready"])
def test_deeply_nested_metadata_is_a_bounded_rejection(tmp_path, harmless, target):
    startup = manager(tmp_path)
    path = startup.path if target == "journal" else startup.ready_path
    raw = b'{"nested":' + b"[" * 1200 + b"]" * 1200 + b"}"
    path.write_bytes(raw)
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert path.read_bytes() == raw
    assert_counts(harmless, popen=0)


def test_archive_resume_rejects_incomplete_matching_snapshot(tmp_path, monkeypatch, harmless):
    startup = manager(tmp_path)
    attempt = admitted_fixture(startup, harmless)
    real_observe = startup_module.observe
    monkeypatch.setattr(
        startup_module,
        "observe",
        lambda pid, expected=None: (
            Observation("exited", expected) if expected else real_observe(pid)
        ),
    )
    with startup.locked():
        terminal, _ = startup.reconciled()
    archive = tmp_path / "coordinator-start-history" / (attempt.attempt_id + ".json")
    atomic_json(archive, {"attempt": terminal.model_dump(mode="json")})
    before = archive.read_bytes()
    with pytest.raises(WorkflowError) as error:
        CoordinatorClient(tmp_path)._ensure()
    assert error.value.code == "COORDINATOR_START_RECORD_INVALID"
    assert archive.read_bytes() == before
    assert startup.read().attempt_id == attempt.attempt_id
    assert_counts(harmless, popen=1)
