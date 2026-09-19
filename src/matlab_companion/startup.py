"""Private startup admission. No Core, scientific recovery, or process signalling.

Callers hold the bounded startup lock for every journal operation. Coordinators
hold lifetime ownership first; launchers only probe that lock with timeout zero.
Timestamps are observations, never leases. Uncertainty cannot authorize Popen.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .storage import atomic_json, file_lock, process_start_identity, utc_now

MAX_RECORD_BYTES = 64 * 1024
LOCK_SECONDS = 10.0
Text = Annotated[str, Field(min_length=1, max_length=4096)]
Identifier = Annotated[str, Field(min_length=1, max_length=256)]
Phase = Literal[
    "intent",
    "spawn_requested",
    "owner_claimed",
    "core_admitted",
    "stopping",
    "failed_before_spawn",
    "owner_exited",
]
TERMINAL = {"failed_before_spawn", "owner_exited"}
TRANSITIONS = {
    "intent": {"spawn_requested", "owner_claimed", "failed_before_spawn"},
    "spawn_requested": {"owner_claimed", "failed_before_spawn"},
    "owner_claimed": {"core_admitted", "owner_exited"},
    "core_admitted": {"stopping", "owner_exited"},
    "stopping": {"owner_exited"},
    "failed_before_spawn": set(),
    "owner_exited": set(),
}


def canonical_uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("A canonical UUID is required")
    return value


def image_path(value):
    return os.path.normcase(str(Path(value).resolve()))


class StartupError(Exception):
    def __init__(self, code, message, attempt_id=None):
        self.code = code
        self.attempt_id = attempt_id
        self.message = message + (f" Startup attempt: {attempt_id}." if attempt_id else "")
        super().__init__(self.message)


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    pid: int = Field(gt=0, le=0xFFFFFFFF)
    process_start: Identifier | None = None
    executable: Text | None = None

    @field_validator("executable")
    @classmethod
    def absolute_image(cls, value):
        if value is not None and not Path(value).is_absolute():
            raise ValueError("A process image must be absolute")
        return value

    @property
    def complete(self):
        return self.process_start is not None and self.executable is not None


class Owner(Identity):
    process_start: Identifier
    executable: Text
    instance_id: str

    _instance_uuid = field_validator("instance_id")(canonical_uuid)


class Attempt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: Literal[1]
    attempt_id: str
    revision: int = Field(ge=1)
    root: Text
    configuration_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    runtime_version: Identifier
    ipc_protocol: int = Field(ge=1)
    launch_executable: Text
    expected_owner_executable: Text
    launch_shape: Literal["direct_verified", "wrapper_or_unverified"]
    origin: Literal["managed_spawn", "explicit_in_process"]
    initiator: Identity
    launcher: Identity | None
    owner: Owner | None
    phase: Phase
    observed_at: Identifier
    last_observation: Identifier
    terminal_evidence: Literal["popen_not_invoked", "identified_process_chain_retired"] | None

    _attempt_uuid = field_validator("attempt_id")(canonical_uuid)

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema(cls, value):
        if type(value) is not int:
            raise ValueError("An integer schema version is required")
        return value

    @field_validator("root", "launch_executable", "expected_owner_executable")
    @classmethod
    def absolute_scope(cls, value):
        if not Path(value).is_absolute():
            raise ValueError("Startup scope paths must be absolute")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.phase in {"owner_claimed", "core_admitted", "stopping", "owner_exited"}:
            if self.owner is None:
                raise ValueError("An owner phase needs complete self-claimed identity")
        elif self.owner is not None:
            raise ValueError("An unclaimed phase cannot have an owner")
        if self.phase == "failed_before_spawn":
            if self.terminal_evidence != "popen_not_invoked" or self.launcher is not None:
                raise ValueError("Noncreation requires a pre-invocation fact")
        elif self.phase == "owner_exited":
            if self.terminal_evidence != "identified_process_chain_retired":
                raise ValueError("Retirement requires independent process-chain evidence")
        elif self.terminal_evidence is not None:
            raise ValueError("Pending attempts cannot have terminal evidence")
        if self.owner and image_path(self.owner.executable) != image_path(
            self.expected_owner_executable
        ):
            raise ValueError("Owner executable conflicts with intent")
        if self.origin == "explicit_in_process" and (
            self.launcher is not None or self.phase == "spawn_requested"
        ):
            raise ValueError("Explicit in-process admission cannot request a launch")
        if self.launcher is not None and self.phase == "intent":
            raise ValueError("A launcher cannot precede the spawn request")
        return self


@dataclass(frozen=True)
class Observation:
    state: Literal["live", "exited", "different", "unknown"]
    identity: Identity


def observe(pid, expected=None):
    """Read identity and exit together, never infer death from query denial."""
    partial = Identity(pid=pid)
    if expected is not None and not expected.complete:
        return Observation("unknown", partial)
    if os.name == "nt":
        from .native_session import WindowsProcess

        process = None
        try:
            process = WindowsProcess(pid)
            identity = Identity(
                **{k: process.identity[k] for k in ("pid", "process_start", "executable")}
            )
            state = "exited" if process.exited() else "live"
        except OSError as error:
            # WindowsProcess reports Win32 codes in errno. Only OpenProcess's
            # ERROR_INVALID_PARAMETER for this positive PID establishes absence.
            absent = error.errno == 87 and error.strerror == "Native process handle unavailable"
            return Observation("exited" if absent else "unknown", partial)
        finally:
            if process is not None:
                process.close()
    elif sys.platform.startswith("linux"):
        proc = Path("/proc") / str(pid)
        try:
            before = process_start_identity(pid)
            stat = (proc / "stat").read_text(encoding="ascii")
            zombie = stat.rsplit(")", 1)[1].split()[0] in {"Z", "X"}
            if (
                zombie
                and expected is not None
                and expected.complete
                and before == expected.process_start
            ):
                executable = expected.executable
            else:
                executable = str((proc / "exe").resolve(strict=True))
            after = process_start_identity(pid)
            if not before or before != after:
                return Observation("unknown", partial)
            identity = Identity(pid=pid, process_start=before, executable=executable)
            state = "exited" if stat.rsplit(")", 1)[1].split()[0] in {"Z", "X"} else "live"
        except FileNotFoundError:
            # Missing exe for a zombie is not, alone, proof of process absence.
            return Observation("unknown" if proc.exists() else "exited", partial)
        except (OSError, ValueError, IndexError):
            return Observation("unknown", partial)
    else:
        return Observation("unknown", partial)
    if expected is not None:
        if not expected.complete:
            return Observation("unknown", identity)
        if identity.process_start != expected.process_start:
            return Observation("different", identity)
        if image_path(identity.executable) != image_path(expected.executable):
            return Observation("unknown", identity)
    return Observation(state, identity)


def bounded_json(path):
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_RECORD_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_RECORD_BYTES:
        raise ValueError("Startup metadata exceeds its size bound")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("Duplicate metadata key")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except RecursionError as error:
        raise ValueError("Startup metadata nesting exceeds the parser bound") from error
    if not isinstance(value, dict):
        raise TypeError("Startup metadata must be an object")
    return value


class Startup:
    def __init__(self, root, fingerprint, version, protocol):
        self.root = Path(root).resolve()
        self.fingerprint, self.version, self.protocol = fingerprint, version, protocol
        self.path = self.root / "coordinator-start.json"
        self.ready_path = self.root / "coordinator.json"

    def error(self, code, message, attempt=None):
        return StartupError(code, message, attempt.attempt_id if attempt else None)

    @contextlib.contextmanager
    def locked(self, timeout=LOCK_SECONDS):
        try:
            with file_lock(self.root / ".coordinator-start.lock", timeout=timeout):
                yield
        except TimeoutError:
            try:
                attempt = self.read()
            except StartupError:
                attempt = None
            raise self.error(
                "COORDINATOR_START_BUSY",
                "Startup ownership is busy; no process was launched.",
                attempt,
            ) from None

    def read(self):
        try:
            value = bounded_json(self.path)
            return Attempt.model_validate(value) if value is not None else None
        except (OSError, ValueError, TypeError) as error:
            raise StartupError(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup metadata cannot be validated; it was preserved.",
            ) from error

    def read_ready(self):
        try:
            value = bounded_json(self.ready_path)
            if value is None:
                return None
            Owner.model_validate(
                {k: value[k] for k in ("pid", "process_start", "executable", "instance_id")}
            )
            if value["state"] != "ready" or type(value["protocol"]) is not int:
                raise ValueError("Invalid readiness metadata")
            if not all(
                isinstance(value[k], str) for k in ("root", "version", "configuration_sha256")
            ):
                raise ValueError("Invalid readiness scope")
            endpoint = value["endpoint"]
            if not isinstance(endpoint, dict) or set(endpoint) != {"kind", "address"}:
                raise ValueError("Invalid endpoint")
            if not all(isinstance(v, str) and v for v in endpoint.values()):
                raise ValueError("Invalid endpoint values")
            if "startup_attempt_id" in value:
                canonical_uuid(value["startup_attempt_id"])
            return value
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise StartupError(
                "COORDINATOR_START_RECORD_INVALID",
                "Readiness metadata cannot be validated; it was preserved.",
            ) from error

    def scope(self, root, fingerprint, version, protocol, attempt=None):
        if version != self.version or protocol != self.protocol:
            raise self.error(
                "COORDINATOR_VERSION_CONFLICT",
                "A different runtime owns this root; preserve its work and ownership.",
                attempt,
            )
        if root != str(self.root) or fingerprint != self.fingerprint:
            raise self.error(
                "COORDINATOR_CONFIGURATION_CHANGED",
                "Existing ownership uses different setup settings; preserve its work and ownership.",
                attempt,
            )

    def check_scope(self, attempt):
        self.scope(
            attempt.root,
            attempt.configuration_sha256,
            attempt.runtime_version,
            attempt.ipc_protocol,
            attempt,
        )

    def write(self, attempt):
        value = attempt.model_dump(mode="json")
        if (
            len(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")) + 1
            > MAX_RECORD_BYTES
        ):
            raise ValueError("Startup publication exceeds its size bound")
        atomic_json(self.path, value)
        if self.read() != attempt:
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup publication readback did not match; no further launch is authorized.",
                attempt,
            )
        return attempt

    def update(self, expected, **changes):
        current = self.read()
        if current != expected:
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup identity or revision changed; the newer record was preserved.",
                current or expected,
            )
        if set(changes) - {
            "phase",
            "owner",
            "launcher",
            "launch_shape",
            "last_observation",
            "terminal_evidence",
        }:
            raise ValueError("Immutable startup scope cannot change")
        phase = changes.get("phase", current.phase)
        if phase != current.phase and phase not in TRANSITIONS[current.phase]:
            raise ValueError("Impossible startup transition")
        if (
            "owner" in changes
            and current.owner is not None
            and changes["owner"] != current.owner.model_dump()
        ):
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID", "An existing owner cannot be rebound.", current
            )
        if "launcher" in changes and current.launcher is not None:
            raise ValueError("A launch identity can only be recorded once")
        updated = Attempt.model_validate(
            current.model_dump()
            | changes
            | {"revision": current.revision + 1, "observed_at": utc_now()}
        )
        return self.write(updated)

    def note(self, expected, observation):
        # An observer must not turn an old snapshot into an overwrite of a claim.
        if self.read() != expected:
            return self.read()
        return self.update(expected, last_observation=observation)

    def free_lifetime(self):
        try:
            with file_lock(self.root / ".coordinator.lock", timeout=0):
                pass
        except TimeoutError:
            raise self.error(
                "COORDINATOR_START_UNCONFIRMED",
                "A lifetime owner has not been reconciled; no process was launched.",
                self.read(),
            ) from None

    def bind_ready(self, attempt, ready):
        if ready is None:
            return
        required = {
            "startup_attempt_id",
            "pid",
            "process_start",
            "executable",
            "instance_id",
            "root",
            "configuration_sha256",
            "version",
            "protocol",
        }
        if not isinstance(ready, dict) or not required <= ready.keys():
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Ready ownership metadata is incomplete; it was preserved.",
                attempt,
            )
        owner = attempt.owner
        if (
            owner is None
            or ready.get("startup_attempt_id") != attempt.attempt_id
            or any(
                ready[k] != getattr(owner, k)
                for k in ("pid", "process_start", "executable", "instance_id")
            )
            or ready["root"] != attempt.root
            or ready["configuration_sha256"] != attempt.configuration_sha256
            or ready["version"] != attempt.runtime_version
            or ready["protocol"] != attempt.ipc_protocol
            or attempt.phase not in {"core_admitted", "stopping", "owner_exited"}
        ):
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Readiness conflicts with startup ownership; both records were preserved.",
                attempt,
            )

    def reconciled(self, *, lifetime_held=False):
        attempt, ready = self.read(), self.read_ready()
        if attempt is None:
            if ready is None:
                return None, None
            if "startup_attempt_id" in ready:
                raise StartupError(
                    "COORDINATOR_START_RECORD_INVALID",
                    "New-runtime readiness has no startup journal; it was preserved.",
                )
            # Explicit Alpha.3 compatibility branch, only with no pending journal.
            identity = Identity(
                pid=ready["pid"],
                process_start=ready["process_start"],
                executable=ready["executable"],
            )
            observed = observe(identity.pid)
            if observed.state in {"exited", "different"} or (
                observed.identity.complete
                and observed.identity.process_start != identity.process_start
            ):
                return None, None
            actual = observe(os.getpid())
            permitted = {image_path(sys.executable)}
            if actual.state == "live" and actual.identity.complete:
                permitted.add(image_path(actual.identity.executable))
            if (
                observed.state != "live"
                or not observed.identity.complete
                or actual.state != "live"
                or not actual.identity.complete
                or image_path(identity.executable) not in permitted
                or image_path(observed.identity.executable)
                != image_path(actual.identity.executable)
            ):
                raise StartupError(
                    "COORDINATOR_IDENTITY_UNAVAILABLE",
                    "Legacy coordinator identity cannot be checked; it was preserved.",
                )
            self.scope(
                ready["root"], ready["configuration_sha256"], ready["version"], ready["protocol"]
            )
            return None, ready
        if attempt.root != str(self.root):
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "The journal belongs to a different root; it was preserved.",
                attempt,
            )
        self.bind_ready(attempt, ready)
        if attempt.owner is not None:
            owner = observe(attempt.owner.pid, attempt.owner)
            launcher_retired = attempt.origin == "explicit_in_process"
            if attempt.launcher is not None and attempt.launcher.complete:
                launcher_retired = observe(attempt.launcher.pid, attempt.launcher).state in {
                    "exited",
                    "different",
                }
            # A lost parent PID publication is safe only when the real owner has
            # claimed; an unknown wrapper may still exist, so do not retire it.
            if owner.state in {"exited", "different"} and launcher_retired:
                if not lifetime_held:
                    self.free_lifetime()
                if attempt.phase != "owner_exited":
                    attempt = self.update(
                        attempt,
                        phase="owner_exited",
                        terminal_evidence="identified_process_chain_retired",
                        last_observation="identified_process_chain_retired",
                    )
            elif attempt.phase in TERMINAL:
                raise self.error(
                    "COORDINATOR_START_UNCONFIRMED",
                    "Retired ownership cannot currently be reconfirmed; no process was launched.",
                    attempt,
                )
            elif ready and owner.state == "live" and attempt.phase == "core_admitted":
                self.check_scope(attempt)
                return attempt, ready
        if attempt.phase not in TERMINAL:
            self.check_scope(attempt)
        return attempt, None

    def archive(self, attempt):
        if attempt is None:
            # Stale legacy readiness must not be carried into a new journal.
            # Preserve it in a separate bounded snapshot before replacing it.
            ready = self.read_ready()
            if ready:
                path = (
                    self.root
                    / "coordinator-start-history"
                    / ("legacy-" + ready["instance_id"] + ".json")
                )
                self.archive_value(path, {"attempt": None, "ready": ready})
                self.ready_path.unlink()
            return
        if attempt.phase not in TERMINAL or self.read() != attempt:
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Only the exact reconciled terminal attempt can be archived.",
                attempt,
            )
        ready = self.read_ready()
        self.bind_ready(attempt, ready)
        path = self.root / "coordinator-start-history" / (attempt.attempt_id + ".json")
        value = {"attempt": attempt.model_dump(mode="json"), "ready": ready}
        existing = bounded_json(path)
        if existing is not None and set(existing) != {"attempt", "ready"}:
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup archive is incomplete or incompatible; it was preserved.",
                attempt,
            )
        # Resume a crash after archive publication and matching ready removal.
        if ready is None and existing and existing.get("attempt") == value["attempt"]:
            self.bind_ready(attempt, existing.get("ready"))
            value = existing
        self.archive_value(path, value)
        if ready:
            self.ready_path.unlink()

    @staticmethod
    def archive_value(path, value):
        if (
            len(json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")) + 1
            > MAX_RECORD_BYTES
        ):
            raise ValueError("Startup archive exceeds its size bound")
        existing = bounded_json(path)
        if existing is None:
            atomic_json(path, value)
        elif existing != value:
            raise StartupError(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup archive conflicts with the prior snapshot; it was preserved.",
            )
        if bounded_json(path) != value:
            raise StartupError(
                "COORDINATOR_START_RECORD_INVALID",
                "Startup archive readback failed; ownership was preserved.",
            )

    def intent(self, *, explicit=False):
        observed = observe(os.getpid())
        if observed.state != "live" or not observed.identity.complete:
            raise StartupError(
                "COORDINATOR_IDENTITY_UNAVAILABLE",
                "The initiating interpreter identity cannot be checked; no launch is authorized.",
            )
        return self.write(
            Attempt(
                schema_version=1,
                launcher=None,
                owner=None,
                terminal_evidence=None,
                attempt_id=str(uuid.uuid4()),
                revision=1,
                root=str(self.root),
                configuration_sha256=self.fingerprint,
                runtime_version=self.version,
                ipc_protocol=self.protocol,
                launch_executable=str(Path(sys.executable).resolve()),
                expected_owner_executable=observed.identity.executable,
                launch_shape="wrapper_or_unverified",
                origin="explicit_in_process" if explicit else "managed_spawn",
                initiator=observed.identity,
                phase="intent",
                observed_at=utc_now(),
                last_observation="intent_persisted",
            )
        )

    def launcher(self, attempt, process):
        observed = observe(process.pid)
        shape = "wrapper_or_unverified"
        if (
            observed.state == "live"
            and observed.identity.complete
            and image_path(observed.identity.executable) == image_path(attempt.launch_executable)
            and image_path(observed.identity.executable)
            == image_path(attempt.expected_owner_executable)
        ):
            shape = "direct_verified"
        return self.update(
            attempt,
            launcher=observed.identity.model_dump(),
            launch_shape=shape,
            last_observation="launcher_returned",
        )

    def claim(self, attempt, instance_id):
        self.check_scope(attempt)
        observed = observe(os.getpid())
        if observed.state != "live" or not observed.identity.complete:
            raise self.error(
                "COORDINATOR_IDENTITY_UNAVAILABLE",
                "Coordinator identity cannot be checked; Core was not constructed.",
                attempt,
            )
        owner = Owner(**observed.identity.model_dump(), instance_id=instance_id)
        if attempt.owner is not None:
            if attempt.owner == owner and self.read() == attempt:
                return attempt
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "This attempt already belongs to a different coordinator; Core was not constructed.",
                attempt,
            )
        if (
            attempt.origin == "managed_spawn" and attempt.phase != "spawn_requested"
        ) or attempt.phase not in {"intent", "spawn_requested"}:
            raise self.error(
                "COORDINATOR_START_RECORD_INVALID",
                "The attempt is not available for this self-claim.",
                attempt,
            )
        if image_path(owner.executable) != image_path(attempt.expected_owner_executable):
            raise self.error(
                "COORDINATOR_IDENTITY_MISMATCH",
                "Coordinator image conflicts with intent; Core was not constructed.",
                attempt,
            )
        return self.update(
            attempt,
            owner=owner.model_dump(),
            phase="owner_claimed",
            last_observation="owner_claimed",
        )

    def admit(self, attempt_id, instance_id):
        # Caller already holds lifetime ownership. Never probe it recursively.
        with self.locked():
            if attempt_id is not None:
                canonical_uuid(attempt_id)
                attempt = self.read()
                if attempt is None or attempt.attempt_id != attempt_id:
                    raise StartupError(
                        "COORDINATOR_START_RECORD_INVALID",
                        "The supplied startup attempt is missing or mismatched; Core was not constructed.",
                        attempt_id,
                    )
                self.bind_ready(attempt, self.read_ready())
            else:
                attempt, ready = self.reconciled(lifetime_held=True)
                if ready or (attempt is not None and attempt.phase not in TERMINAL):
                    raise self.error(
                        "COORDINATOR_START_UNCONFIRMED",
                        "An existing startup owner must be reconciled; Core was not constructed.",
                        attempt,
                    )
                self.archive(attempt)
                attempt = self.intent(explicit=True)
            attempt = self.claim(attempt, instance_id)
            if attempt.phase != "owner_claimed":
                raise self.error(
                    "COORDINATOR_START_RECORD_INVALID",
                    "Core admission was already used; it cannot be repeated.",
                    attempt,
                )
            return self.update(attempt, phase="core_admitted", last_observation="core_admitted")

    def stopping(self, admitted):
        with self.locked():
            current = self.read()
            if (
                current
                and current.attempt_id == admitted.attempt_id
                and current.owner == admitted.owner
                and current.phase == "core_admitted"
            ):
                self.update(current, phase="stopping", last_observation="settling_core")
