"""Owned job storage, atomic writes and cross-process execution locking."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def default_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "Chembridge" / "MATLABCompanion"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _sharing_retry(action):
    """Only retry Windows sharing/access races; never retries a scientific operation."""
    deadline = time.monotonic() + 0.25
    while True:
        try:
            return action()
        except OSError as error:
            windows_sharing = getattr(error, "winerror", None) in {5, 32, 33}
            crt_access = getattr(error, "winerror", None) is None and error.errno in {
                errno.EACCES,
                errno.EPERM,
            }
            if (
                os.name != "nt"
                or not (windows_sharing or crt_access)
                or time.monotonic() >= deadline
            ):
                raise
            time.sleep(0.01)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _sharing_retry(lambda: os.replace(temporary, path))
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


def read_json(path: Path) -> dict:
    def read():
        with path.open(encoding="utf-8-sig") as stream:
            return json.load(stream)

    return _sharing_retry(read)


def contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError("Path escapes the authorised directory")
    return resolved


def process_alive(pid: int) -> bool:
    """Query process existence without Windows os.kill semantics."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied is not proof of exit.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def process_start_identity(pid: int) -> str | None:
    """Read an OS process incarnation, without signalling or claiming native exit.

    None means unobserved, including access restrictions and unsupported platforms.
    Callers must retain ownership conservatively when identity cannot be checked.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(
                handle,
                *(ctypes.byref(item) for item in (creation, exit_time, kernel_time, user_time)),
            ):
                return None
            ticks = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            return f"windows-filetime:{ticks}"
        finally:
            kernel.CloseHandle(handle)
    try:
        # /proc stat's command may contain spaces and parentheses; fields after
        # its last ')' start at field 3. Start time is field 22 (index 19 below).
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"linux-proc:{boot}:{int(fields[19])}"
    except (OSError, ValueError, IndexError):
        return None


@contextlib.contextmanager
def file_lock(path: Path, timeout: float = 0):
    """OS-released lock, including after a crashed coordinator process."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    # Windows byte-range locks may extend beyond EOF. Reading a locked byte here
    # would fail before reaching the bounded contention loop below.
    deadline = time.monotonic() + timeout
    while True:
        try:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except (OSError, BlockingIOError):
            if time.monotonic() >= deadline:
                stream.close()
                raise TimeoutError("The executor is busy") from None
            time.sleep(0.1)
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()
