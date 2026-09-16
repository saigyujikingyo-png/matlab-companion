"""Read-only installation observations; no coordinator, queue recovery or workers."""

from __future__ import annotations

import os
import stat
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from .backend import OfficialBackend
from .contracts import PARAMETER_MODELS, JobSummary, StatusOutput
from .storage import default_root, read_json, utc_now


def resolve_root(root: str | Path | None = None) -> Path:
    """Resolve an installation identity without creating its directory."""
    return (Path(root).expanduser() if root is not None else default_root()).resolve()


def storage_observation(root: Path, *, max_entries=10_000, max_seconds=0.25):
    """Bounded metadata scan; no scientific payload reads, traversal of links or cleanup."""
    jobs = root / "jobs"
    observed = {
        "max_active_jobs": 10,
        "active_jobs": 0,
        "retained_jobs": 0,
        "storage_bytes": 0,
        "storage_complete": True,
        "retention": "explicit_removal_only",
        "automatic_cleanup": False,
        "observed_at": utc_now(),
    }
    if not jobs.exists():
        return observed
    deadline = time.monotonic() + max_seconds
    seen = 0
    top_directories = set()
    state_directories = set()
    stack = [jobs]
    try:
        info = jobs.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError("Job store is a link")
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    if seen >= max_entries or time.monotonic() >= deadline:
                        raise TimeoutError("Accounting scan limit")
                    seen += 1
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                        # An AF_UNIX socket is not a regular file and is not followed.
                        if getattr(info, "st_reparse_tag", 0) != 0x80000023:
                            observed["storage_complete"] = False
                        continue
                    path = Path(entry.path)
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(path)
                        if directory == jobs:
                            top_directories.add(path)
                            observed["retained_jobs"] += 1
                    elif stat.S_ISREG(info.st_mode):
                        observed["storage_bytes"] += info.st_size
                        if directory.parent == jobs and entry.name == "state.json":
                            if info.st_size > 64 * 1024:
                                raise ValueError("Oversized state metadata")
                            state = JobSummary.model_validate(read_json(path))
                            observed["active_jobs"] += state.state in {
                                "queued",
                                "running",
                                "cancel_requested",
                            }
                            state_directories.add(directory)
        if top_directories != state_directories:
            observed["storage_complete"] = False
    except (OSError, ValueError, TypeError, KeyError):
        observed["storage_complete"] = False
    if not observed["storage_complete"]:
        observed["active_jobs"] = None
    return observed


def status_fields(root: Path, *, backend=None) -> dict:
    """Read status fields for an already resolved root, without constructing Core."""
    adapter = backend if backend is not None else OfficialBackend(root)
    available = adapter.available()
    observation = root / "native-observation.json"
    observed = read_json(observation) if observation.is_file() else {}
    if not isinstance(observed, dict):
        raise TypeError("Native observation must be an object")
    state = "unverified" if available else "unavailable"
    reason = (
        "Installed backend detected; use a synthetic workflow to verify native capability."
        if available
        else "Complete setup and select a licensed MATLAB installation."
    )
    if available and isinstance(adapter, OfficialBackend) and not adapter.supports_native_exit():
        state = "unsupported"
        reason = "Native process exit observation is supported only on Windows in this preview; no native call can start on this platform."
    return {
        "runtime": storage_observation(root),
        "backend": {
            "state": state,
            "reason": reason,
            "matlab_version": observed.get("matlab_version"),
            "matlab_release": observed.get("matlab_release"),
        },
        "capabilities": [
            {"name": operation, "state": state, "reason": reason} for operation in PARAMETER_MODELS
        ],
    }


def passive_status(root: Path, *, backend=None) -> dict:
    """Return the public validated status contract using only passive reads."""
    result = {
        "request_id": str(uuid.uuid4()),
        "observed_at": utc_now(),
        "ok": True,
        "operation": "matlab_status",
    }
    try:
        result.update(status_fields(root, backend=backend))
    except (ValueError, TypeError, KeyError):
        result.update(
            ok=False,
            error={
                "code": "INPUT_INVALID",
                "message": "Saved installation settings or native observations could not be read. They were preserved for review.",
            },
        )
    except OSError:
        result.update(
            ok=False,
            error={
                "code": "FILE_ACCESS_FAILED",
                "message": "The selected file or output directory could not be accessed.",
            },
        )
    try:
        return StatusOutput.model_validate(result).model_dump(mode="json")
    except ValidationError:
        return StatusOutput.model_validate(
            {
                "request_id": result["request_id"],
                "observed_at": result["observed_at"],
                "ok": False,
                "error": {
                    "code": "OUTPUT_CONTRACT_INVALID",
                    "message": "Saved status observation did not match the output contract. It was preserved for review.",
                },
            }
        ).model_dump(mode="json")
