"""Opt-in Windows R1 lifecycle acceptance; never imported by portable CI.

The default output is a new private temporary directory. Nothing is launched
without --run-native and explicit installed MATLAB/backend paths. The sentinel
is a separate, explicitly owned MATLAB -batch process. The interruption case
injects a *coordinator* timeout while a retained thread continues the genuine
official-backend call. It does not test upstream RPC cancellation or MATLAB
termination. No process-name search, attach, broad kill, or quarantine removal
is performed. A child Python worker bounds even a stuck backend teardown.

Requires Windows and MATLAB R2025a+ (documented matlabProcessID). References:
https://www.mathworks.com/help/matlab/ref/matlabprocessid.html
https://www.mathworks.com/help/matlab/ref/matlabwindows.html

Example, using existing authorised installations (no download):
  uv run python acceptance/native_r1_lifecycle.py --run-native \
      --matlab-root <MATLAB-installation> --backend-binary <pinned-server.exe>

An optional --public-output writes an allowlisted receipt without local paths,
process IDs, session tokens, raw errors, or environment variables. All detailed
diagnostics and unknown native work remain under the private run directory.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from ctypes import wintypes
from pathlib import Path

from matlab_companion.backend import (
    ASSETS,
    BACKEND_VERSION,
    OfficialBackend,
    backend_path,
    matlab_quote,
    native_code_root,
)
from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, digest, read_json, utc_now

POLL_SECONDS = 0.1
NATIVE_TIMEOUT = 180
WORKER_TIMEOUT = 450
SENTINEL_START_TIMEOUT = 120
SENTINEL_STOP_TIMEOUT = 45
SENTINEL_LIFETIME = SENTINEL_START_TIMEOUT + WORKER_TIMEOUT + 90
SCOPE = (
    "Windows synthetic native lifecycle and unrelated owned-session preservation; "
    "coordinator timeout injection with retained official native call. "
    "Not upstream RPC cancellation, host-model, installer, or release acceptance."
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def optional_json(path: Path) -> dict | None:
    try:
        return read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError):
        return None


class ObservedProcess:
    """Independent Win32 oracle; keep the handle to defeat PID reuse.

    This intentionally does not use production process identity/liveness code.
    Access denial or an unreadable handle is unknown, never proof of stopping.
    """

    def __init__(self, pid: int):
        require(os.name == "nt", "This acceptance oracle requires Windows")
        require(isinstance(pid, int) and pid > 0, "A native PID was not observed")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        self.kernel.GetProcessTimes.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        # QUERY_LIMITED_INFORMATION | SYNCHRONIZE; deliberately no terminate right.
        self.handle = self.kernel.OpenProcess(0x00101000, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Cannot observe the exact native process")
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(
                self.handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                raise OSError(ctypes.get_last_error(), "Cannot read process creation time")
            size = wintypes.DWORD(32768)
            executable = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(
                self.handle, 0, executable, ctypes.byref(size)
            ):
                raise OSError(ctypes.get_last_error(), "Cannot read native executable")
            self.identity = {
                "pid": pid,
                "creation_filetime": (created.dwHighDateTime << 32) | created.dwLowDateTime,
                "executable": executable.value,
            }
            require(self.state() == "alive", "Native process exited before identity capture")
        except BaseException:
            self.close()
            raise

    def state(self) -> str:
        observed = self.kernel.WaitForSingleObject(self.handle, 0)
        return {0: "exited", 258: "alive"}.get(observed, "unknown")

    def matches_matlab(self, installation: Path) -> bool:
        executable = Path(self.identity["executable"]).resolve()
        return executable.is_relative_to(installation.resolve()) and executable.name.lower() == (
            "matlab.exe"
        )

    def observation(self) -> dict:
        state = self.state()
        return {
            "identity": self.identity,
            "process_state": state,
            "native_stopped": True if state == "exited" else False if state == "alive" else None,
            "basis": "WaitForSingleObject on held native process handle with birth/executable",
            "observed_at": utc_now(),
        }

    def close(self) -> None:
        if getattr(self, "handle", None):
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def sentinel_source(directory: Path, token: str) -> str:
    """Only internally constructed paths/numeric constants enter this script."""
    return f"""% Owned R1 sentinel; independent of Companion's new-session backend.
