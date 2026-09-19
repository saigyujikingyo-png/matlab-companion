"""On-demand, per-user/root execution owner; private JSON RPC, never a network service."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from . import __version__
from .core import Core, WorkflowError
from .ipc import LocalListener
from .startup import Startup, StartupError
from .storage import atomic_json, file_lock, utc_now

PROTOCOL_VERSION = 1
IDLE_SECONDS = 30.0
MAX_CLIENTS = 8
# Exact returned children are retained even if ownership publication or the
# daemon waiter fails. No process in this registry is signalled.
_launches: dict[str, subprocess.Popen] = {}


def resolved_configuration(root, allowed_roots=(), output_roots=()):
    from .setup_ui import SetupError, load_settings

    root = Path(root).resolve()
    try:
        settings = load_settings(root)
    except SetupError:
        raise ValueError("Saved setup settings are invalid and were preserved") from None

    def folders(explicit, name):
        selected = explicit or settings.get(name, [])
        if not isinstance(selected, (list, tuple)) or any(
            not isinstance(item, (str, Path)) for item in selected
        ):
            raise ValueError("Authorized folders must be a list of paths")
        for item in selected:
            if not str(item).strip() or any(char in str(item) for char in ("\x00", "\r", "\n")):
                raise ValueError("Authorized folder is invalid")
            if not explicit and not Path(item).is_absolute():
                raise ValueError("Saved authorized folders must be absolute paths")
        return [str(Path(item).resolve()) for item in selected]

    value = {
        "root": str(root),
        "allowed_roots": folders(allowed_roots, "allowed_roots"),
        "output_roots": folders(output_roots, "output_roots"),
        "settings": settings,
        "matlab_override": os.environ.get("MATLAB_COMPANION_MATLAB_ROOT"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return value, fingerprint


def windows_job_observation():
    if os.name != "nt":
        return {"member": False, "limit_flags": None}
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.IsProcessInJob.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.BOOL),
    ]
    kernel.IsProcessInJob.restype = wintypes.BOOL
    result = wintypes.BOOL()
    if not kernel.IsProcessInJob(kernel.GetCurrentProcess(), None, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    flags = None
    if result.value:

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_longlong),
                ("job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active_limit", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        limits = BasicLimits()
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.LPVOID,
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        if kernel.QueryInformationJobObject(
            None, 2, ctypes.byref(limits), ctypes.sizeof(limits), None
        ):
            flags = limits.flags
    return {"member": bool(result.value), "limit_flags": flags}


def in_windows_job():
    return windows_job_observation()["member"]


def spawn_coordinator(
    root,
    allowed_roots=(),
    output_roots=(),
    *,
    idle_seconds=IDLE_SECONDS,
    startup,
    attempt,
):
    if startup.read() != attempt or attempt.phase != "spawn_requested":
        raise startup.error(
            "COORDINATOR_START_RECORD_INVALID",
            "A matching durable launch intent is required.",
            attempt,
        )
    startup.check_scope(attempt)
    try:
        config, fingerprint = resolved_configuration(root, allowed_roots, output_roots)
        startup.scope(config["root"], fingerprint, __version__, PROTOCOL_VERSION, attempt)
        if (
            not 0.1 <= idle_seconds <= 300
            or str(Path(sys.executable).resolve()) != attempt.launch_executable
        ):
            raise ValueError("Launch parameters changed before invocation")
        command = [
            sys.executable,
            "-I",
            "-B",
            "-m",
            "matlab_companion",
            "coordinator",
            "--root",
            str(Path(root).resolve()),
            "--idle-seconds",
            str(idle_seconds),
            "--startup-attempt-id",
            attempt.attempt_id,
        ]
        for flag, values in (("--allow-root", allowed_roots), ("--output-root", output_roots)):
            for value in values:
                command.extend([flag, str(Path(value).resolve())])
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "WINDIR",
                "SYSTEMROOT",
                "SYSTEMDRIVE",
                "COMSPEC",
                "PATHEXT",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "LOCALAPPDATA",
                "APPDATA",
                "HOME",
                "DISPLAY",
                "LANG",
                "LD_LIBRARY_PATH",
                "MLM_LICENSE_FILE",
                "LM_LICENSE_FILE",
                "MATLAB_COMPANION_MATLAB_ROOT",
            }
        }
        kwargs = (
            {"start_new_session": True}
            if os.name != "nt"
            else {
                "creationflags": subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW,
            }
        )
    except (OSError, ValueError, TypeError, StartupError) as error:
        # This catch ends before Popen: noncreation is a known local fact.
        startup.update(
            attempt,
            phase="failed_before_spawn",
            terminal_evidence="popen_not_invoked",
            last_observation="preflight_failed_before_popen",
        )
        raise startup.error(
            "COORDINATOR_START_BLOCKED",
            "Launch preparation failed before process creation; the noncreation record was preserved.",
            attempt,
        ) from error
    # Failure to break away is deliberately not retried as an ordinary child.
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=environment,
            **kwargs,
        )
    except OSError as error:
        with contextlib.suppress(OSError, ValueError, StartupError):
            startup.note(attempt, "spawn_exception")
        raise startup.error(
            "COORDINATOR_START_BLOCKED",
            "Independent process creation was not confirmed. No ordinary child fallback was attempted; the startup attempt was preserved.",
            attempt,
        ) from error
    _launches[attempt.attempt_id] = process
    # Capture the returned launcher before creating a thread. A Windows venv
    # launcher may be a redirector; the actual owner must claim itself separately.
    publication_error = None
    try:
        startup.launcher(attempt, process)
    except (OSError, ValueError, StartupError) as error:
        publication_error = error

    def reap():
        process.wait()
        _launches.pop(attempt.attempt_id, None)

    try:
        threading.Thread(target=reap, name="companion-owner-reaper", daemon=True).start()
    except RuntimeError as error:
        raise startup.error(
            "COORDINATOR_START_UNCONFIRMED",
            "The returned child is retained but its waiter could not start; ownership was preserved.",
            attempt,
        ) from error
    if publication_error is not None:
        raise startup.error(
            "COORDINATOR_START_UNCONFIRMED",
            "Launcher publication was not confirmed; the returned child and startup attempt were preserved.",
            attempt,
        ) from publication_error
    return process


class Coordinator:
    def __init__(
        self,
        root,
        allowed_roots=(),
        output_roots=(),
        *,
        idle_seconds=IDLE_SECONDS,
        backend=None,
        startup_attempt_id=None,
    ):
        self.root = Path(root).resolve()
        self.configuration, self.fingerprint = resolved_configuration(
            self.root, allowed_roots, output_roots
        )
        self.idle_seconds = idle_seconds
        self.backend = backend
        self.instance_id = str(uuid.uuid4())
        self.startup_attempt_id = startup_attempt_id
        self.startup = Startup(self.root, self.fingerprint, __version__, PROTOCOL_VERSION)
        self.guard = threading.Lock()
        self.inflight = 0
        self.last_request = time.monotonic()
        self.waiters = threading.BoundedSemaphore(4)

    def dispatch(self, core, method, params):
        if not isinstance(params, dict):
            raise TypeError("RPC parameters must be an object")
        if method == "call":
            from .server import INPUT_MODELS

            if set(params) != {"tool", "arguments"} or params["tool"] not in INPUT_MODELS:
                raise ValueError("Unknown private command")
            tool = params["tool"]
            arguments = (
                INPUT_MODELS[tool].model_validate(params["arguments"]).model_dump(mode="json")
            )
            waiting = tool == "matlab_job" and arguments["action"] == "wait"
            if waiting and not self.waiters.acquire(blocking=False):
                raise WorkflowError(
                    "WAIT_BUSY",
                    "Four observers are already waiting; read status or wait later.",
                    arguments["job_id"],
                )
            try:
                return core.call(tool, arguments)
            finally:
                if waiting:
                    self.waiters.release()
        if method in {"state", "result"} and set(params) == {"job_id"}:
            return (core._state if method == "state" else core.result)(params["job_id"])
        if method == "artifact_path" and set(params) == {"job_id", "artifact_id"}:
            record, path = core.artifact_path(params["job_id"], params["artifact_id"])
            return {"artifact": record, "path": str(path)}
        raise ValueError("Unknown private command")

    def handle(self, connection, core):
        request_id = None
        try:
            request = connection.recv_json(timeout=3)
            request_id = str(uuid.UUID(request["request_id"]))
            if (
                set(request) != {"protocol", "instance_id", "request_id", "method", "params"}
                or request["protocol"] != PROTOCOL_VERSION
                or request["instance_id"] != self.instance_id
            ):
                raise ValueError("Private protocol identity mismatch")
            result = self.dispatch(core, request["method"], request["params"])
            response = {
                "request_id": request_id,
                "instance_id": self.instance_id,
                "ok": True,
                "result": result,
            }
        except WorkflowError as error:
            response = {
                "request_id": request_id,
                "instance_id": self.instance_id,
                "ok": False,
                "error": {"code": error.code, "message": error.message, "job_id": error.job_id},
            }
        except (OSError, EOFError, TimeoutError, ValueError, KeyError, TypeError, ValidationError):
            response = {
                "request_id": request_id,
                "instance_id": self.instance_id,
                "ok": False,
                "error": {
                    "code": "COORDINATOR_REQUEST_FAILED",
                    "message": "The local request was not confirmed. Inspect existing work before any write retry.",
                    "job_id": None,
                },
            }
        except Exception as error:  # noqa: BLE001 - preserve the service without exposing private exceptions.
            atomic_json(
                self.root / "coordinator-error.json",
                {"error_type": type(error).__name__, "observed_at": utc_now()},
            )
            response = {
                "request_id": request_id,
                "instance_id": self.instance_id,
                "ok": False,
                "error": {
                    "code": "COORDINATOR_REQUEST_FAILED",
                    "message": "The local request was not confirmed. Inspect existing work before any write retry.",
                    "job_id": None,
                },
            }
        finally:
            # Disconnect never cancels a job or its handler; only sending the completed response fails.
            with contextlib.suppress(OSError, EOFError, TimeoutError, ValueError):
                if "response" in locals():
                    connection.send_json(response, timeout=3)
            connection.close()
            with self.guard:
                self.inflight -= 1
                self.last_request = time.monotonic()

    def run(self):
        if not 0.1 <= self.idle_seconds <= 300:
            raise ValueError("Idle lifetime must be between 0.1 and 300 seconds")
        # Breakaway is enforced by the launcher. Membership in an outer job is
        # still possible and does not identify the individual frontend's job.
        # Record it; never claim survival after the entire host/outer job closes.
        windows_job = windows_job_observation()
        self.root.mkdir(parents=True, exist_ok=True)
        with file_lock(self.root / ".coordinator.lock"):
            admitted = self.startup.admit(self.startup_attempt_id, self.instance_id)
            self.startup_attempt_id = admitted.attempt_id
            listener = core = None
            try:
                listener = LocalListener(self.root, self.instance_id, max_clients=MAX_CLIENTS)
                core = Core(
                    self.root,
                    self.configuration["allowed_roots"],
                    self.configuration["output_roots"],
                    backend=self.backend,
                )
                record = {
                    "protocol": PROTOCOL_VERSION,
                    "instance_id": self.instance_id,
                    "pid": os.getpid(),
                    "process_start": admitted.owner.process_start,
                    "version": __version__,
                    "executable": admitted.owner.executable,
                    "startup_attempt_id": admitted.attempt_id,
                    "root": str(self.root),
                    "configuration_sha256": self.fingerprint,
                    "state": "ready",
                    "observed_at": utc_now(),
                    "endpoint": {
                        "kind": listener.endpoint.kind,
                        "address": listener.endpoint.address,
                    },
                    "idle_seconds": self.idle_seconds,
                    "windows_job": windows_job,
                    "lifetime_scope": "individual_frontend_disconnect; outer host or OS termination is not covered",
                }
                with self.startup.locked():
                    current = self.startup.read()
                    if (
                        current is None
                        or current.attempt_id != admitted.attempt_id
                        or current.owner != admitted.owner
                        or current.phase != "core_admitted"
                    ):
                        raise self.startup.error(
                            "COORDINATOR_START_RECORD_INVALID",
                            "Core ownership changed before readiness; the existing Core will settle.",
                            admitted,
                        )
                    atomic_json(self.root / "coordinator.json", record)
                with ThreadPoolExecutor(
                    max_workers=MAX_CLIENTS, thread_name_prefix="companion-ipc"
                ) as handlers:
                    while True:
                        with self.guard:
                            idle = (
                                self.inflight == 0
                                and time.monotonic() - self.last_request >= self.idle_seconds
                            )
                        if idle and not core.has_active_work():
                            break
                        try:
                            connection = listener.accept(timeout=0.2)
                        except TimeoutError:
                            continue
                        with self.guard:
                            if self.inflight >= MAX_CLIENTS:
                                connection.close()
                                continue
                            self.inflight += 1
                            self.last_request = time.monotonic()
                        handlers.submit(self.handle, connection, core)
                quarantine = (self.root / "executor-quarantine.json").exists()
                active = (self.root / "executor-active.json").exists()
                atomic_json(
                    self.root / "coordinator-stopped.json",
                    {
                        "instance_id": self.instance_id,
                        "observed_at": utc_now(),
                        "reason": "idle_degraded" if quarantine or active else "idle",
                        "active_jobs": 0,
                        "quarantine_preserved": quarantine,
                        "active_marker_preserved": active,
                        "native_stop_claim": "No claim is made by idle exit; use per-job native-lifecycle evidence.",
                    },
                )
            finally:
                # Diagnostic writes and listener failures must not skip Core.close.
                # The surrounding lifetime lock stays held through all settlement.
                try:
                    with contextlib.suppress(OSError, ValueError, StartupError):
                        self.startup.stopping(admitted)
                finally:
                    try:
                        if listener is not None:
                            listener.close()
                    finally:
                        if core is not None:
                            core.close()
                with contextlib.suppress(OSError, ValueError, StartupError), self.startup.locked():
                    current = self.startup.read()
                    ready = self.startup.read_ready()
                    if (
                        current
                        and current.attempt_id == admitted.attempt_id
                        and current.owner == admitted.owner
                        and ready
                        and ready.get("startup_attempt_id") == admitted.attempt_id
                        and ready.get("instance_id") == self.instance_id
                    ):
                        self.startup.bind_ready(current, ready)
                        self.startup.ready_path.unlink()
