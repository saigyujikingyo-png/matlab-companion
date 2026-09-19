"""Rejected frontend/configuration inputs stay passive; no service or MATLAB launch."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from matlab_companion.client import CoordinatorClient
from matlab_companion.coordinator import Coordinator, resolved_configuration
from matlab_companion.server import create_server
from matlab_companion.setup_ui import SetupError
from matlab_companion.storage import atomic_json

JOB_ID = str(uuid.uuid4())


def rejected_job_request(client, arguments):
    server = create_server(client)
    entry = server.get_request_handler("tools/call")
    parameters = entry.params_type.model_validate({"name": "matlab_job", "arguments": arguments})
    result = asyncio.run(entry.handler(None, parameters))
    assert result.is_error
    assert result.structured_content["ok"] is False
    assert result.structured_content["error"]["code"] == "INPUT_OR_OUTPUT_INVALID"
    assert json.loads(result.content[0].text) == result.structured_content
    return result.structured_content


@pytest.mark.parametrize(
    "arguments",
    [
        {"job_id": "not-a-job-id"},
        {"job_id": JOB_ID, "action": "unsupported"},
        {"job_id": JOB_ID, "action": "status", "timeout_seconds": 1},
        {"job_id": JOB_ID, "action": "wait", "timeout_seconds": 11},
    ],
    ids=["malformed-uuid", "invalid-action", "inapplicable-options", "invalid-wait-bound"],
)
def test_rejected_job_request_does_not_create_root_or_launch(tmp_path, monkeypatch, arguments):
    root = tmp_path / "absent-root"
    launches = []

    def blocked_spawn(*args, **kwargs):
        launches.append((args, kwargs))
        raise OSError("Test guard: a rejected request must not launch a service")

    monkeypatch.setattr("matlab_companion.client.spawn_coordinator", blocked_spawn)
    rejected_job_request(CoordinatorClient(root), arguments)
    assert not launches, "Rejected public input attempted to launch the coordinator"
    assert not root.exists(), "Rejected public input created its installation root"


def test_rejected_request_retains_known_job_without_changing_queued_bytes(tmp_path, monkeypatch):
    root = tmp_path / "store"
    job = root / "jobs" / JOB_ID
    atomic_json(
        job / "state.json",
        {
            "job_id": JOB_ID,
            "operation": "data_profile",
            "state": "queued",
            "phase": "queued",
            "summary": "Portable passive lookup fixture; never dispatched.",
            "artifact_count": 0,
        },
    )
    atomic_json(job / "scheduler.json", {"fixture": "Do not recover this queued job"})
    before = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }

    def forbidden_spawn(*args, **kwargs):
        raise AssertionError("Error metadata lookup must not start job recovery")

    monkeypatch.setattr("matlab_companion.client.spawn_coordinator", forbidden_spawn)
    output = rejected_job_request(
        CoordinatorClient(root), {"job_id": JOB_ID, "action": "status", "after_event_seq": 0}
    )
    assert output["job_id"] == JOB_ID
    after = {
        path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("key", ["allowed_roots", "output_roots"])
@pytest.mark.parametrize(
    "malformed",
    ["drive-string", "mixed-elements", "empty-element", "relative-element", "blank-element"],
)
def test_invalid_saved_roots_rejected_before_core(tmp_path, monkeypatch, key, malformed):
    root = tmp_path / "store"
    valid_path = str(tmp_path.resolve())
    values = {
        "drive-string": tmp_path.anchor,
        "mixed-elements": [valid_path, 42],
        "empty-element": [""],
        "relative-element": ["relative-inputs"],
        "blank-element": ["   "],
    }
    atomic_json(root / "settings.json", {key: values[malformed]})
    original = (root / "settings.json").read_bytes()
    core_constructions = []

    def forbidden_core(*args, **kwargs):
        core_constructions.append((args, kwargs))
        raise AssertionError("Malformed stored authorization reached Core construction")

    monkeypatch.setattr("matlab_companion.coordinator.Core", forbidden_core)
    # A regression must remain non-native even if validation lets it reach run().
    monkeypatch.setattr(
        "matlab_companion.coordinator.LocalListener",
        lambda *args, **kwargs: SimpleNamespace(close=lambda: None),
    )
    with pytest.raises((SetupError, ValueError, TypeError)):
        Coordinator(root).run()
    assert not core_constructions
    assert (root / "settings.json").read_bytes() == original
    assert not (root / "jobs").exists()


def test_explicit_relative_roots_resolve_but_saved_empty_list_stays_unprivileged(tmp_path):
    root = tmp_path / "store"
    atomic_json(root / "settings.json", {"allowed_roots": [], "output_roots": []})
    empty, _ = resolved_configuration(root)
    assert empty["allowed_roots"] == empty["output_roots"] == []
    explicit, _ = resolved_configuration(root, ["relative-inputs"], ["relative-outputs"])
    assert explicit["allowed_roots"] == [str(Path("relative-inputs").resolve())]
    assert explicit["output_roots"] == [str(Path("relative-outputs").resolve())]


@pytest.mark.parametrize("command", ["serve", "status", "setup", "self-test"])
def test_private_startup_token_cannot_be_used_by_other_entrypoints(tmp_path, monkeypatch, command):
    import sys

    from matlab_companion.__main__ import main

    root = tmp_path / "absent-cli-root"
    monkeypatch.setattr(
        sys,
        "argv",
        ["companion", command, "--root", str(root), "--startup-attempt-id", str(uuid.uuid4())],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not root.exists()


@pytest.mark.parametrize("token", ["not-a-uuid", "{00000000-0000-0000-0000-000000000000}"])
def test_malformed_startup_token_is_rejected_before_coordinator_root(tmp_path, monkeypatch, token):
    import sys

    from matlab_companion.__main__ import main

    root = tmp_path / "absent-cli-root"
    monkeypatch.setattr(
        sys,
        "argv",
        ["companion", "coordinator", "--root", str(root), "--startup-attempt-id", token],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not root.exists()