sentinelToken = '{token}';
sentinelPid = double(matlabProcessID);
sentinelPayload = [3 1 4 1 5 9 2 6];
sentinelExpected = sentinelPayload;
sentinelFolder = pwd;
sentinelPath = path;
sentinelRng = rng;
sentinelStarted = tic;
sentinelCounter = 0;
sentinelStop = {matlab_quote(directory / "stop.flag")};
sentinelHeartbeat = {matlab_quote(directory / "heartbeat.json")};
sentinelTemporary = {matlab_quote(directory / "heartbeat.tmp")};
while toc(sentinelStarted) < {SENTINEL_LIFETIME} && ~isfile(sentinelStop)
    sentinelCounter = sentinelCounter + 1;
    sentinelState = struct('nonce', sentinelToken, 'matlab_pid', sentinelPid, ...
        'counter', sentinelCounter, 'payload', sentinelPayload, ...
        'state_preserved', isequal(sentinelPayload, sentinelExpected) && ...
            strcmp(pwd, sentinelFolder) && strcmp(path, sentinelPath) && ...
            isequal(rng, sentinelRng), ...
        'matlab_version', version, 'matlab_release', version('-release'));
    sentinelFile = fopen(sentinelTemporary, 'w', 'n', 'UTF-8');
    assert(sentinelFile ~= -1, 'R1:SentinelWrite', 'Cannot write owned heartbeat');
    fwrite(sentinelFile, jsonencode(sentinelState), 'char');
    fclose(sentinelFile);
    movefile(sentinelTemporary, sentinelHeartbeat, 'f');
    pause(0.2);
end
sentinelFile = fopen({matlab_quote(directory / "stopped.json")}, 'w', 'n', 'UTF-8');
assert(sentinelFile ~= -1, 'R1:SentinelWrite', 'Cannot write stop acknowledgement');
fwrite(sentinelFile, jsonencode(struct('nonce', sentinelToken, ...
    'matlab_pid', sentinelPid, 'counter', sentinelCounter, ...
    'cooperative_stop', isfile(sentinelStop))), 'char');
