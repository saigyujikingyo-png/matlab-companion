"""Observe owned MATLAB process identity and exit without terminating processes.

A backend response and a completed scientific receipt are not process-exit
evidence. Windows observers retain a query/synchronize handle after validating
the launcher nonce, executable and creation-time window. Unsupported or denied
observation is explicitly unconfirmed. No PID-only polling or kill is used.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import os
import time
import uuid
from pathlib import Path

from .storage import atomic_json, utc_now

MAX_EXIT_WAIT = 20.0
POLL_INTERVAL = 0.05
MAX_IDENTITY_BYTES = 4096
FILETIME_UNIX_EPOCH = 116444736000000000


class NativeSessionUnconfirmed(RuntimeError):
    """The owned MATLAB process has no verified exit observation."""


class IdentityRejected(ValueError):
    """The session marker cannot authorize observation of this process."""


class WindowsProcess:
    """A read-only process handle remains bound to its process after PID reuse."""

    def __init__(self, pid: int):
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.kernel = kernel
        # SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION. No termination access.
        self.handle = kernel.OpenProcess(0x00101000, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "Native process handle unavailable")
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(
                self.handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                raise OSError(ctypes.get_last_error(), "Native process creation time unavailable")
            size = wintypes.DWORD(32768)
            executable = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(
                self.handle, 0, executable, ctypes.byref(size)
            ):
                raise OSError(ctypes.get_last_error(), "Native process executable unavailable")
            ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
            self.identity = {
                "pid": pid,
                "process_start": f"windows-filetime:{ticks}",
                "created_at_ns": (ticks - FILETIME_UNIX_EPOCH) * 100,
                "executable": str(Path(executable.value).resolve()),
            }
        except BaseException:
            self.close()
            raise

    def exited(self) -> bool:
        state = self.kernel.WaitForSingleObject(self.handle, 0)
        if state not in (0, 258):
            raise OSError(ctypes.get_last_error(), "Native process exit observation unavailable")
        return state == 0

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def observation_supported() -> bool:
    # POSIX needs an independently validated pidfd/process-birth implementation.
    # Until then a native call cannot promise the exit gate on those platforms.
    return os.name == "nt"


class NativeSessionWatcher:
    def __init__(self, job: Path, session_id: str):
        self.job = job
        self.session_id = str(uuid.UUID(session_id))
        self.job_id = str(uuid.UUID(job.name))
        self.task = None
        # The lower bound precedes server initialization: upstream startup timing
        # may change independently of our fixed scientific launcher.
        self.started_ns = time.time_ns()
        self.expected_executable = None
        self.record = {
            "contract_version": "1.0",
            "job_id": self.job_id,
            "session_id": self.session_id,
            "backend_returned": False,
            "backend_returned_meaning": "Official adapter body and stdio context completed normally",
            "backend_finished_at": None,
            "backend_error_type": None,
            "rpc_response_observed": False,
            "rpc_response_observed_at": None,
            "launch_window_started_at": utc_now(),
            "native_call_started_at": None,
            "native_exited": None,
            "native_identity": None,
            "native_observed_at": None,
            "reason_code": "NATIVE_CALL_NOT_STARTED",
        }

    def _write(self, **changes) -> None:
        self.record.update(changes)
        atomic_json(self.job / "native-lifecycle.json", self.record)

    def begin(self) -> None:
        self._write()

    def start(self, installation: Path) -> None:
        if not observation_supported():
            self._write(reason_code="NATIVE_OBSERVATION_UNSUPPORTED")
            raise NativeSessionUnconfirmed("Native process exit observation is unsupported")
        if self.task is not None:
            raise RuntimeError("A native session watcher can only start once")
        self.expected_executable = (installation / "bin" / "win64" / "MATLAB.exe").resolve()
        self._write(native_call_started_at=utc_now(), reason_code="AWAITING_NATIVE_IDENTITY")
        # The task is installed before the first native RPC is issued.
        self.task = asyncio.create_task(self._observe(), name=f"native-observer-{self.session_id}")

    def rpc_response_observed(self) -> None:
        self._write(rpc_response_observed=True, rpc_response_observed_at=utc_now())

    def _read_identity(self) -> tuple[dict, int] | None:
        try:
            with (self.job / "native-session.json").open("rb") as stream:
                raw = stream.read(MAX_IDENTITY_BYTES + 1)
                marker_written_ns = os.fstat(stream.fileno()).st_mtime_ns
        except FileNotFoundError:
            return None
        if len(raw) > MAX_IDENTITY_BYTES:
            raise IdentityRejected("Native identity marker exceeds its size bound")
        try:
            marker = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # A transient writer/replace window is not native exit evidence.
            return None
        if (
            not isinstance(marker, dict)
            or marker.get("contract_version") != "1.0"
            or marker.get("job_id") != self.job_id
            or marker.get("session_id") != self.session_id
            or type(marker.get("matlab_pid")) is not int
            or not 0 < marker["matlab_pid"] <= 0xFFFFFFFF
        ):
            raise IdentityRejected("Native identity marker did not match the owned launcher")
        return marker, marker_written_ns

    def _validate_process(self, process: WindowsProcess, marker_written_ns: int) -> None:
        identity = process.identity
        expected = os.path.normcase(str(self.expected_executable))
        observed = os.path.normcase(str(Path(identity["executable"]).resolve()))
        if observed != expected:
            raise IdentityRejected("Native executable does not match the selected installation")
        # A reused PID born after the marker, or a pre-existing user session,
        # cannot inherit this launcher's ownership. Allow only FILETIME rounding.
        if not self.started_ns - 100 <= identity["created_at_ns"] <= marker_written_ns + 100:
            raise IdentityRejected("Native process creation time is outside the launch window")

    async def _observe(self) -> None:
        process = None
        try:
            while process is None:
                marker = self._read_identity()
                if marker is None:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                identity, marker_written_ns = marker
                process = WindowsProcess(identity["matlab_pid"])
                self._validate_process(process, marker_written_ns)
                self._write(
                    native_identity=process.identity,
                    native_exited=False,
                    native_observed_at=utc_now(),
                    reason_code="NATIVE_PROCESS_ALIVE",
                )
            while not process.exited():
                await asyncio.sleep(POLL_INTERVAL)
            self._write(native_exited=True, native_observed_at=utc_now(), reason_code=None)
        except IdentityRejected:
            self._write(reason_code="NATIVE_IDENTITY_REJECTED")
        except OSError:
            self._write(reason_code="NATIVE_OBSERVATION_UNAVAILABLE")
        finally:
            if process is not None:
                process.close()

    async def finish(
        self,
        *,
        backend_returned: bool,
        backend_error_type: str | None = None,
        timeout: float = MAX_EXIT_WAIT,
    ) -> dict:
        self._write(
            backend_returned=backend_returned,
            backend_finished_at=utc_now(),
            backend_error_type=backend_error_type,
        )
        if self.task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.task), timeout=max(0, min(timeout, MAX_EXIT_WAIT))
                )
            except TimeoutError:
                self.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.task
                self._write(
                    reason_code="NATIVE_EXIT_UNCONFIRMED"
                    if self.record["native_identity"]
                    else "NATIVE_IDENTITY_UNOBSERVED"
                )
        return dict(self.record)
