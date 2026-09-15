"""Installation boundaries without GUI, network, MATLAB or live host mutations."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from matlab_companion.setup_ui import (
    SetupError,
    clear_quarantine,
    connect_codex,
    load_settings,
    quarantine_status,
    rollback_codex,
    save_settings,
    setup_status,
)
from matlab_companion.storage import atomic_json, file_lock, read_json


@pytest.fixture
def folders(tmp_path):
    input_dir = tmp_path / "Input with spaces"
    output_dir = tmp_path / "Results"
    matlab = tmp_path / "MATLAB"
    for folder in (input_dir, output_dir, matlab / "bin"):
        folder.mkdir(parents=True)
    (matlab / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")).write_bytes(b"fixture only")
    return input_dir, output_dir, matlab


class FakeCodex:
    """A stateful fake at the official CLI process boundary."""

    def __init__(self, entries=()):
        self.entries = {item["name"]: item for item in entries}
        self.commands = []
        self.fail_add = False

    def __call__(self, args, **kwargs):
        assert not kwargs.get("shell", False)
        self.commands.append(list(args))
        action = args[2]
        if action == "list":
            return subprocess.CompletedProcess(args, 0, json.dumps(list(self.entries.values())), "")
        if action == "add":
            if self.fail_add:
                return subprocess.CompletedProcess(args, 1, "", "simulated CLI failure")
            index = args.index("--")
            self.entries[args[3]] = {
                "name": args[3],
                "enabled": True,
                "transport": {
                    "type": "stdio",
                    "command": args[index + 1],
                    "args": args[index + 2 :],
                    "env": None,
                },
            }
            return subprocess.CompletedProcess(args, 0, "Added server", "")
        if action == "remove":
            self.entries.pop(args[3], None)
            return subprocess.CompletedProcess(args, 0, "Removed server", "")
        raise AssertionError(f"Unexpected CLI action: {action}")


def test_settings_merge_reuses_roots_and_preserves_unknown_values(tmp_path, folders):
    inputs, outputs, matlab = folders
    root = tmp_path / "settings"
    old_input = tmp_path / "Prior input"
    old_input.mkdir()
    atomic_json(
        root / "settings.json",
        {
            "allowed_roots": [str(old_input)],
            "output_roots": [str(outputs)],
            "adapter_preferences": {"claude": "keep"},
            "matlab_root": str(matlab),
        },
    )
    result = save_settings(root, inputs, outputs, matlab)
    assert result["allowed_roots"] == [str(old_input.resolve()), str(inputs.resolve())]
    assert result["output_roots"] == [str(outputs.resolve())]
    assert result["adapter_preferences"] == {"claude": "keep"}
    assert load_settings(root) == result
    assert save_settings(root, inputs, outputs, matlab) == result


@pytest.mark.parametrize("which", ["input", "output", "matlab"])
def test_invalid_folder_selection_does_not_change_existing_settings(tmp_path, folders, which):
    inputs, outputs, matlab = folders
    root = tmp_path / "settings"
    save_settings(root, inputs, outputs, matlab)
    original = (root / "settings.json").read_bytes()
    arguments = {"input_folder": inputs, "output_folder": outputs, "matlab_folder": matlab}
    arguments[
        {"input": "input_folder", "output": "output_folder", "matlab": "matlab_folder"}[which]
    ] = tmp_path / "missing"
    with pytest.raises(SetupError):
        save_settings(root, **arguments)
    assert (root / "settings.json").read_bytes() == original


def test_corrupt_settings_are_preserved_for_recovery(tmp_path, folders):
    root = tmp_path / "settings"
    root.mkdir()
    target = root / "settings.json"
    target.write_text('{"private": "keep", BROKEN', encoding="utf-8")
    original = target.read_bytes()
    with pytest.raises(SetupError):
        save_settings(root, *folders)
    assert target.read_bytes() == original


def test_connection_uses_argument_vector_and_preserves_other_servers(tmp_path):
    root = tmp_path / "settings"
    runtime = tmp_path / "Runtime with spaces" / "python.exe"
    runtime.parent.mkdir()
    runtime.touch()
    other = {"name": "other-plugin", "transport": {"type": "stdio", "command": "keep", "args": []}}
    cli = FakeCodex([other])
    result = connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)
    assert result["state"] == "connected"
    add = next(command for command in cli.commands if command[2] == "add")
    assert add[:5] == ["codex", "mcp", "add", "matlab-companion", "--"]
    assert add[5] == str(runtime.resolve())
    assert add[6:9] == ["-m", "matlab_companion", "serve"]
    assert cli.entries["other-plugin"] == other
    assert read_json(root / "codex-connection.json")["created_by_setup"] is True
    count = sum(command[2] == "add" for command in cli.commands)
    assert (
        connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)["state"]
        == "already_connected"
    )
    assert sum(command[2] == "add" for command in cli.commands) == count


def test_existing_different_codex_entry_is_never_overwritten(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    existing = {
        "name": "matlab-companion",
        "transport": {
            "type": "stdio",
            "command": "older-runtime",
            "args": ["preserve"],
            "env": {"PRIVATE_TOKEN": "must stay private"},
        },
    }
    cli = FakeCodex([existing])
    result = connect_codex(
        tmp_path / "settings", runtime_python=runtime, codex_command="codex", runner=cli
    )
    assert result["state"] == "conflict"
    assert cli.entries["matlab-companion"] == existing
    assert all(command[2] == "list" for command in cli.commands)
    assert "PRIVATE_TOKEN" not in json.dumps(result)
    assert not (tmp_path / "settings" / "codex-connection.json").exists()


def test_failed_cli_add_keeps_recovery_record_and_does_not_repeat(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    cli = FakeCodex()
    cli.fail_add = True
    root = tmp_path / "settings"
    with pytest.raises(SetupError):
        connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)
    assert read_json(root / "codex-connection.json")["state"] == "uncertain"
    assert sum(command[2] == "add" for command in cli.commands) == 1
    assert not any(command[2] == "remove" for command in cli.commands)


def test_rollback_removes_only_the_unchanged_entry_created_by_setup(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    cli = FakeCodex()
    root = tmp_path / "settings"
    connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)
    result = rollback_codex(root, codex_command="codex", runner=cli)
    assert result["state"] == "removed"
    assert "matlab-companion" not in cli.entries
    assert read_json(root / "codex-connection.json")["state"] == "removed"


def test_rollback_preserves_user_changes_after_connection(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    cli = FakeCodex()
    root = tmp_path / "settings"
    connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)
    cli.entries["matlab-companion"]["transport"]["env"] = {"MY_OPTION": "keep"}
    with pytest.raises(SetupError):
        rollback_codex(root, codex_command="codex", runner=cli)
    assert not any(command[2] == "remove" for command in cli.commands)


def test_quarantine_recovery_requires_confirmation_and_preserves_jobs(tmp_path):
    root = tmp_path / "settings"
    job = root / "jobs" / "known-job"
    job.mkdir(parents=True)
    (job / "state.json").write_text('{"state":"unknown"}', encoding="utf-8")
    original_job = (job / "state.json").read_bytes()
    atomic_json(
        root / "executor-quarantine.json",
        {"job_id": "known-job", "reason": "Native exit unconfirmed."},
    )
    current = quarantine_status(root)
    with pytest.raises(SetupError):
        clear_quarantine(root, confirmed_stopped=False, expected_sha256=current["sha256"])
    assert (root / "executor-quarantine.json").is_file()
    result = clear_quarantine(root, confirmed_stopped=True, expected_sha256=current["sha256"])
    assert result["state"] == "cleared"
    assert not (root / "executor-quarantine.json").exists()
    assert (job / "state.json").read_bytes() == original_job
    assert Path(result["receipt"]).is_file()


def test_changed_quarantine_and_active_executor_cannot_be_cleared(tmp_path):
    root = tmp_path / "settings"
    atomic_json(root / "executor-quarantine.json", {"job_id": "first", "reason": "Waiting."})
    first = quarantine_status(root)
    atomic_json(root / "executor-quarantine.json", {"job_id": "second", "reason": "Changed."})
    with pytest.raises(SetupError):
        clear_quarantine(root, confirmed_stopped=True, expected_sha256=first["sha256"])
    current = quarantine_status(root)
    with file_lock(root / ".execution.lock"), pytest.raises(SetupError):
        clear_quarantine(root, confirmed_stopped=True, expected_sha256=current["sha256"])
    assert (root / "executor-quarantine.json").is_file()


def test_rollback_preserves_changed_host_options_outside_transport(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    cli = FakeCodex()
    root = tmp_path / "settings"
    connect_codex(root, runtime_python=runtime, codex_command="codex", runner=cli)
    cli.entries["matlab-companion"]["startup_timeout_sec"] = 90
    with pytest.raises(SetupError):
        rollback_codex(root, codex_command="codex", runner=cli)
    assert not any(command[2] == "remove" for command in cli.commands)


def test_passive_status_does_not_claim_native_or_host_acceptance(tmp_path, folders):
    root = tmp_path / "settings"
    save_settings(root, *folders)
    status = setup_status(root)
    assert status["matlab_installation_found"] is True
    assert status["backend_verified"] is False
    assert status["native_execution"] == "unverified"
    assert status["licence"] == "unverified"
    assert status["host_delivery"] == "unverified"
    assert not (root / "jobs").exists()


def test_unsupported_codex_list_shape_cannot_be_treated_as_absent_entry(tmp_path):
    runtime = tmp_path / "python.exe"
    runtime.touch()
    calls = []

    def runner(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '[{"unexpected_field":"unknown"}]', "")

    with pytest.raises(SetupError):
        connect_codex(
            tmp_path / "settings", runtime_python=runtime, codex_command="codex", runner=runner
        )
    assert len(calls) == 1 and calls[0][2] == "list"
