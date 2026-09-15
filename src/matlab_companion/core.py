"""Validated local workflows with durable jobs and independent file delivery."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from .backend import OfficialBackend
from .contracts import (
    PARAMETER_MODELS,
    TOOL_OUTPUT_MODELS,
    Artifact,
    JobSummary,
    operation_schemas,
    validate_native_receipt,
    validate_operation_result,
    validate_parameters,
)
from .storage import (
    atomic_json,
    contained,
    default_root,
    digest,
    file_lock,
    process_alive,
    read_json,
    utc_now,
)

MAX_INPUT_BYTES = 256 * 1024 * 1024
ACTIVE = {"queued", "running", "cancel_requested"}
UUID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
DESCRIPTIONS = {
    "data_profile": "Inspect numeric CSV columns and missing values without modifying the source.",
    "plot_xy": "Create an editable XY figure with explicit columns and units.",
    "linear_calibration": "Fit a linear calibration with explicit intercept and weighting semantics.",
    "first_order_kinetics": "Simulate first-order decay and check against its analytical solution.",
    "revise_figure": "Revise labels or limits of an owned figure while preserving its curves.",
}


class WorkflowError(Exception):
    def __init__(self, code: str, message: str, job_id: str | None = None):
        self.code, self.message, self.job_id = code, message, job_id
        super().__init__(message)


class Core:
    def __init__(self, root: Path | None = None, allowed_roots=(), output_roots=(), backend=None):
        self.root = (root or default_root()).resolve()
        self.allowed_roots = [Path(p).resolve() for p in allowed_roots]
        self.output_roots = [Path(p).resolve() for p in output_roots]
        self.backend = backend or OfficialBackend()
        for name in ("jobs", "inputs"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matlab-companion")
        self.futures = {}
        self.mutex = threading.RLock()
        self._recover_jobs()

    def close(self):
        self.pool.shutdown(wait=True)

    def _base(self, tool, ok=True):
        return {
            "request_id": str(uuid.uuid4()),
            "observed_at": utc_now(),
            "ok": ok,
            "operation": tool,
        }

    def _authorised(self, value: str, roots: list[Path]) -> Path:
        path = Path(value).resolve()
        if not any(path.is_relative_to(root) for root in roots):
            raise WorkflowError("INPUT_INVALID", "Choose this file or destination in setup first.")
        return path

    def _job_path(self, job_id: str) -> Path:
        if not isinstance(job_id, str) or not UUID_PATTERN.fullmatch(job_id):
            raise WorkflowError("INPUT_INVALID", "Invalid job identifier")
        return contained(self.root / "jobs" / str(uuid.UUID(job_id)), self.root / "jobs")

    def _state(self, job_id):
        path = self._job_path(job_id) / "state.json"
        if not path.is_file():
            raise WorkflowError("INPUT_INVALID", "Job was not found")
        return JobSummary.model_validate(read_json(path)).model_dump(mode="json")

    def _save_state(self, job_id, expected_states=None, **changes):
        with file_lock(self._job_path(job_id) / ".state.lock", timeout=10):
            state = self._state(job_id)
            if expected_states is not None and state["state"] not in expected_states:
                return state
            state.update(changes)
            state = JobSummary.model_validate(state).model_dump(mode="json")
            atomic_json(self._job_path(job_id) / "state.json", state)
            return state

    def _recover_jobs(self):
        """Do not replay a native dispatch whose coordinator disappeared."""
        with file_lock(self.root / ".recovery.lock", timeout=10):
            for path in (self.root / "jobs").glob("*/state.json"):
                state = read_json(path)
                if state.get("state") not in ACTIVE:
                    continue
                job = path.parent
                dispatch = job / "dispatch.json"
                scheduler = job / "scheduler.json"
                owner_file = dispatch if dispatch.exists() else scheduler
                owner = read_json(owner_file) if owner_file.exists() else {}
                if process_alive(owner.get("coordinator_pid", 0)):
                    continue
                if dispatch.exists() or state["state"] != "queued":
                    atomic_json(
                        self.root / "executor-quarantine.json",
                        {
                            "job_id": state["job_id"],
                            "reason": "Coordinator exited after native dispatch; executor quiescence is unconfirmed.",
                        },
                    )
                    self._save_state(
                        state["job_id"],
                        state="unknown",
                        summary="Coordinator exited; native outcome is unknown",
                        error={
                            "code": "OUTCOME_UNKNOWN",
                            "message": "Reconcile the existing receipt; do not replay this write.",
                        },
                    )
                    if (job / "receipt.json").exists():
                        self._reconcile(state["job_id"])
                else:
                    atomic_json(
                        scheduler, {"coordinator_pid": os.getpid(), "accepted_at": utc_now()}
                    )
                    self.futures[state["job_id"]] = self.pool.submit(self._execute, state["job_id"])

    def call(self, tool: str, arguments: dict) -> dict:
        if tool not in TOOL_OUTPUT_MODELS:
            raise ValueError("Unknown tool")
        try:
            if not isinstance(arguments, dict):
                raise WorkflowError("INPUT_INVALID", "Arguments must be an object")
            handler = getattr(self, "_" + tool.removeprefix("matlab_"))
            result = self._base(tool)
            result.update(handler(**arguments))
        except WorkflowError as error:
            result = self._base(tool, False) | {
                "job_id": error.job_id,
                "error": {"code": error.code, "message": error.message[:2000]},
            }
        except (ValidationError, ValueError, TypeError, FileNotFoundError, KeyError) as error:
            message = (
                "Invalid or unavailable input; consult operation help and registered file IDs."
            )
            if isinstance(error, ValidationError):
                message = "; ".join(
                    ".".join(str(x) for x in e["loc"]) + ": " + e["msg"]
                    for e in error.errors(
                        include_input=False, include_url=False, include_context=False
                    )[:4]
                )
            result = self._base(tool, False) | {
                "error": {"code": "INPUT_INVALID", "message": message[:2000]}
            }
        except OSError:
            result = self._base(tool, False) | {
                "error": {
                    "code": "FILE_ACCESS_FAILED",
                    "message": "The selected file or output directory could not be accessed.",
                }
            }
        # A malformed result never goes to a host as success. Preserve known job identity.
        try:
            return TOOL_OUTPUT_MODELS[tool].model_validate(result).model_dump(mode="json")
        except ValidationError:
            failure = self._base(tool, False) | {
                "job_id": result.get("job_id"),
                "error": {
                    "code": "OUTPUT_CONTRACT_INVALID",
                    "message": "Result validation failed; inspect the existing job before retrying.",
                },
            }
            return TOOL_OUTPUT_MODELS[tool].model_validate(failure).model_dump(mode="json")

    def _status(self):
        available = self.backend.available()
        observation = self.root / "native-observation.json"
        observed = read_json(observation) if observation.is_file() else {}
        state = "unverified" if available else "unavailable"
        reason = (
            "Installed backend detected; use a synthetic workflow to verify native capability."
            if available
            else "Complete setup and select a licensed MATLAB installation."
        )
        return {
            "backend": {
                "state": state,
                "reason": reason,
                "matlab_version": observed.get("matlab_version"),
                "matlab_release": observed.get("matlab_release"),
            },
            "capabilities": [
                {
                    "name": op,
                    "state": "unverified" if available else "unavailable",
                    "reason": reason,
                }
                for op in PARAMETER_MODELS
            ],
        }

    def _help(self, operation=None):
        names = [operation] if operation is not None else list(PARAMETER_MODELS)
        if any(name not in PARAMETER_MODELS for name in names):
            raise WorkflowError("CAPABILITY_UNSUPPORTED", "Operation is not implemented")
        return {
            "operations": [
                {
                    "operation": op,
                    "summary": DESCRIPTIONS[op],
                    "requires_input": op not in {"first_order_kinetics", "revise_figure"},
                    "parameter_schema_uri": f"matlab-companion://schemas/{op}/parameters",
                    "result_schema_uri": f"matlab-companion://schemas/{op}/result",
                }
                for op in names
            ]
        }

    def _inspect(self, path: str):
        source = self._authorised(path, self.allowed_roots)
        if source.suffix.lower() not in {".csv", ".tsv"}:
            raise WorkflowError(
                "INPUT_UNTRUSTED",
                "This preview accepts CSV/TSV; arbitrary MAT/FIG loading is not enabled.",
            )
        size = source.stat().st_size
        if size > MAX_INPUT_BYTES:
            raise WorkflowError("INPUT_INVALID", "Input exceeds the 256 MiB preview limit")
        with source.open(encoding="utf-8-sig", newline="") as stream:
            header = next(
                csv.reader(stream, delimiter="\t" if source.suffix.lower() == ".tsv" else ","), []
            )
        if (
            not header
            or len(header) > 1000
            or len(set(header)) != len(header)
            or any(not x or len(x) > 200 for x in header)
        ):
            raise WorkflowError(
                "INPUT_INVALID",
                "CSV headers must be unique nonempty names, at most 200 characters and 1000 columns.",
            )
        checksum = digest(source)
        input_id = "input-" + checksum[:32]
        record = {
            "input_id": input_id,
            "name": source.name,
            "media_type": "text/csv"
            if source.suffix.lower() == ".csv"
            else "text/tab-separated-values",
            "size_bytes": size,
            "sha256": checksum,
            "trust": "tabular_input",
            "profile": None,
        }
        atomic_json(
            self.root / "inputs" / f"{input_id}.json", {"metadata": record, "path": str(source)}
        )
        return {"input": record}

    def _run(
        self,
        operation: str,
        parameters: dict,
        idempotency_key: str,
        input_id=None,
        source_job_id=None,
        source_artifact_id=None,
        expected_revision=None,
    ):
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise WorkflowError("INPUT_INVALID", "Supply an idempotency key of 1 to 128 characters")
        parameters = dict(parameters)
        source = None
        input_record = None
        source_record = None
        if operation == "revise_figure":
            if "source_figure" in parameters:
                raise WorkflowError(
                    "INPUT_UNTRUSTED",
                    "Choose an owned figure artifact; arbitrary figure paths are not accepted.",
                )
            if expected_revision != source_job_id:
                raise WorkflowError(
                    "REVISION_CONFLICT", "expected_revision must match the source job revision"
                )
            source_record, source = self.artifact_path(source_job_id, source_artifact_id)
            if source_record["role"] != "native_figure":
                raise WorkflowError(
                    "INPUT_INVALID", "Source artifact must be an owned native figure"
                )
            parameters["source_figure"] = str(source)
        elif operation != "first_order_kinetics":
            if not isinstance(input_id, str) or not ID_PATTERN.fullmatch(input_id):
                raise WorkflowError(
                    "INPUT_INVALID", "Inspect and register a selected input file first"
                )
            input_record = read_json(self.root / "inputs" / f"{input_id}.json")
            source = self._authorised(input_record["path"], self.allowed_roots)
            if digest(source) != input_record["metadata"]["sha256"]:
                raise WorkflowError(
                    "REVISION_CONFLICT", "Input changed after inspection; inspect it again"
                )
        parameters = validate_parameters(operation, parameters)
        signature = hashlib.sha256(
            json.dumps(
                {
                    "operation": operation,
                    "parameters": parameters,
                    "input": input_record["metadata"]["sha256"] if input_record else None,
                    "source": source_record["sha256"] if source_record else None,
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        key = hashlib.sha256(idempotency_key.encode()).hexdigest()
        with self.mutex, file_lock(self.root / ".index.lock", timeout=10):
            index_path = self.root / "idempotency.json"
            index = read_json(index_path) if index_path.exists() else {}
            if key in index:
                old = index[key]
                if old["signature"] != signature:
                    raise WorkflowError(
                        "REVISION_CONFLICT",
                        "Idempotency key already identifies a different request",
                        old["job_id"],
                    )
                return {"job_id": old["job_id"], "job": self._state(old["job_id"])}
            if not self.backend.available():
                raise WorkflowError(
                    "MATLAB_NOT_FOUND",
                    "Set up the official backend and a licensed MATLAB installation first",
                )
            if (self.root / "executor-quarantine.json").exists():
                raise WorkflowError(
                    "EXECUTOR_RECOVERY_REQUIRED",
                    "An earlier native execution has an unknown outcome; recover that executor before starting another calculation.",
                )
            active = sum(
                read_json(p).get("state") in ACTIVE
                for p in (self.root / "jobs").glob("*/state.json")
            )
            if active >= 10:
                raise WorkflowError(
                    "QUEUE_FULL", "The queue contains ten active jobs; wait for an existing job"
                )
            job_id = str(uuid.uuid4())
            job = self._job_path(job_id)
            (job / "outputs").mkdir(parents=True)
            if source is not None:
                staged = job / (
                    "source.fig"
                    if operation == "revise_figure"
                    else "input" + source.suffix.lower()
                )
                shutil.copyfile(source, staged)
                expected_hash = (
                    source_record["sha256"] if source_record else input_record["metadata"]["sha256"]
                )
                if digest(staged) != expected_hash or digest(source) != expected_hash:
                    raise WorkflowError(
                        "REVISION_CONFLICT", "Input changed while staging; inspect it again"
                    )
                if operation == "revise_figure":
                    parameters["source_figure"] = str(staged)
            else:
                staged = None
            request = {
                "contract_version": "1.0",
                "job_id": job_id,
                "operation": operation,
                "parameters": parameters,
                "input_path": str(staged)
                if staged is not None and operation != "revise_figure"
                else None,
                "output_dir": str(job / "outputs"),
                "cancel_path": str(job / "cancel.flag"),
            }
            atomic_json(job / "request.json", request)
            atomic_json(
                job / "provenance.json",
                {
                    "signature": signature,
                    "input_sha256": digest(staged) if staged is not None else None,
                    "source_revision": source_job_id,
                    "accepted_at": utc_now(),
                },
            )
            state = JobSummary(
                job_id=job_id,
                operation=operation,
                state="queued",
                summary="Accepted; waiting for the owned executor",
            ).model_dump(mode="json")
            atomic_json(job / "state.json", state)
            atomic_json(
                job / "scheduler.json", {"coordinator_pid": os.getpid(), "accepted_at": utc_now()}
            )
            index[key] = {"signature": signature, "job_id": job_id}
            atomic_json(index_path, index)
            self.futures[job_id] = self.pool.submit(self._execute, job_id)
        return {"job_id": job_id, "job": state}

    def _execute(self, job_id):
        job = self._job_path(job_id)
        try:
            with file_lock(self.root / ".execution.lock", timeout=600):
                if (self.root / "executor-quarantine.json").exists():
                    self._save_state(
                        job_id,
                        state="failed",
                        summary="Waiting for recovery of a previous executor",
                        error={
                            "code": "EXECUTOR_RECOVERY_REQUIRED",
                            "message": "No native dispatch occurred for this job; recover the earlier executor.",
                        },
                    )
                    return
                if (job / "cancel.flag").exists():
                    self._save_state(
                        job_id, state="cancelled", summary="Cancelled before native dispatch"
                    )
                    return
                self._save_state(
                    job_id, state="running", summary="Running in an owned MATLAB session"
                )
                atomic_json(
                    job / "dispatch.json",
                    {
                        "coordinator_pid": os.getpid(),
                        "coordinator_identity": None,
                        "dispatched_at": utc_now(),
                    },
                )
                asyncio.run(self.backend.execute(job))
                self._reconcile(job_id)
        except Exception as error:  # noqa: BLE001 -- Native failures must preserve uncertain writes.
            (job / "cancel.flag").write_text(
                "cancel requested after loss of executor response\n", encoding="utf-8"
            )
            atomic_json(
                self.root / "executor-quarantine.json",
                {
                    "job_id": job_id,
                    "reason": "No confirmed native return; cooperative cancellation requested.",
                },
            )
            if (job / "receipt.json").exists():
                self._reconcile(job_id)
            else:
                atomic_json(
                    job / "execution-error.json",
                    {"type": type(error).__name__, "observed_at": utc_now()},
                )
                self._save_state(
                    job_id,
                    state="unknown",
                    summary="Execution outcome needs reconciliation",
                    error={
                        "code": "OUTCOME_UNKNOWN",
                        "message": "The executor stopped responding without a valid receipt; do not repeat the write.",
                    },
                )

    def _reconcile(self, job_id):
        job = self._job_path(job_id)
        manifest = job / "artifacts.json"
        committed = None
        if manifest.exists():
            # Once committed, old hashes are evidence, never a new trust baseline.
            try:
                committed = read_json(manifest)["artifacts"]
                for record in committed:
                    path = contained(job / "outputs" / record["name"], job / "outputs")
                    if (
                        not path.is_file()
                        or path.stat().st_size != record["size_bytes"]
                        or digest(path) != record["sha256"]
                    ):
                        raise ValueError("Verified artifact changed")
                current = self._state(job_id)
                if current["state"] == "completed" or (
                    current["state"] not in ACTIVE
                    and (current.get("error") or {}).get("code") != "OUTCOME_UNKNOWN"
                ):
                    return current
            except (ValueError, OSError):
                return self._save_state(
                    job_id,
                    state="failed",
                    summary="A previously verified artifact changed",
                    error={
                        "code": "REVISION_CONFLICT",
                        "message": "The original immutable artifact hashes were preserved; this revision is no longer trusted.",
                    },
                )
        if not (job / "receipt.json").exists():
            return self._state(job_id)
        try:
            if (job / "receipt.json").stat().st_size > 4 * 1024 * 1024:
                raise ValueError("Receipt too large")
            receipt = validate_native_receipt(read_json(job / "receipt.json"))
            request = read_json(job / "request.json")
            if receipt.job_id != job_id or receipt.operation != request["operation"]:
                raise ValueError("Receipt identity mismatch")
            if receipt.state != "completed":
                return self._save_state(
                    job_id,
                    state=receipt.state,
                    summary=receipt.summary,
                    error={
                        "code": receipt.error.code,
                        "message": receipt.error.message.replace(str(job), "[job]"),
                    },
                    verification=receipt.verification.model_dump(),
                )
            if not receipt.verification.native_reopen or (
                receipt.operation != "data_profile"
                and (not receipt.verification.script_rerun or not receipt.verification.numerical)
            ):
                return self._save_state(
                    job_id,
                    state="failed",
                    summary="Native verification did not complete",
                    error={
                        "code": "NATIVE_VERIFY_FAILED",
                        "message": "Required native reopen, scientific or reproduction verification is absent",
                    },
                )
            required = {"native_data", "data_export", "method"}
            if receipt.operation != "data_profile":
                required |= {"native_figure", "preview", "figure_export", "script"}
            if request["input_path"] is not None or receipt.operation == "revise_figure":
                required.add("original_input")
            if not required.issubset({item.role for item in receipt.artifacts}):
                return self._save_state(
                    job_id,
                    state="failed",
                    summary="Required output artifacts are missing",
                    error={
                        "code": "NATIVE_VERIFY_FAILED",
                        "message": "The operation did not produce its complete required artifact set.",
                    },
                )
            artifacts = []
            for entry in receipt.artifacts:
                path = contained(job / "outputs" / entry.name, job / "outputs")
                if not path.is_file() or not 0 < path.stat().st_size <= 512 * 1024 * 1024:
                    raise ValueError("Missing or oversized artifact")
                checksum = digest(path)
                artifact_id = "artifact-" + hashlib.sha256(entry.name.encode()).hexdigest()[:24]
                artifacts.append(
                    Artifact(
                        **entry.model_dump(),
                        artifact_id=artifact_id,
                        job_id=job_id,
                        size_bytes=path.stat().st_size,
                        sha256=checksum,
                        uri=f"matlab-companion://artifacts/{job_id}/{artifact_id}",
                        verified=True,
                    ).model_dump(mode="json")
                )
            if committed is not None and artifacts != committed:
                raise ValueError("Committed manifest differs from the native receipt")
            details = validate_operation_result(
                receipt.operation, receipt.details.model_dump(mode="json")
            )
            atomic_json(job / "result.json", details.model_dump(mode="json"))
            if committed is None:
                atomic_json(job / "artifacts.json", {"artifacts": artifacts})
            atomic_json(
                self.root / "native-observation.json",
                {
                    "matlab_version": receipt.matlab_version,
                    "matlab_release": receipt.matlab_release,
                    "observed_at": receipt.observed_at,
                },
            )
            return self._save_state(
                job_id,
                state="completed",
                summary=receipt.summary,
                metrics=[m.model_dump(mode="json") for m in receipt.metrics],
                verification=receipt.verification.model_dump(),
                artifact_count=len(artifacts),
                error=None,
            )
        except (ValidationError, ValueError, OSError, KeyError):
            return self._save_state(
                job_id,
                state="unknown",
                summary="Native receipt or artifacts failed validation",
                error={
                    "code": "OUTPUT_CONTRACT_INVALID",
                    "message": "Preserved this job for inspection; no automatic replay is allowed.",
                },
            )

    def _job(self, job_id, action="status"):
        if action not in {"status", "cancel", "reconcile"}:
            raise WorkflowError("INPUT_INVALID", "Unknown job action", job_id)
        state = self._state(job_id)
        if action == "cancel" and state["state"] in ACTIVE:
            (self._job_path(job_id) / "cancel.flag").write_text(
                "cancel requested\n", encoding="utf-8"
            )
            state = self._save_state(
                job_id,
                expected_states=ACTIVE,
                state="cancel_requested",
                summary="Cancellation requested; waiting for a safe native boundary",
            )
        if action == "reconcile":
            self._recover_jobs()
            state = self._reconcile(job_id)
        result = None
        if state["state"] == "completed":
            result = {
                "operation": state["operation"],
                "schema_uri": f"matlab-companion://schemas/{state['operation']}/result",
                "result_uri": f"matlab-companion://results/{job_id}",
            }
        return {"job_id": job_id, "job": state, "result": result}

    def wait(self, job_id, timeout=300):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._state(job_id)
            if state["state"] not in ACTIVE:
                return state
            time.sleep(0.05)
        raise TimeoutError("Job remains active")

    def artifact_path(self, job_id, artifact_id):
        state = self._state(job_id)
        if state["state"] != "completed":
            raise WorkflowError(
                "INPUT_INVALID", "Artifact is not from a completed verified job", job_id
            )
        records = read_json(self._job_path(job_id) / "artifacts.json")["artifacts"]
        record = next((r for r in records if r["artifact_id"] == artifact_id), None)
        if record is None:
            raise WorkflowError("INPUT_INVALID", "Artifact identifier was not found", job_id)
        path = contained(
            self._job_path(job_id) / "outputs" / record["name"], self._job_path(job_id) / "outputs"
        )
        if path.stat().st_size != record["size_bytes"] or digest(path) != record["sha256"]:
            raise WorkflowError("REVISION_CONFLICT", "Artifact changed after verification", job_id)
        return record, path

    def _artifacts(
        self,
        job_id=None,
        action="list",
        artifact_id=None,
        destination=None,
        operation=None,
        schema_kind="parameters",
    ):
        if action == "read_schema":
            self.schema(operation, schema_kind)
            return {"artifacts": []}
        if action == "read_result":
            self.result(job_id)
            return {"job_id": job_id, "artifacts": []}
        if action not in {"list", "read", "deliver"}:
            raise WorkflowError("INPUT_INVALID", "Unknown artifact action", job_id)
        self._state(job_id)
        manifest = self._job_path(job_id) / "artifacts.json"
        records = read_json(manifest)["artifacts"] if manifest.is_file() else []
        if action == "list":
            return {"job_id": job_id, "artifacts": records}
        record, source = self.artifact_path(job_id, artifact_id)
        delivery = {"artifact_id": artifact_id, "state": "available", "method": "mcp_resource"}
        if action == "deliver":
            target = self._authorised(destination, self.output_roots)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if digest(target) != record["sha256"]:
                    raise WorkflowError(
                        "REVISION_CONFLICT",
                        "Destination exists with different contents; choose a new filename",
                        job_id,
                    )
            else:
                with source.open("rb") as src, target.open("xb") as dest:
                    shutil.copyfileobj(src, dest)
            if digest(target) != record["sha256"] or target.stat().st_size != record["size_bytes"]:
                raise WorkflowError(
                    "DELIVERY_FAILED", "Destination readback did not match the original", job_id
                )
            delivery = {
                "artifact_id": artifact_id,
                "state": "verified",
                "method": "local_copy",
                "destination": str(target),
                "size_bytes": target.stat().st_size,
                "sha256": digest(target),
            }
            atomic_json(self._job_path(job_id) / f"delivery-{artifact_id}.json", delivery)
        return {"job_id": job_id, "artifacts": [record], "delivery": delivery}

    def schema(self, operation, kind="parameters"):
        if operation not in PARAMETER_MODELS or kind not in {"parameters", "result"}:
            raise WorkflowError("INPUT_INVALID", "Unknown schema")
        schema = operation_schemas()[operation][kind]
        if operation == "revise_figure" and kind == "parameters":
            schema["properties"].pop("source_figure", None)
            schema["required"] = [x for x in schema.get("required", []) if x != "source_figure"]
        return schema

    def result(self, job_id):
        state = self._state(job_id)
        if state["state"] != "completed":
            raise WorkflowError("INPUT_INVALID", "Job has no verified result", job_id)
        return validate_operation_result(
            state["operation"], read_json(self._job_path(job_id) / "result.json")
        ).model_dump(mode="json")
