"""Known job identity survives unreadable or damaged durable state."""

import json
import uuid

import pytest
from jsonschema import Draft202012Validator

import matlab_companion.core as core_module
from matlab_companion.contracts import TOOL_OUTPUT_MODELS
from matlab_companion.core import Core
from matlab_companion.storage import atomic_json


@pytest.fixture
def stored_job(tmp_path):
    core = Core(tmp_path)
    job_id = str(uuid.uuid4())
    state_path = tmp_path / "jobs" / job_id / "state.json"
    atomic_json(
        state_path,
        {
            "job_id": job_id,
            "operation": "data_profile",
            "state": "queued",
            "summary": "Accepted portable fixture; no backend was dispatched",
        },
    )
    try:
        yield core, job_id, state_path
    finally:
        core.close()


def assert_known_job_error(output, job_id, code):
    assert not output["ok"]
    assert output["job_id"] == job_id
    assert output["job"] is None
    assert output["result"] is None
    assert output["error"]["code"] == code
    assert not output["error"]["retryable"]
    model = TOOL_OUTPUT_MODELS["matlab_job"]
    Draft202012Validator(model.model_json_schema()).validate(output)
    assert json.loads(model.model_validate(output).model_dump_json()) == output


def test_unreadable_state_preserves_the_waiting_job_without_repair_or_dispatch(
    stored_job, monkeypatch
):
    core, job_id, state_path = stored_job
    before = state_path.read_bytes()
    original_read = core_module.read_json
    reads = []

    def denied_state(path):
        if path == state_path:
            reads.append(path)
            raise PermissionError("Portable state read denial")
        return original_read(path)

    monkeypatch.setattr(core_module, "read_json", denied_state)
    output = core.call(
        "matlab_job",
        {
            "job_id": job_id,
            "action": "wait",
            "timeout_seconds": 0,
        },
    )
    assert_known_job_error(output, job_id, "FILE_ACCESS_FAILED")
    assert reads == [state_path]
    assert state_path.read_bytes() == before
    assert not core.futures
    assert not (state_path.parent / "dispatch.json").exists()


@pytest.mark.parametrize("damaged", [b'{"state":', b'{"state":"completed"}'])
def test_bad_state_preserves_known_identity_and_original_evidence(stored_job, damaged):
    core, job_id, state_path = stored_job
    state_path.write_bytes(damaged)
    output = core.call("matlab_job", {"job_id": job_id, "action": "status"})
    assert_known_job_error(output, job_id, "INPUT_INVALID")
    assert state_path.read_bytes() == damaged
    assert not core.futures
    assert not (state_path.parent / "dispatch.json").exists()


def test_missing_state_keeps_the_requested_legal_identity(stored_job):
    core, job_id, state_path = stored_job
    state_path.unlink()
    output = core.call("matlab_job", {"job_id": job_id})
    assert_known_job_error(output, job_id, "INPUT_INVALID")
    assert not state_path.exists()


@pytest.mark.parametrize(
    "invalid", [True, 1234, "not-a-job", "a" * 32, "-" * 36, "aaaaaaaa--bbbb-cccc-ddddeeeeeeeeeeee"]
)
def test_invalid_input_identifier_is_never_promoted_into_the_error_contract(stored_job, invalid):
    core, _, _ = stored_job
    output = core.call("matlab_job", {"job_id": invalid, "action": "wait", "timeout_seconds": 0})
    assert not output["ok"]
    assert output["job_id"] is None
    Draft202012Validator(TOOL_OUTPUT_MODELS["matlab_job"].model_json_schema()).validate(output)
