"""P2 fake-provider and temporary-file tests; no Core/native/host operations."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from matlab_companion import activation as a
from matlab_companion.storage import atomic_json, file_lock

BEFORE = {
    "provider": "fake-conditional-v1",
    "profile": "test-only",
    "name": "matlab-companion",
    "presence": True,
    "revision": 1,
    "command": "old-python",
    "args": ["serve"],
    "env": {},
}
DESIRED = {**BEFORE, "revision": 2, "command": "new-python"}


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, dict):
        path.write_bytes(a.canonical(value))
    else:
        path.write_bytes(value)
    return path


class FakeProvider:
    atomic_conditional = True

    def __init__(self):
        self.target = copy.deepcopy(BEFORE)
        self.calls = []
        self.scans = 0
        self.after_snapshot = None
        self.before_change = None
        self.crash_after = False

    def snapshot(self, identity, limits, deadline):
        self.scans += 1
        value = {
            "root": identity,
            "complete": True,
            "coverage": dict.fromkeys(a.COVERAGE, True),
            "sources": [
                {
                    "id": "named-entry",
                    "kind": "mcp_entries",
                    "identity": copy.deepcopy(self.target),
                    "recognized": True,
                }
            ],
            "processes": [],
        }
        if self.after_snapshot:
            self.after_snapshot(self.scans, value)
        return value

    def read_target(self):
        return copy.deepcopy(self.target)

    def change(self, expected, desired, operation_id):
        self.calls.append(operation_id)
        if self.before_change:
            self.before_change()
        if self.target != expected:
            raise ValueError("External edit prevented the conditional write")
        self.target = copy.deepcopy(desired)
        if self.crash_after:
            raise TimeoutError("Provider response lost after effect")
        return {
            "operation_id": operation_id,
            "conditional_match": True,
            "revision": desired["revision"],
        }


def journal(root, *, inventory=None):
    return a.Journal.create(
        root,
        source_commit="a" * 40,
        package_sha256="b" * 64,
        target=copy.deepcopy(BEFORE),
        inventory_sha256=inventory,
        desired_target=copy.deepcopy(DESIRED),
    )


def package(root):
    root.mkdir()
    write(root, "module.py", b"# harmless fixture\n")
    write(root, "docs/README.md", b"# Package fixture\n")
    return [
        {
            "path": p.relative_to(root).as_posix(),
            "size_bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(root.rglob("*"))
        if p.is_file()
    ]


def assert_code(code, function):
    with pytest.raises(a.ActivationError) as error:
        function()
    assert error.value.code == code


def test_current_provider_refuses_incomplete_visibility_and_any_change(tmp_path):
    j = journal(tmp_path)
    original = j.read()
    assert_code("INCOMPLETE", lambda: j.admit())
    assert_code(
        "CONDITIONAL_UNAVAILABLE",
        lambda: j.request_change(a.CodexReadOnlyProvider(), BEFORE, DESIRED),
    )
    assert j.read() == original
    assert_code("CONDITIONAL_UNAVAILABLE", lambda: a.CodexReadOnlyProvider().change())


def test_two_complete_scans_and_actual_lock_order(tmp_path, monkeypatch):
    provider = FakeProvider()
    original_lock = a.file_lock
    trace = []

    @contextmanager
    def traced(path, timeout):
        trace.append(("enter", path.name, timeout))
        with original_lock(path, timeout=timeout):
            yield
        trace.append(("exit", path.name, timeout))

    monkeypatch.setattr(a, "file_lock", traced)
    before = write(tmp_path, "settings.json", {"allowed_roots": []}).read_bytes()
    result = a.observe_admission(tmp_path, provider)
    assert result["metadata"]["jobs"] == [] and provider.scans == 2
    expected = [
        ".activation.lock",
        ".setup-codex.lock",
        ".coordinator-start.lock",
        ".coordinator.lock",
        ".execution.lock",
    ]
    assert [row[1] for row in trace if row[0] == "enter"] == expected
    assert [row[1] for row in trace if row[0] == "exit"] == list(reversed(expected))
    assert all(row[2] == 0 for row in trace)
    assert (tmp_path / "settings.json").read_bytes() == before
    assert not (tmp_path / "jobs").exists()


@pytest.mark.parametrize(
    "name",
    [
        ".activation.lock",
        ".setup-codex.lock",
        ".coordinator-start.lock",
        ".coordinator.lock",
        ".execution.lock",
    ],
)
def test_busy_real_lock_refuses_without_wait_or_provider_call(tmp_path, name):
    ready, release = threading.Event(), threading.Event()

    def hold():
        with file_lock(tmp_path / name):
            ready.set()
            release.wait(5)

    worker = threading.Thread(target=hold)
    worker.start()
    assert ready.wait(5)
    provider = FakeProvider()
    try:
        assert_code("BUSY", lambda: a.observe_admission(tmp_path, provider))
        assert provider.scans == 0
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()


@pytest.mark.parametrize(
    "mutation", ["coverage", "inaccessible", "unknown", "duplicate", "live", "source_limit"]
)
def test_external_incomplete_unknown_live_and_bound_refused(tmp_path, mutation):
    provider = FakeProvider()

    def corrupt(_, value):
        if mutation == "coverage":
            value["coverage"].pop("services")
        if mutation == "inaccessible":
            value["complete"] = False
        if mutation == "unknown":
            value["sources"][0]["recognized"] = False
        if mutation == "duplicate":
            value["sources"] *= 2
        if mutation == "live":
            value["processes"] = [
                {
                    "pid": 99,
                    "creation_identity": "fake-incarnation",
                    "executable": "old-runtime",
                    "account": "test",
                    "root": str(tmp_path),
                }
            ]
        if mutation == "source_limit":
            value["sources"] *= 257

    provider.after_snapshot = corrupt
    assert_code(
        "LIVE_OWNER" if mutation == "live" else "INCOMPLETE",
        lambda: a.observe_admission(tmp_path, provider),
    )


@pytest.mark.parametrize("which", ["file", "external", "new_job"])
def test_change_between_complete_scans_refuses(tmp_path, which):
    provider = FakeProvider()

    def change(number, value):
        if number != 1:
            return
        if which == "file":
            write(tmp_path, "settings.json", {"modified": True})
        if which == "external":
            provider.target["revision"] += 1
        if which == "new_job":
            write(
                tmp_path,
                "jobs/11111111-1111-4111-8111-111111111111/state.json",
                {
                    "job_id": "11111111-1111-4111-8111-111111111111",
                    "operation": "first_order_kinetics",
                    "state": "completed",
                    "summary": "Completed fixture",
                },
            )

    provider.after_snapshot = change
    assert_code("CHANGED", lambda: a.observe_admission(tmp_path, provider))


@pytest.mark.parametrize(
    "state", ["queued", "running", "cancel_requested", "unknown", "interrupted"]
)
def test_uncertain_or_accepted_jobs_remain_unchanged(tmp_path, state):
    job_id = "11111111-1111-4111-8111-111111111111"
    row = {
        "job_id": job_id,
        "operation": "first_order_kinetics",
        "state": state,
        "summary": "Synthetic metadata",
    }
    if state in {"unknown", "interrupted"}:
        row["error"] = {"code": "OUTCOME_UNKNOWN", "message": "Retain original operation"}
    path = write(tmp_path, f"jobs/{job_id}/state.json", row)
    before = path.read_bytes()
    assert_code("UNRESOLVED_JOB", lambda: a.observe_admission(tmp_path, FakeProvider()))
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "name",
    [
        "coordinator.json",
        "coordinator-start.json",
        "executor-active.json",
        "executor-quarantine.json",
    ],
)
def test_existing_owner_metadata_requires_separate_review(tmp_path, name):
    path = write(tmp_path, name, {"existing": "preserved"})
    before = path.read_bytes()
    assert_code("UNRESOLVED_OWNER", lambda: a.observe_admission(tmp_path, FakeProvider()))
    assert path.read_bytes() == before


def test_historical_dispatch_does_not_become_exit_proof(tmp_path):
    job_id = "11111111-1111-4111-8111-111111111111"
    write(
        tmp_path,
        f"jobs/{job_id}/state.json",
        {
            "job_id": job_id,
            "operation": "first_order_kinetics",
            "state": "completed",
            "summary": "Completed fixture",
        },
    )
    path = write(tmp_path, f"jobs/{job_id}/dispatch.json", {"coordinator_pid": 123})
    assert_code("NATIVE_REVIEW", lambda: a.observe_admission(tmp_path, FakeProvider()))
    assert path.exists()


def test_metadata_limits_refuse_without_truncation(tmp_path):
    write(tmp_path, "settings.json", b"x" * (a.MAX_EVENT_BYTES + 1))
    assert_code("LIMIT", lambda: a.observe_admission(tmp_path, FakeProvider()))
    write(tmp_path, "settings.json", {"valid": True})
    assert_code(
        "INCOMPLETE",
        lambda: a.observe_admission(tmp_path, FakeProvider(), a.Limits(metadata_bytes=1)),
    )
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs/11111111-1111-4111-8111-111111111111").mkdir()
    assert_code(
        "INCOMPLETE", lambda: a.observe_admission(tmp_path, FakeProvider(), a.Limits(jobs=0))
    )


def test_deadline_covers_both_complete_scans(tmp_path, monkeypatch):
    provider = FakeProvider()
    clock = [0.0]
    monkeypatch.setattr(a.time, "monotonic", lambda: clock[0])
    provider.after_snapshot = lambda *args: clock.__setitem__(0, 20.0)
    assert_code("INCOMPLETE", lambda: a.observe_admission(tmp_path, provider))


@pytest.mark.parametrize(
    "value", ["../escape", "./file", "/absolute", "a\\b", "x:stream", "NUL", "foo."]
)
def test_contained_metadata_paths_reject_aliases(tmp_path, value):
    assert_code("ALIAS", lambda: a.checked_path(tmp_path, value, absent=True))


def test_root_dotdot_alias_rejected(tmp_path):
    assert_code("ALIAS", lambda: a.root_identity(str(tmp_path) + "/../" + tmp_path.name))


def test_reparse_attribute_refused_without_following_target(tmp_path, monkeypatch):
    original = Path.lstat

    def fake(path):
        info = original(path)
        if path == tmp_path:

            class Reparse:
                st_mode = info.st_mode
                st_file_attributes = 0x400

            return Reparse()
        return info

    monkeypatch.setattr(Path, "lstat", fake)
    assert_code("ALIAS", lambda: a.root_identity(tmp_path))


def test_real_symlink_alias_refused_when_privilege_available(tmp_path):
    real = tmp_path / "actual"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink privilege is unavailable")
    assert_code("ALIAS", lambda: a.root_identity(link))


def test_journal_is_exclusive_and_summary_crash_is_preserved(tmp_path, monkeypatch):
    j = journal(tmp_path)
    assert j.read()["phase"] == "prepared"
    with pytest.raises(FileExistsError):
        journal(tmp_path)
    original = a.atomic_json

    def fail_summary(*args, **kwargs):
        raise OSError("disk write interrupted")

    monkeypatch.setattr(a, "atomic_json", fail_summary)
    with pytest.raises(OSError):
        j.admit(FakeProvider())
    monkeypatch.setattr(a, "atomic_json", original)
    names = sorted(p.name for p in j.directory.iterdir())
    assert "event-0002.json" in names
    assert_code("UNKNOWN", j.read)
    assert names == sorted(p.name for p in j.directory.iterdir())


@pytest.mark.parametrize(
    "damage",
    ["missing_event", "bad_summary", "extra_file", "duplicate_key", "wrong_root", "wrong_hash"],
)
def test_journal_damage_refuses_without_repair(tmp_path, damage):
    j = journal(tmp_path)
    event = j.directory / "event-0001.json"
    if damage == "missing_event":
        event.unlink()
    if damage == "bad_summary":
        atomic_json(j.directory / "summary.json", {"bad": True})
    if damage == "extra_file":
        write(j.directory, "orphan.tmp", b"uncertain")
    if damage == "duplicate_key":
        event.write_bytes(b'{"schema_version":1,"schema_version":1}')
    if damage in {"wrong_root", "wrong_hash"}:
        value = json.loads(event.read_text(encoding="utf-8"))
        if damage == "wrong_root":
            value["root"]["file_id"] = "different"
        else:
            value["previous_sha256"] = "f" * 64
        event.write_bytes(a.canonical(value))
    before = {p.name: p.read_bytes() for p in j.directory.iterdir()}
    assert_code("UNKNOWN", j.read)
    assert before == {p.name: p.read_bytes() for p in j.directory.iterdir()}


def test_fake_conditional_success_and_no_second_request(tmp_path):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    result = j.request_change(provider, BEFORE, DESIRED)
    assert result["phase"] == "mutation_observed" and provider.target == DESIRED
    assert len(provider.calls) == 1
    assert_code("REFUSED", lambda: j.request_change(provider, BEFORE, DESIRED))
    assert len(provider.calls) == 1


def test_lost_response_reconciles_same_operation_without_replay(tmp_path):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    provider.crash_after = True
    first = j.request_change(provider, BEFORE, DESIRED)
    assert first["phase"] == "unknown" and provider.target == DESIRED
    restarted = a.Journal(tmp_path)
    for observed in [DESIRED, BEFORE]:
        record = restarted.reconcile(observed)
        assert record["phase"] == "unknown"
        assert record["operation"]["operation_id"] == first["operation"]["operation_id"]
    assert len(provider.calls) == 1
    assert_code("REFUSED", lambda: restarted.request_change(provider, BEFORE, DESIRED))


def test_concurrent_external_edit_survives_precheck_dispatch_race(tmp_path):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    external = {**BEFORE, "revision": 12, "command": "user-selected-runtime"}
    provider.before_change = lambda: setattr(provider, "target", external)
    result = j.request_change(provider, BEFORE, DESIRED)
    assert result["phase"] == "unknown" and provider.target == external
    record = j.reconcile(provider.read_target())
    assert record["phase"] == "conflict" and provider.target == external
    assert len(provider.calls) == 1


def test_target_change_before_dispatch_never_writes_request(tmp_path):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    provider.target = {**BEFORE, "args": ["external", "edit"]}
    prior = j.read()
    assert_code("CONFLICT", lambda: j.request_change(provider, BEFORE, DESIRED))
    assert j.read() == prior and provider.calls == []


class SimulatedCrash(BaseException):
    pass


def test_crash_after_durable_request_before_provider_call_is_not_replayed(tmp_path, monkeypatch):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    original = j._append

    def crash(current, tip, phase, operation=None):
        result = original(current, tip, phase, operation)
        if phase == "mutation_requested":
            raise SimulatedCrash()
        return result

    monkeypatch.setattr(j, "_append", crash)
    with pytest.raises(SimulatedCrash):
        j.request_change(provider, BEFORE, DESIRED)
    restarted = a.Journal(tmp_path)
    record = restarted.read()
    assert record["phase"] == "mutation_requested" and provider.calls == []
    assert restarted.reconcile(BEFORE)["phase"] == "unknown"
    assert provider.calls == []


def staged_fixture(tmp_path):
    scope = a.create_isolated_stage_scope(tmp_path)
    source = tmp_path / "source"
    records = package(source)
    j = journal(scope.root, inventory=a.fingerprint(records))
    provider = FakeProvider()
    j.admit(provider)
    return scope, source, records, j, provider


def test_exclusive_isolated_stage_binds_frozen_inventory(tmp_path):
    scope, source, records, j, provider = staged_fixture(tmp_path)
    result = a.stage_isolated(scope, j, source, records, provider)
    assert result["phase"] == "staged_verified"
    assert (scope.root / "candidate/module.py").read_bytes() == (source / "module.py").read_bytes()
    assert provider.calls == []
    assert_code("REFUSED", lambda: a.stage_isolated(scope, j, source, records, provider))


def test_staging_scope_cannot_be_retargeted_to_existing_root(tmp_path):
    scope, source, records, _journal, provider = staged_fixture(tmp_path)
    other = tmp_path / "existing"
    other.mkdir()
    otherj = journal(other, inventory=a.fingerprint(records))
    otherj.admit(provider)
    forged = dataclasses.replace(scope, root=other, identity=a.root_identity(other))
    assert_code("REFUSED", lambda: a.stage_isolated(forged, otherj, source, records, provider))
    assert not (other / "candidate").exists()


def test_stage_manifest_must_match_frozen_review(tmp_path):
    scope, source, records, j, provider = staged_fixture(tmp_path)
    write(source, "module.py", b"Changed but newly hashed")
    records[0]["sha256"] = hashlib.sha256((source / records[0]["path"]).read_bytes()).hexdigest()
    records[0]["size_bytes"] = (source / records[0]["path"]).stat().st_size
    # Rebuild every hash to demonstrate that internally consistent new bytes
    # are still not the package accepted in the immutable review.
    for record in records:
        path = source / record["path"]
        record.update(
            size_bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        )
    assert_code("CONFLICT", lambda: a.stage_isolated(scope, j, source, records, provider))
    assert not (scope.root / "candidate").exists()


def test_partial_stage_survives_copy_failure_and_restart(tmp_path, monkeypatch):
    scope, source, records, j, provider = staged_fixture(tmp_path)
    original = a._copy_file
    calls = []

    def interrupt(src, dst, record):
        original(src, dst, record)
        calls.append(dst)
        raise OSError("disk interrupted after copy")

    monkeypatch.setattr(a, "_copy_file", interrupt)
    result = a.stage_isolated(scope, j, source, records, provider)
    assert result["phase"] == "unknown" and len(calls) == 1 and calls[0].exists()
    retained = {
        p.relative_to(scope.root).as_posix(): p.read_bytes()
        for p in (scope.root / "candidate").rglob("*")
        if p.is_file()
    }
    restarted = a.Journal(scope.root)
    assert_code("REFUSED", lambda: a.stage_isolated(scope, restarted, source, records, provider))
    assert retained == {
        p.relative_to(scope.root).as_posix(): p.read_bytes()
        for p in (scope.root / "candidate").rglob("*")
        if p.is_file()
    }


def test_existing_stage_destination_is_never_replaced(tmp_path):
    scope, source, records, j, provider = staged_fixture(tmp_path)
    path = write(scope.root, "candidate/owner.txt", b"other owner")
    before = j.read()
    assert_code("CONFLICT", lambda: a.stage_isolated(scope, j, source, records, provider))
    assert path.read_bytes() == b"other owner" and j.read() == before


def test_unlisted_and_symlink_like_package_members_are_rejected(tmp_path):
    source = tmp_path / "source"
    records = package(source)
    write(source, "unlisted.txt", b"unreviewed")
    assert_code("INVALID", lambda: a._package_inventory(source, records))
    records[0]["path"] = "../escape"
    assert_code("ALIAS", lambda: a._package_inventory(source, records))


def test_journal_code_has_no_setup_core_or_process_dispatch_import():
    import ast

    tree = ast.parse(Path(a.__file__).read_text(encoding="utf-8"))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        name and ("core" in name or "setup_ui" in name or "coordinator" in name) for name in imports
    )
    assert not any(
        isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names)
        for node in ast.walk(tree)
    )


def test_changed_desired_target_is_not_a_new_authorization(tmp_path):
    j = journal(tmp_path)
    provider = FakeProvider()
    j.admit(provider)
    assert_code(
        "CONFLICT", lambda: j.request_change(provider, BEFORE, {**DESIRED, "command": "unreviewed"})
    )
    assert provider.calls == [] and j.read()["phase"] == "admitted"


def test_claiming_cas_on_current_provider_cannot_enable_host_writes(tmp_path):
    class UnsupportedOverride(a.CodexReadOnlyProvider):
        atomic_conditional = True

        def change(self, *args):
            pytest.fail("Current provider mutations must remain unreachable")

    j = journal(tmp_path)
    assert_code(
        "CONDITIONAL_UNAVAILABLE", lambda: j.request_change(UnsupportedOverride(), BEFORE, DESIRED)
    )
    assert j.read()["phase"] == "prepared"


@pytest.mark.parametrize("point", ["before_create", "after_one_file", "after_all_files"])
def test_stage_abrupt_interruption_keeps_same_operation_and_partial_files(
    tmp_path, monkeypatch, point
):
    scope, source, records, j, provider = staged_fixture(tmp_path)
    if point == "before_create":
        original = j._append

        def crash(current, tip, phase, operation=None):
            result = original(current, tip, phase, operation)
            if phase == "stage_requested":
                raise SimulatedCrash()
            return result

        monkeypatch.setattr(j, "_append", crash)
    else:
        original = a._copy_file
        count = [0]

        def crash(src, dst, record):
            original(src, dst, record)
            count[0] += 1
            if count[0] == (1 if point == "after_one_file" else len(records)):
                raise SimulatedCrash()

        monkeypatch.setattr(a, "_copy_file", crash)
    with pytest.raises(SimulatedCrash):
        a.stage_isolated(scope, j, source, records, provider)
    restarted = a.Journal(scope.root)
    before = restarted.read()
    assert before["phase"] == "stage_requested"
    assert_code("REFUSED", lambda: a.stage_isolated(scope, restarted, source, records, provider))
    assert restarted.read() == before
    observation = (
        before["operation"]["expected_before"]
        if point == "before_create"
        else {"presence": True, "partial_or_unattributed": True}
    )
    result = restarted.reconcile(observation)
    assert result["operation"]["operation_id"] == before["operation"]["operation_id"]
    assert result["phase"] == ("unknown" if point == "before_create" else "conflict")
    if point != "before_create":
        assert (scope.root / "candidate").is_dir()


def test_stage_scope_factory_refuses_non_temporary_parent(tmp_path, monkeypatch):
    permitted = tmp_path / "permitted-temp"
    permitted.mkdir()
    monkeypatch.setattr(a.tempfile, "gettempdir", lambda: str(permitted))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert_code("REFUSED", lambda: a.create_isolated_stage_scope(tmp_path))
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_opened_metadata_swap_is_not_treated_as_a_stable_read(tmp_path, monkeypatch):
    path = write(tmp_path, "settings.json", {"original": True})
    original = Path.open

    def changing_open(item, *args, **kwargs):
        if item == path and args == ("rb",):
            replacement = item.with_suffix(".replacement")
            replacement.write_bytes(b'{"changed":true}')
            replacement.replace(item)
        return original(item, *args, **kwargs)

    monkeypatch.setattr(Path, "open", changing_open)
    assert_code("CHANGED", lambda: a.read_metadata(tmp_path, "settings.json"))


def test_journal_review_cannot_change_after_admission(tmp_path):
    j = journal(tmp_path)
    j.admit(FakeProvider())
    event = j.directory / "event-0002.json"
    value = json.loads(event.read_text(encoding="utf-8"))
    value["review"]["desired_target"]["command"] = "external-edit"
    event.write_bytes(a.canonical(value))
    assert_code("UNKNOWN", j.read)


@pytest.mark.parametrize("name", ["receipt.json", "backend-result.json"])
def test_scientific_receipt_contents_are_not_opened_for_admission(tmp_path, monkeypatch, name):
    job_id = "11111111-1111-4111-8111-111111111111"
    write(
        tmp_path,
        f"jobs/{job_id}/state.json",
        {
            "job_id": job_id,
            "operation": "first_order_kinetics",
            "state": "completed",
            "summary": "Completed fixture",
        },
    )
    target = write(tmp_path, f"jobs/{job_id}/{name}", b"Opaque scientific response - do not open")
    original = Path.open

    def protected(path, *args, **kwargs):
        if path == target:
            pytest.fail("Scientific result content was opened")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", protected)
    assert_code("NATIVE_REVIEW", lambda: a.observe_admission(tmp_path, FakeProvider()))


def test_same_bytes_with_external_rewrite_between_scans_refuses(tmp_path):
    import os

    path = write(tmp_path, "settings.json", {"same": True})
    provider = FakeProvider()

    def change(number, value):
        if number == 1:
            st = path.stat()
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 3_000_000_000))

    provider.after_snapshot = change
    assert_code("CHANGED", lambda: a.observe_admission(tmp_path, provider))