fclose(sentinelFile);
"""


class Sentinel:
    def __init__(self, root: Path, installation: Path, token: str):
        self.directory = root / "sentinel"
        self.directory.mkdir()
        self.installation = installation
        self.token = token
        self.process = None
        self.native = None
        self.log = None
        self.latest = None
        self.samples = 0
        self.first_counter = None
        self.last_advance = time.monotonic()
        self.events = []

    def start(self) -> None:
        script = self.directory / "sentinel.m"
        script.write_text(sentinel_source(self.directory, self.token), encoding="utf-8")
        self.log = (self.directory / "stdout.log").open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                str(self.installation / "bin" / "matlab.exe"),
                "-wait",
                "-noFigureWindows",
                "-sd",
                str(self.directory),
                "-batch",
                f"run({matlab_quote(script)})",
            ],
            cwd=self.directory,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + SENTINEL_START_TIMEOUT
        while time.monotonic() < deadline:
            heartbeat = optional_json(self.directory / "heartbeat.json")
            if heartbeat:
                self.native = ObservedProcess(heartbeat["matlab_pid"])
                require(
                    self.native.matches_matlab(self.installation), "Sentinel executable mismatch"
                )
                self.check("sentinel_ready")
                return
            require(self.process.poll() is None, "Sentinel exited before its first heartbeat")
            time.sleep(POLL_SECONDS)
        raise TimeoutError("Sentinel startup exceeded its bounded wait")

    def check(self, phase: str | None = None) -> dict:
        heartbeat = optional_json(self.directory / "heartbeat.json")
        require(heartbeat is not None, "Sentinel heartbeat became unreadable")
        require(heartbeat.get("nonce") == self.token, "Sentinel token changed")
        require(heartbeat.get("state_preserved") is True, "Sentinel state was changed")
        require(heartbeat.get("payload") == [3, 1, 4, 1, 5, 9, 2, 6], "Sentinel data changed")
        require(self.native.state() == "alive", "The independent sentinel is no longer alive")
        require(heartbeat["matlab_pid"] == self.native.identity["pid"], "Sentinel PID changed")
        if self.latest is None or heartbeat["counter"] > self.latest["counter"]:
            self.last_advance = time.monotonic()
        if self.latest:
            require(
                heartbeat["counter"] >= self.latest["counter"], "Sentinel heartbeat went backwards"
            )
        require(time.monotonic() - self.last_advance < 10, "Sentinel heartbeat stopped advancing")
        self.latest = heartbeat
        self.samples += 1
        if self.first_counter is None:
            self.first_counter = heartbeat["counter"]
        snapshot = {"phase": phase, "counter": heartbeat["counter"], "observed_at": utc_now()}
        if phase:
            self.events.append(snapshot)
        return snapshot

    def stop(self) -> dict:
        # Cooperative instruction only to this nonce-owned sentinel directory.
        (self.directory / "stop.flag").write_text(self.token, encoding="utf-8")
        deadline = time.monotonic() + SENTINEL_STOP_TIMEOUT
        while self.process is not None and time.monotonic() < deadline:
            if self.native is not None and self.native.state() == "exited":
                break
            if self.native is None and self.process.poll() is not None:
                break
            time.sleep(POLL_SECONDS)
        acknowledgement = optional_json(self.directory / "stopped.json")
        result = {
            "cooperative_stop_acknowledged": bool(
                acknowledgement
                and acknowledgement.get("nonce") == self.token
                and acknowledgement.get("cooperative_stop") is True
            ),
            "native_observation": self.native.observation() if self.native else None,
            "launcher_exit_code": self.process.poll() if self.process else None,
        }
        if self.native:
            self.native.close()
        if self.log:
            self.log.close()
        return result


class RetainedNativeCall:
    """Fault adapter: lose the coordinator response, retain the real native call.

    A daemon thread hosts its own event loop so asyncio.run in Core cannot
    cancel the retained call when this adapter raises the injected timeout.
    The outer owned Python worker is bounded by the controller deadline.
    """

    def __init__(self, root: Path, installation: Path):
        self.official = OfficialBackend(root, timeout=NATIVE_TIMEOUT)
        self.installation = installation
        self.calls = 0
        self.thread = None
        self.finished = threading.Event()
        self.native = None
        self.error_type = None
        self.identity = None

    def available(self) -> bool:
        return self.official.available()

    async def execute(self, job: Path) -> None:
        self.calls += 1
        require(self.calls == 1, "An uncertain native dispatch was replayed")

        def run_native():
            try:
                asyncio.run(self.official.execute(job))
            except BaseException as error:  # noqa: BLE001 -- Preserve private lifecycle diagnostics.
                self.error_type = type(error).__name__
                (job / "acceptance-retained-error.txt").write_text(
                    traceback.format_exc(), encoding="utf-8"
                )
            finally:
                self.finished.set()

        self.thread = threading.Thread(target=run_native, name="r1-retained-native", daemon=True)
        self.thread.start()
        deadline = time.monotonic() + NATIVE_TIMEOUT
        while time.monotonic() < deadline:
            session = optional_json(job / "native-session.json")
            if session is not None:
                require(session.get("job_id") == job.name, "Native session job mismatch")
                require(session.get("contract_version") == "1.0", "Native session schema mismatch")
                uuid.UUID(session["session_id"])
                self.native = ObservedProcess(session["matlab_pid"])
                require(self.native.matches_matlab(self.installation), "Native executable mismatch")
                self.identity = self.native.identity
                atomic_json(
                    job / "acceptance-injected-timeout.json",
                    {
                        "kind": "coordinator_timeout_retaining_real_native_call",
                        "session": session,
                        "native_observation": self.native.observation(),
                        "observed_at": utc_now(),
                    },
                )
                raise TimeoutError("Acceptance-only coordinator timeout; native RPC is retained")
            require(not self.finished.is_set(), "Native call ended before identity was observed")
            await asyncio.sleep(0.005)
        raise TimeoutError("Native startup identity was not observed within the acceptance bound")


def public_receipt(private: dict) -> dict:
    """Construct, rather than recursively redact, the shareable evidence."""
    worker = private.get("worker", {})
    sentinel = private.get("sentinel", {})
    normal = worker.get("normal_case")
    interruption = worker.get("interruption")
    return {
        "scope": SCOPE,
        "observed_at": private["observed_at"],
        "outcome": private.get("outcome", "failed"),
        "source_commit": private.get("source_commit"),
        "source_dirty": private.get("source_dirty"),
        "source_commit_scope": "Working-directory Git checkout; not imported-runtime binding by itself",
        "runtime_version": private.get("runtime_version"),
        "runtime_sources": private["runtime_sources"],
        "harness_sha256": private["harness_sha256"],
        "native_sources": private["native_sources"],
        "environment": {
            "platform": "Windows",
            "backend": BACKEND_VERSION,
            "matlab_release": sentinel.get("matlab_release"),
            "matlab_version": sentinel.get("matlab_version"),
        },
        "normal_case": {
            key: normal.get(key)
            for key in (
                "operation",
                "state",
                "rows",
                "verification",
                "artifact_count",
            )
        }
        if normal
        else None,
        "interruption": {
            key: interruption.get(key)
            for key in (
                "injection",
                "initial_state",
                "quarantined",
                "dispatch_preserved",
                "same_idempotency_preserved",
                "new_dispatch_blocked",
                "native_dispatch_calls",
                "late_receipt_observed",
                "reconciled_state",
                "late_receipt_state",
            )
        }
        if interruption
        else None,
        "sentinel": {
            key: sentinel.get(key)
            for key in (
                "identity_observed",
                "state_preserved",
                "heartbeat_advanced",
                "samples",
                "cooperative_stop_acknowledged",
                "native_stop_observed",
            )
        },
        "native_observations": [
            {
                "case": item["case"],
                "identity_observed": True,
                "process_state": item["observation"]["process_state"],
                "native_stopped": item["observation"]["native_stopped"],
                "basis": item["observation"]["basis"],
            }
            for item in private.get("native_observations", [])
        ],
        "worker_deadline_exceeded": private.get("worker_deadline_exceeded", False),
        "error_type": private.get("error_type"),
        "limitations": [
            "Sentinel is an explicitly owned independent test session, not a user's session.",
            "The injected coordinator timeout does not test upstream RPC cancellation.",
            "A native process is stopped only when its independently held OS handle signals exit.",
            "An absent late receipt is recorded as unobserved; no native work is replayed.",
        ],
    }


def worker(root: Path) -> int:
    """Only the controller invokes this child against its new owned directory."""
    configuration = read_json(root / "ownership.json")
    require(configuration.get("kind") == "native_r1_lifecycle", "Owned directory marker missing")
    installation = Path(configuration["matlab_root"])
    store, inputs = root / "store", root / "fixtures"
    report = {"outcome": "running", "events": []}
    cores = []
    retained = RetainedNativeCall(store, installation)

    def save(phase: str) -> None:
        report["events"].append({"phase": phase, "observed_at": utc_now()})
        atomic_json(root / "worker-report.json", report)
        print(phase, flush=True)

    def submit(core, arguments):
        response = core.call("matlab_run", arguments)
        require(response["ok"], "A native acceptance submission was rejected")
        return response["job_id"]

    try:
        core = Core(store, [inputs], backend=OfficialBackend(store, timeout=NATIVE_TIMEOUT))
        cores.append(core)
        inspected = core.call("matlab_inspect", {"path": str(inputs / "synthetic.csv")})
        require(inspected["ok"], "Synthetic input inspection failed")
        arguments = {
            "operation": "data_profile",
            "parameters": {},
            "input_id": inspected["input"]["input_id"],
            "idempotency_key": "r1-normal",
        }
        normal_id = submit(core, arguments)
        report["normal_job_id"] = normal_id
        save("normal_dispatched")
        state = core.wait(normal_id, timeout=NATIVE_TIMEOUT + 30)
        require(state["state"] == "completed", "Ordinary native profile did not complete")
        profile = core.result(normal_id)
        require(profile["rows"] == 4, "Native profile row count differs from the synthetic fixture")
        require(state["verification"]["native_reopen"], "Normal MAT native reopening not verified")
        report["normal_case"] = {
            "operation": "data_profile",
            "state": state["state"],
            "rows": profile["rows"],
            "verification": state["verification"],
            "artifact_count": state["artifact_count"],
        }
        save("normal_completed")
        core.close()
        cores.remove(core)

        # A plotting/ODE recipe leaves a real native interval after session identity publication.
        # If it completes before fault injection, the harness fails instead of inventing unknown.
        fault = Core(store, [inputs], backend=retained)
        cores.append(fault)
        arguments = {
            "operation": "first_order_kinetics",
            "parameters": {
                "initial_concentration": 2,
                "rate_constant": 0.25,
                "time_end": 8,
                "points": 10000,
                "concentration_unit": "mmol/L",
                "time_unit": "s",
                "title": "Synthetic R1 coordinator interruption",
            },
            "idempotency_key": "r1-interrupted-once",
        }
        interrupted_id = submit(fault, arguments)
        report["interrupted_job_id"] = interrupted_id
        save("interruption_dispatched")
        state = fault.wait(interrupted_id, timeout=NATIVE_TIMEOUT + 30)
        require(retained.native is not None, "Injected timeout did not observe a native identity")
        require(state["state"] == "unknown", "Unknown interval was not observed after injection")
        require(
            (store / "executor-quarantine.json").is_file(), "Unknown executor was not quarantined"
        )
        job = store / "jobs" / interrupted_id
        original_dispatch = digest(job / "dispatch.json")
        original_request = digest(job / "request.json")
        report["interruption"] = {
            "injection": "coordinator_timeout_retaining_real_native_call",
            "initial_state": state["state"],
            "quarantined": True,
            "dispatch_preserved": False,
            "same_idempotency_preserved": False,
            "new_dispatch_blocked": False,
            "native_dispatch_calls": retained.calls,
            "late_receipt_observed": False,
            "reconciled_state": None,
        }
        save("unknown_preserved")
        repeated = fault.call("matlab_run", arguments)
        require(repeated["ok"] and repeated["job_id"] == interrupted_id, "Idempotent job changed")
        blocked = fault.call("matlab_run", arguments | {"idempotency_key": "r1-must-not-dispatch"})
        require(not blocked["ok"], "Unknown executor accepted another native job")
        require(
            blocked["error"]["code"] == "EXECUTOR_RECOVERY_REQUIRED", "Unexpected quarantine error"
        )
        observer = Core(store, [inputs], backend=retained)
        cores.append(observer)
        observed = observer.call("matlab_job", {"job_id": interrupted_id, "action": "status"})
        require(
            observed["ok"] and observed["job"]["state"] == "unknown",
            "Passive status changed unknown",
        )
        require(retained.calls == 1, "Passive coordinator replayed the native dispatch")
        report["interruption"].update(
            {"same_idempotency_preserved": True, "new_dispatch_blocked": True}
        )
        save("no_replay_observed")

        # Genuine native receipt only: no fabricated result, relocated receipt, or scientific replay.
        deadline = time.monotonic() + NATIVE_TIMEOUT + 15
        while time.monotonic() < deadline:
            if (job / "receipt.json").is_file() or retained.finished.is_set():
                break
            time.sleep(POLL_SECONDS)
        reconciled = observer.call("matlab_job", {"job_id": interrupted_id, "action": "reconcile"})
        require(reconciled["ok"], "Explicit reconciliation failed")
        late = (job / "receipt.json").is_file()
        if late:
            expected = read_json(job / "receipt.json")["state"]
            require(reconciled["job"]["state"] == expected, "Late receipt was not reconciled")
            require(
                expected in {"completed", "cancelled", "failed"}, "Invalid native receipt state"
            )
        else:
            require(
                reconciled["job"]["state"] == "unknown", "Missing receipt became a known result"
            )
        require(
            digest(job / "dispatch.json") == original_dispatch, "Dispatch identity was rewritten"
        )
        require(digest(job / "request.json") == original_request, "Original request was changed")
        require(retained.calls == 1, "Reconciliation replayed native work")
        report["interruption"].update(
            {
                "dispatch_preserved": True,
                "native_dispatch_calls": retained.calls,
                "late_receipt_observed": late,
                "reconciled_state": reconciled["job"]["state"],
                "late_receipt_state": read_json(job / "receipt.json")["state"] if late else None,
            }
        )
        save("late_receipt_reconciled" if late else "late_receipt_unobserved_unknown_retained")
        require(
            retained.finished.wait(NATIVE_TIMEOUT + 15), "Retained native RPC exceeded its bound"
        )
        report["retained_native_observation"] = retained.native.observation()
        report["retained_backend_error_type"] = retained.error_type
        report["outcome"] = "passed"
        save("worker_completed")
        return 0
    except BaseException as error:  # noqa: BLE001 -- Persist interruptions before owned cleanup.
        report["outcome"] = "failed"
        report["error_type"] = type(error).__name__
        (root / "worker-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        save("worker_failed")
        return 1
    finally:
        # A stuck Core.close remains bounded by the controller's exact child handle.
        for core in cores:
            core.close()
        if retained.native:
            retained.native.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run-native", action="store_true", help="Explicitly start this native acceptance"
    )
    parser.add_argument(
        "--matlab-root", type=Path, help="Existing licensed MATLAB R2025a+ installation"
    )
    parser.add_argument(
        "--backend-binary", type=Path, help="Existing pinned official backend; read-only source"
    )
    parser.add_argument(
        "--run-root", type=Path, help="New private directory, must not already exist"
    )
    parser.add_argument("--public-output", type=Path, help="Optional new sanitized receipt file")
    parser.add_argument("--worker-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_root:
        require(
            os.environ.get("MATLAB_COMPANION_R1_WORKER") == "1", "Worker requires its controller"
        )
        return worker(args.worker_root.resolve())
    if not args.run_native:
        parser.print_help()
        return 0
    require(os.name == "nt", "Native R1 lifecycle acceptance currently targets Windows")
    require(
        args.matlab_root is not None and args.backend_binary is not None,
        "Supply explicit installed MATLAB and pinned backend paths",
    )
    installation, binary = args.matlab_root.resolve(), args.backend_binary.resolve()
    require((installation / "bin" / "matlab.exe").is_file(), "MATLAB executable was not found")
    _, expected = ASSETS[(platform.system(), platform.machine())]
    require(
        binary.is_file() and digest(binary) == expected, "Pinned backend checksum did not match"
    )
    if args.public_output:
        require(
            not args.public_output.exists(), "Public output already exists; choose a new receipt"
        )
    if args.run_root:
        root = args.run_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
    else:
        root = Path(tempfile.mkdtemp(prefix="mc-r1-lifecycle-"))
    token = str(uuid.uuid4())
    atomic_json(
        root / "ownership.json",
        {
            "kind": "native_r1_lifecycle",
            "nonce": token,
            "matlab_root": str(installation),
            "controller_pid": os.getpid(),
            "observed_at": utc_now(),
        },
    )
    target = backend_path(root / "store")
    target.parent.mkdir(parents=True)
    shutil.copyfile(binary, target)
    require(digest(target) == expected, "Isolated backend copy differs from its pinned source")
    atomic_json(root / "store" / "settings.json", {"matlab_root": str(installation)})
    (root / "fixtures").mkdir()
    source = root / "fixtures" / "synthetic.csv"
    source.write_text("x,y\n0,1\n1,3\n2,5\n3,7\n", encoding="utf-8", newline="\n")
    source_hash = digest(source)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=False
    )
    report = {
        "scope": SCOPE,
        "observed_at": utc_now(),
        "outcome": "running",
        "source_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "source_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "runtime_version": importlib.metadata.version("matlab-companion"),
        "runtime_sources": {
            name: digest(Path(importlib.import_module("matlab_companion." + name).__file__))
            for name in ("backend", "core", "storage", "contracts")
        },
        "harness_sha256": digest(Path(__file__)),
        "run_root": str(root),
        "native_sources": {
            p.name: digest(p) for p in (native_code_root() / "+companion").glob("*.m")
        },
        "native_observations": [],
    }
    sentinel = Sentinel(root, installation, token)
    native_handles = {}
    child = None
    print("Private R1 acceptance directory:", root, flush=True)
    try:
        sentinel.start()
        environment = os.environ.copy()
        environment["MATLAB_COMPANION_R1_WORKER"] = "1"
        environment["MATLAB_COMPANION_MATLAB_ROOT"] = str(installation)
        with (root / "worker-stdout.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(Path(__file__).resolve()),
                    "--worker-root",
                    str(root),
                ],
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            deadline = time.monotonic() + WORKER_TIMEOUT
            last_phase = None
            while child.poll() is None:
                sentinel.check()
                current = optional_json(root / "worker-report.json") or {}
                phase = (current.get("events") or [{}])[-1].get("phase")
                if phase and phase != last_phase:
                    sentinel.check(phase)
                    print("R1 lifecycle:", phase, flush=True)
                    last_phase = phase
                for session_path in (root / "store" / "jobs").glob("*/native-session.json"):
                    if session_path.parent.name in native_handles:
                        continue
                    session = optional_json(session_path)
                    if session and isinstance(session.get("matlab_pid"), int):
                        try:
                            observed = ObservedProcess(session["matlab_pid"])
                        except OSError:
                            continue  # No captured identity means unknown, never stopped.
                        require(
                            observed.matches_matlab(installation),
                            "Companion native executable mismatch",
                        )
                        require(
                            observed.identity != sentinel.native.identity,
                            "Companion attached to sentinel",
                        )
                        native_handles[session_path.parent.name] = observed
                if time.monotonic() >= deadline:
                    report["worker_deadline_exceeded"] = True
                    raise TimeoutError("Owned Python acceptance worker exceeded its deadline")
                time.sleep(POLL_SECONDS)
        sentinel.check("worker_exit")
        report["worker"] = read_json(root / "worker-report.json")
        require(
            child.returncode == 0 and report["worker"]["outcome"] == "passed",
            "Lifecycle worker failed",
        )
        require(
            len(native_handles) == 2,
            "Both Companion native identities were not independently captured",
        )
        require(
            sentinel.latest["counter"] > sentinel.first_counter,
            "Sentinel heartbeat did not advance",
        )
        require(digest(source) == source_hash, "Synthetic source bytes changed")
        report["outcome"] = "passed"
    except BaseException as error:  # noqa: BLE001 -- Persist interruptions before owned cleanup.
        report["outcome"] = "failed"
        report["error_type"] = type(error).__name__
        (root / "controller-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if child is not None and child.poll() is None:
            # Exact owned Python child handle only. This makes no claim about native stop.
            child.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=10)
            report["owned_python_worker_terminated"] = True
        report["worker"] = optional_json(root / "worker-report.json") or report.get("worker", {})
        for job_id, native in native_handles.items():
            case = "normal" if job_id == report["worker"].get("normal_job_id") else "interrupted"
            report["native_observations"].append(
                {"case": case, "observation": native.observation()}
            )
            native.close()
        sentinel_preserved = None
        if sentinel.native is not None:
            try:
                sentinel.check("before_sentinel_shutdown")
                sentinel_preserved = True
            except (AssertionError, OSError):
                sentinel_preserved = False
                report["outcome"] = "failed"
                report.setdefault("error_type", "SentinelPreservationFailed")
        cleanup = sentinel.stop()
        report["sentinel"] = {
            "identity_observed": sentinel.native is not None,
            "state_preserved": sentinel_preserved,
            "heartbeat_advanced": bool(
                sentinel.latest and sentinel.latest["counter"] > sentinel.first_counter
            ),
            "samples": sentinel.samples,
            "events": sentinel.events,
            "matlab_release": sentinel.latest.get("matlab_release") if sentinel.latest else None,
            "matlab_version": sentinel.latest.get("matlab_version") if sentinel.latest else None,
            "cooperative_stop_acknowledged": cleanup["cooperative_stop_acknowledged"],
            "native_stop_observed": (cleanup.get("native_observation") or {}).get("native_stopped"),
            "cleanup": cleanup,
        }
        if (
            not cleanup["cooperative_stop_acknowledged"]
            or not report["sentinel"]["native_stop_observed"]
        ):
            report["outcome"] = "failed"
            report.setdefault("error_type", "SentinelShutdownUnconfirmed")
        atomic_json(root / "report.json", report)
        if args.public_output:
            atomic_json(args.public_output.resolve(), public_receipt(report))
        print("R1 lifecycle outcome:", report["outcome"], flush=True)
        print("Private receipt:", root / "report.json", flush=True)
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
