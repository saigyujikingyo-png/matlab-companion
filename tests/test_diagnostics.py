"""Passive diagnostic entrypoints must not recover or dispatch persisted work."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import pytest

from matlab_companion import __main__ as cli
from matlab_companion import backend as backend_module
from matlab_companion import core as core_module
from matlab_companion.contracts import JobSummary, StatusOutput
from matlab_companion.storage import atomic_json


def snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("command", ["status", "self-test", "setup-check"])
def test_cli_diagnostics_leave_queued_and_dispatched_jobs_untouched(
    tmp_path, monkeypatch, capsys, command
):
    root = tmp_path / "selected runtime"
    dispatched = []
    monkeypatch.setattr(core_module.Core, "_execute", lambda self, job_id: dispatched.append(job_id))
    for state in ("queued", "running"):
        job_id = str(uuid.uuid4())
        job = root / "jobs" / job_id
        atomic_json(
            job / "state.json",
            JobSummary(
                job_id=job_id,
                operation="first_order_kinetics",
                state=state,
                summary="Persisted accepted work",
            ).model_dump(mode="json"),
        )
        atomic_json(
            job / ("scheduler.json" if state == "queued" else "dispatch.json"),
            {"coordinator_pid": 0, "idempotency_key": job_id, "signature": "fixture"},
        )
    original = snapshot(root)
    monkeypatch.setattr(sys, "argv", ["matlab_companion", command, "--root", str(root)])

    if command == "setup-check":
        from matlab_companion.setup_ui import setup_status

        output = setup_status(root)["status"]
    else:
        cli.main()
        output, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    StatusOutput.model_validate(output)
    assert dispatched == []
    assert snapshot(root) == original
    assert not (root / "inputs").exists()


@pytest.mark.parametrize("command", ["status", "self-test"])
def test_cli_diagnostics_do_not_create_missing_root(tmp_path, monkeypatch, capsys, command):
    root = tmp_path / "missing runtime"
    monkeypatch.setattr(sys, "argv", ["matlab_companion", command, "--root", str(root)])

    cli.main()

    output, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    StatusOutput.model_validate(output)
    assert not root.exists()


def test_cli_setup_forwards_resolved_root(tmp_path, monkeypatch):
    from matlab_companion import setup_ui

    selected = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(setup_ui, "main", lambda root=None: selected.append(root))
    monkeypatch.setattr(sys, "argv", ["matlab_companion", "setup", "--root", "selected/../chosen"])

    cli.main()

    assert selected == [(tmp_path / "chosen").resolve()]
    assert not (tmp_path / "chosen").exists()


@pytest.mark.parametrize("command", ["status", "self-test"])
def test_diagnostic_entrypoints_never_construct_core_or_start_threads(
    tmp_path, monkeypatch, capsys, command
):
    from matlab_companion.setup_ui import setup_status

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Passive diagnostics must not construct a coordinator or worker")

    monkeypatch.setattr(core_module, "Core", forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    root = tmp_path / "absent"
    monkeypatch.setattr(sys, "argv", ["matlab_companion", command, "--root", str(root)])
    cli.main()
    capsys.readouterr()
    StatusOutput.model_validate(setup_status(root)["status"])
    assert not root.exists()


@pytest.fixture
def separate_installations(tmp_path, monkeypatch):
    default = tmp_path / "unconfigured default"
    monkeypatch.setenv("LOCALAPPDATA", str(default))
    monkeypatch.delenv("MATLAB_COMPANION_MATLAB_ROOT", raising=False)
    binary_bytes = b"official-backend-test-fixture-never-executed"
    monkeypatch.setitem(
        backend_module.ASSETS,
        (backend_module.platform.system(), backend_module.platform.machine()),
        ("backend-fixture", hashlib.sha256(binary_bytes).hexdigest()),
    )
    roots = []
    for name in ("first", "second"):
        root = tmp_path / name
        installation = tmp_path / f"MATLAB {name}"
        (installation / "bin").mkdir(parents=True)
        (installation / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")).touch()
        atomic_json(root / "settings.json", {"matlab_root": str(installation)})
        atomic_json(root / "native-observation.json", {"matlab_version": name})
        roots.append((root, installation))
    binary = backend_module.backend_path(roots[0][0])
    binary.parent.mkdir(parents=True)
    binary.write_bytes(binary_bytes)
    return roots, default


def test_selected_roots_keep_backend_matlab_and_observations_separate(
    separate_installations, monkeypatch, capsys
):
    from matlab_companion.diagnostics import passive_status
    from matlab_companion.setup_ui import setup_status

    roots, default = separate_installations
    originals = {root: snapshot(root) for root, _ in roots}
    for index, (root, installation) in enumerate(roots):
        assert backend_module.matlab_root(root) == installation.resolve()
        adapter = backend_module.OfficialBackend(root)
        assert adapter.root == root.resolve()
        assert adapter.available() is (index == 0)
        status = passive_status(root)
        StatusOutput.model_validate(status)
        assert status["backend"]["matlab_version"] == root.name
        assert status["backend"]["state"] == ("unverified" if index == 0 else "unavailable")
        setup = setup_status(root)
        assert setup["matlab_installation_found"]
        assert setup["backend_verified"] is (index == 0)
        assert setup["status"]["backend"] == status["backend"]
        monkeypatch.setattr(sys, "argv", ["matlab_companion", "status", "--root", str(root)])
        cli.main()
        assert json.loads(capsys.readouterr().out)["backend"] == status["backend"]
        assert snapshot(root) == originals[root]
    assert not default.exists()


@pytest.mark.parametrize("command", ["status", "self-test"])
def test_real_cli_process_preserves_existing_job_bytes(tmp_path, command):
    root = tmp_path / "runtime"
    for state in ("queued", "running"):
        job_id = str(uuid.uuid4())
        job = root / "jobs" / job_id
        atomic_json(
            job / "state.json",
            JobSummary(
                job_id=job_id, operation="data_profile", state=state, summary="Retained work"
            ).model_dump(mode="json"),
        )
        if state == "running":
            atomic_json(job / "dispatch.json", {"coordinator_pid": 0})
    original = snapshot(root)
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-m", "matlab_companion", command, "--root", str(root)],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
        env=os.environ | {"LOCALAPPDATA": str(tmp_path / "unconfigured default")},
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    output, _ = json.JSONDecoder().raw_decode(result.stdout)
    StatusOutput.model_validate(output)
    assert snapshot(root) == original


@pytest.mark.parametrize("observation", [[], {"matlab_version": {"invalid": "value"}}])
def test_malformed_saved_observation_returns_validated_error_without_mutation(
    tmp_path, observation
):
    from matlab_companion.diagnostics import passive_status

    root = tmp_path / "runtime"
    atomic_json(root / "native-observation.json", observation)
    original = snapshot(root)
    result = passive_status(root)
    StatusOutput.model_validate(result)
    assert result["ok"] is False
    assert result["error"]["code"] in {"INPUT_INVALID", "OUTPUT_CONTRACT_INVALID"}
    assert snapshot(root) == original


def test_backend_launcher_records_identity_before_science_and_uses_selected_root(
    separate_installations, monkeypatch
):
    roots, default = separate_installations
    root, installation = roots[0]
    job = root / "jobs" / str(uuid.uuid4())
    job.mkdir(parents=True)
    calls = []

    def stop_before_process(parameters, **_kwargs):
        calls.append(parameters)
        raise RuntimeError("Stopped at process boundary; no native launch")

    monkeypatch.setattr(backend_module, "stdio_client", stop_before_process)
    with pytest.raises(RuntimeError, match="Stopped at process boundary"):
        asyncio.run(backend_module.OfficialBackend(root).execute(job))

    assert len(calls) == 1
    assert calls[0].command == str(backend_module.backend_path(root))
    assert f"--matlab-root={installation.resolve()}" in calls[0].args
    launcher = (job / "launch_companion.m").read_text(encoding="utf-8")
    assert "'contract_version', '1.0'" in launcher
    assert f"'job_id', '{job.name}'" in launcher
    session_id = launcher.split("'session_id', '", 1)[1].split("'", 1)[0]
    assert str(uuid.UUID(session_id)) == session_id
    assert "matlabProcessID" in launcher and "feature(" not in launcher
    assert "'ConvertInfAndNaN', true" in launcher
    assert backend_module.matlab_quote(job / "native-session.json") in launcher
    assert launcher.index("fclose(") < launcher.index("movefile(") < launcher.index("companion.execute(")
    assert not (job / "native-session.json").exists()  # Generation is not native execution evidence.
    assert not default.exists()
