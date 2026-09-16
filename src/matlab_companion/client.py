"""Thin stdio-facing adapter; scientific lifetime belongs to the local coordinator."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from . import __version__
from .contracts import TOOL_OUTPUT_MODELS, JobSummary, validate_parameters
from .coordinator import IDLE_SECONDS, PROTOCOL_VERSION, resolved_configuration, spawn_coordinator
from .core import Core, WorkflowError
from .diagnostics import passive_status
from .ipc import Endpoint, connect
from .storage import file_lock, process_alive, process_start_identity, read_json


class CoordinatorClient:
    _base = staticmethod(Core._base)
    _help = staticmethod(Core._help)
    schema = staticmethod(Core.schema)

    def __init__(self, root, allowed_roots=(), output_roots=(), *, idle_seconds=IDLE_SECONDS):
        self.root = Path(root).resolve()
        self.allowed_roots = list(allowed_roots)
        self.output_roots = list(output_roots)
        self.idle_seconds = idle_seconds

    def close(self):
        """Closing a frontend does not cancel accepted work or signal its owner."""

    def _record(self):
        path = self.root / "coordinator.json"
        if not path.exists():
            return None
        record = read_json(path)
        if not process_alive(record["pid"]):
            return None
        identity = process_start_identity(record["pid"])
        if identity is not None and identity != record["process_start"]:
            return None
        if identity is None:
            raise WorkflowError(
                "COORDINATOR_IDENTITY_UNAVAILABLE",
                "Existing coordinator identity cannot be checked; it was preserved.",
            )
        if record["version"] != __version__ or record["protocol"] != PROTOCOL_VERSION:
            raise WorkflowError(
                "COORDINATOR_VERSION_CONFLICT",
                "An earlier runtime still owns this root. Let its jobs finish and its idle service exit before reconnecting.",
            )
        _, fingerprint = resolved_configuration(self.root, self.allowed_roots, self.output_roots)
        if record["root"] != str(self.root) or record["configuration_sha256"] != fingerprint:
            raise WorkflowError(
                "COORDINATOR_CONFIGURATION_CHANGED",
                "The live service uses different setup settings. Let accepted work finish and the service exit after its idle interval before reconnecting.",
            )
        return record

    def _ensure(self):
        try:
            resolved_configuration(self.root, self.allowed_roots, self.output_roots)
        except (ValueError, TypeError, OSError):
            raise WorkflowError(
                "SETUP_INVALID",
                "Saved folder permissions or settings are invalid. Review setup; existing values were preserved.",
            ) from None
        record = self._record()
        if record:
            return record
        with file_lock(self.root / ".coordinator-start.lock", timeout=10):
            record = self._record()
            if record:
                return record
            try:
                process = spawn_coordinator(
                    self.root, self.allowed_roots, self.output_roots, idle_seconds=self.idle_seconds
                )
            except OSError as error:
                raise WorkflowError(
                    "COORDINATOR_START_BLOCKED",
                    "This host did not permit an independent local process. Start Companion's job service from its setup window, then retry with the same idempotency key. No ordinary child fallback was attempted.",
                ) from error
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                record = self._record()
                if record:
                    return record
                if process.poll() is not None:
                    raise WorkflowError(
                        "COORDINATOR_START_FAILED",
                        "The independent service could not start. Existing jobs were preserved; inspect setup before retrying.",
                    )
                time.sleep(0.05)
            raise WorkflowError(
                "COORDINATOR_START_UNCONFIRMED",
                "The service did not become ready in time. Its outcome is unconfirmed; no second process was started.",
            )

    def _rpc(self, method, params):
        connection = None
        try:
            record = self._ensure()
            connection = connect(Endpoint(**record["endpoint"]), timeout=3)
            peer = connection.peer_pid()
            if peer is not None and peer != record["pid"]:
                raise WorkflowError(
                    "COORDINATOR_IDENTITY_MISMATCH",
                    "The endpoint does not belong to the recorded coordinator.",
                )
            if process_start_identity(record["pid"]) != record["process_start"]:
                raise WorkflowError(
                    "COORDINATOR_IDENTITY_MISMATCH",
                    "Coordinator identity changed before the request.",
                )
            request_id = str(uuid.uuid4())
            connection.send_json(
                {
                    "protocol": PROTOCOL_VERSION,
                    "instance_id": record["instance_id"],
                    "request_id": request_id,
                    "method": method,
                    "params": params,
                },
                timeout=3,
            )
            response = connection.recv_json(timeout=20)
            if (
                response.get("request_id") != request_id
                or response.get("instance_id") != record["instance_id"]
            ):
                raise ValueError("Response identity mismatch")
            if not response["ok"]:
                error = response["error"]
                raise WorkflowError(error["code"], error["message"], error.get("job_id"))
            return response["result"]
        except (OSError, EOFError, TimeoutError, ValueError, KeyError, TypeError) as error:
            # No automatic retransmit after a possibly accepted write.
            raise WorkflowError(
                "COORDINATOR_RESPONSE_UNCONFIRMED",
                "The local response was not confirmed. Inspect the existing job, or reuse the original idempotency key when reconnecting; do not submit a new write.",
                params.get("job_id"),
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def call(self, tool, arguments):
        if tool == "matlab_status":
            return passive_status(self.root)
        if tool == "matlab_help":
            return (
                TOOL_OUTPUT_MODELS[tool]
                .model_validate(self._base(tool) | self._help(**arguments))
                .model_dump(mode="json")
            )
        try:
            if tool == "matlab_artifacts" and arguments.get("action") == "read_schema":
                self.schema(arguments["operation"], arguments.get("schema_kind", "parameters"))
                return (
                    TOOL_OUTPUT_MODELS[tool]
                    .model_validate(self._base(tool) | {"artifacts": []})
                    .model_dump(mode="json")
                )
            if tool == "matlab_run" and arguments.get("operation") != "revise_figure":
                validate_parameters(arguments["operation"], arguments["parameters"])
            result = self._rpc("call", {"tool": tool, "arguments": arguments})
            return TOOL_OUTPUT_MODELS[tool].model_validate(result).model_dump(mode="json")
        except WorkflowError as error:
            job_id = error.job_id or arguments.get("job_id")
            return (
                TOOL_OUTPUT_MODELS[tool]
                .model_validate(
                    self._base(tool, False)
                    | {
                        "job_id": job_id,
                        "error": {"code": error.code, "message": error.message},
                    }
                )
                .model_dump(mode="json")
            )

    def _state(self, job_id):
        # Error-envelope lookups must not start a coordinator or recover work.
        if not isinstance(job_id, str):
            raise WorkflowError("INPUT_INVALID", "Invalid job identifier")
        identifier = str(uuid.UUID(job_id))
        if identifier != job_id.lower():
            raise WorkflowError("INPUT_INVALID", "Invalid job identifier")
        path = (self.root / "jobs" / identifier / "state.json").resolve()
        if not path.is_relative_to(self.root / "jobs" / identifier) or not path.is_file():
            raise WorkflowError("INPUT_INVALID", "Job was not found")
        if path.stat().st_size > 64 * 1024:
            raise WorkflowError("INPUT_INVALID", "Saved job state is too large")
        return JobSummary.model_validate(read_json(path)).model_dump(mode="json")

    def result(self, job_id):
        return self._rpc("result", {"job_id": job_id})

    def artifact_path(self, job_id, artifact_id):
        value = self._rpc("artifact_path", {"job_id": job_id, "artifact_id": artifact_id})
        path = Path(value["path"]).resolve()
        if not path.is_relative_to(self.root / "jobs" / job_id / "outputs"):
            raise WorkflowError("INPUT_UNTRUSTED", "Artifact path escaped its owning job.", job_id)
        return value["artifact"], path
