"""Read-only installation observations; no coordinator, queue recovery or workers."""

from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import ValidationError

from .backend import OfficialBackend
from .contracts import PARAMETER_MODELS, StatusOutput
from .storage import default_root, read_json, utc_now


def resolve_root(root: str | Path | None = None) -> Path:
    """Resolve an installation identity without creating its directory."""
    return (Path(root).expanduser() if root is not None else default_root()).resolve()


def status_fields(root: Path, *, backend=None) -> dict:
    """Read status fields for an already resolved root, without constructing Core."""
    available = (backend if backend is not None else OfficialBackend(root)).available()
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
    return {
        "backend": {
            "state": state,
            "reason": reason,
            "matlab_version": observed.get("matlab_version"),
            "matlab_release": observed.get("matlab_release"),
        },
        "capabilities": [
            {"name": operation, "state": state, "reason": reason}
            for operation in PARAMETER_MODELS
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
