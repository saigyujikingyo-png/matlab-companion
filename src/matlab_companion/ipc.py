"""Bounded JSON transport for one user's local coordinator; no job ownership.

Windows uses public Win32 named-pipe APIs through ctypes, with an explicit user
DACL and remote-client rejection. POSIX uses owner-only pathname AF_UNIX sockets.
Closing a connection never cancels work, stops a process or removes a job.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import math
import os
import re
import socket
import stat
import struct
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

MAX_FRAME = 16 * 1024 * 1024
_PIPE_PREFIX = "\\\\.\\pipe\\matlab-companion-v1-"


class IPCError(ValueError):
    """Malformed, unsupported or over-limit local protocol data."""


@dataclass(frozen=True)
class Endpoint:
    kind: str
    address: str


def _deadline(timeout: float) -> float:
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("IPC timeout must be finite and positive")
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("Local IPC deadline expired")
    return left


def _limit(max_bytes: int) -> None:
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_FRAME:
        raise ValueError("Invalid local IPC frame limit")


@contextlib.contextmanager
def _locked(lock, deadline):
    if not lock.acquire(timeout=_remaining(deadline)):
        raise TimeoutError("Local IPC connection is busy")
    try:
        yield
    finally:
        lock.release()


def _validate_json(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise IPCError("JSON object keys must be strings")
            _validate_json(item)
    elif isinstance(value, list):
        for item in value:
            _validate_json(item)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise IPCError("Nonfinite numbers are not local IPC values")
    elif value is not None and not isinstance(value, (str, int, bool)):
        raise IPCError("Unsupported local IPC value")


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IPCError("Duplicate JSON object key")
        result[key] = value
    return result


class LocalConnection:
    """One request/response stream; send and receive are serialized per connection."""

    def __init__(self, channel, on_close=None):
        self._channel = channel
        self._on_close = on_close
        self._lock = threading.RLock()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._channel.close()
                finally:
                    if self._on_close is not None:
                        self._on_close(self)

    def peer_pid(self) -> int | None:
        return self._channel.peer()[0]

    def peer_uid(self) -> int | None:
        return self._channel.peer()[1]

    def _write_all(self, data: bytes, deadline: float) -> None:
        if self._closed:
            raise EOFError("Local IPC connection is closed")
        view = memoryview(data)
        while view:
            written = self._channel.write(view, deadline)
            if written <= 0:
                raise EOFError("Local IPC peer disconnected")
            view = view[written:]

    def _read_exact(self, count: int, deadline: float) -> bytes:
        if self._closed:
            raise EOFError("Local IPC connection is closed")
        data = bytearray()
        while len(data) < count:
            part = self._channel.read(count - len(data), deadline)
            if not part:
                raise EOFError("Local IPC peer disconnected during a frame")
            data.extend(part)
        return bytes(data)

    def send_json(self, value: dict, *, timeout: float, max_bytes: int = MAX_FRAME) -> None:
        _limit(max_bytes)
        deadline = _deadline(timeout)
        try:
            if not isinstance(value, dict):
                raise IPCError("Local IPC frame must contain an object")
            _validate_json(value)
            data = json.dumps(value, ensure_ascii=False, allow_nan=False,
                              separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError, UnicodeError, RecursionError) as error:
            raise IPCError("Invalid outgoing local IPC object") from error
        if len(data) > max_bytes:
            raise IPCError("Local IPC frame exceeds its byte limit")
        with _locked(self._lock, deadline):
            try:
                self._write_all(struct.pack("!I", len(data)) + data, deadline)
            except BaseException:
                self.close()
                raise

    def recv_json(self, *, timeout: float, max_bytes: int = MAX_FRAME) -> dict:
        _limit(max_bytes)
        deadline = _deadline(timeout)
        with _locked(self._lock, deadline):
            try:
                size = struct.unpack("!I", self._read_exact(4, deadline))[0]
                if not 0 < size <= max_bytes:
                    raise IPCError("Local IPC frame exceeds its byte limit")
                value = json.loads(self._read_exact(size, deadline).decode("utf-8"),
                                   object_pairs_hook=_object_pairs)
                if not isinstance(value, dict):
                    raise IPCError("Local IPC frame must contain an object")
                _validate_json(value)
                return value
            except (ValueError, TypeError, UnicodeError, RecursionError) as error:
                self.close()
                raise IPCError("Invalid incoming local IPC object") from error
            except BaseException:
                self.close()
                raise


class _SocketChannel:
    def __init__(self, sock):
        self.socket = sock

    def read(self, count, deadline):
        self.socket.settimeout(_remaining(deadline))
        return self.socket.recv(count)

    def write(self, data, deadline):
        self.socket.settimeout(_remaining(deadline))
        return self.socket.send(data)

    def peer(self):
        if hasattr(socket, "SO_PEERCRED"):
            pid, uid, _gid = struct.unpack(
                "iII", self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
            )
            return pid, uid
        return None, None

    def close(self):
        with contextlib.suppress(OSError):
            self.socket.shutdown(socket.SHUT_RDWR)
        self.socket.close()


def _private_directory(path: Path, *, create: bool) -> None:
    if create:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError("Local IPC directory must be owned by this user with mode 0700")
    if path.resolve() != path:
        raise PermissionError("Local IPC directory must not redirect through symlinks")


def _unix_path(root: Path, identity: str) -> Path:
    key = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    directory = Path(tempfile.gettempdir()).resolve() / f"mc-ipc-{os.geteuid()}-{key}"
    _private_directory(directory, create=True)
    path = directory / (identity + ".sock")
    if len(os.fsencode(path)) > 103:
        raise IPCError("Local IPC runtime path exceeds the platform socket limit")
    return path


def _unix_endpoint(address: str) -> Path:
    path = Path(address)
    expected_parent = Path(tempfile.gettempdir()).resolve()
    if (not path.is_absolute() or path.parent.parent != expected_parent or
            not re.fullmatch(rf"mc-ipc-{os.geteuid()}-[0-9a-f]{{16}}", path.parent.name) or
            not re.fullmatch(r"[0-9a-f]{32}\.sock", path.name)):
        raise IPCError("Unsupported local Unix endpoint")
    _private_directory(path.parent, create=False)
    info = path.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise PermissionError("Local IPC socket must be owned by this user with mode 0600")
    return path


class _Windows:
    """Typed public Win32 bindings, initialized only on Windows."""

    def __init__(self):
        from ctypes import wintypes as w

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]

        class SecurityAttributes(ctypes.Structure):
            _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", w.LPVOID),
                        ("bInheritHandle", w.BOOL)]

        self.Overlapped, self.SecurityAttributes = Overlapped, SecurityAttributes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.dword = w.DWORD
        pointer = ctypes.POINTER
        signatures = {
            "CreateNamedPipeW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                                  w.DWORD, pointer(SecurityAttributes)], w.HANDLE),
            "CreateFileW": ([w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            "ConnectNamedPipe": ([w.HANDLE, pointer(Overlapped)], w.BOOL),
            "ReadFile": ([w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), pointer(Overlapped)], w.BOOL),
            "WriteFile": ([w.HANDLE, w.LPVOID, w.DWORD, pointer(w.DWORD), pointer(Overlapped)], w.BOOL),
            "GetOverlappedResult": ([w.HANDLE, pointer(Overlapped), pointer(w.DWORD), w.BOOL], w.BOOL),
            "CancelIoEx": ([w.HANDLE, pointer(Overlapped)], w.BOOL),
            "CreateEventW": ([w.LPVOID, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "WaitNamedPipeW": ([w.LPCWSTR, w.DWORD], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetCurrentProcess": ([], w.HANDLE),
            "LocalFree": ([w.LPVOID], w.LPVOID),
            "GetNamedPipeServerProcessId": ([w.HANDLE, pointer(w.ULONG)], w.BOOL),
            "GetNamedPipeClientProcessId": ([w.HANDLE, pointer(w.ULONG)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        signatures = {
            "OpenProcessToken": ([w.HANDLE, w.DWORD, pointer(w.HANDLE)], w.BOOL),
            "GetTokenInformation": ([w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, pointer(w.DWORD)], w.BOOL),
            "ConvertSidToStringSidW": ([w.LPVOID, pointer(w.LPWSTR)], w.BOOL),
            "ConvertStringSecurityDescriptorToSecurityDescriptorW":
                ([w.LPCWSTR, w.DWORD, pointer(w.LPVOID), pointer(w.DWORD)], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.advapi, name)
            function.argtypes, function.restype = args, result
        token, needed = w.HANDLE(), w.DWORD()
        self.check(self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)))
        try:
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            self.check(self.advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)))
            sid_pointer = ctypes.cast(buffer, pointer(w.LPVOID))[0]
            sid_text = w.LPWSTR()
            self.check(self.advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)))
            try:
                self.sid = sid_text.value
            finally:
                self.kernel.LocalFree(sid_text)
        finally:
            self.kernel.CloseHandle(token)

    @staticmethod
    def check(result):
        if not result:
            code = ctypes.get_last_error()
            if code in (109, 232, 233, 995):
                raise EOFError("Local pipe peer disconnected")
            raise ctypes.WinError(code)
        return result

    def event(self):
        return self.check(self.kernel.CreateEventW(None, True, False, None))

    def wait(self, event, deadline):
        milliseconds = min(0xFFFFFFFE, math.ceil(_remaining(deadline) * 1000))
        result = self.kernel.WaitForSingleObject(event, milliseconds)
        if result == 258:
            raise TimeoutError("Local pipe deadline expired")
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())

    def cancel_and_drain(self, handle, overlapped):
        # CancelIoEx is asynchronous. Keep OVERLAPPED and buffers alive until
        # completion, even when completion wins the cancellation race.
        self.kernel.CancelIoEx(handle, ctypes.byref(overlapped))
        count = self.dword()
        self.kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(count), True)

    def new_pipe(self, address, first, max_clients):
        descriptor = ctypes.c_void_p()
        self.check(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"D:P(A;;GA;;;{self.sid})", 1, ctypes.byref(descriptor), None
        ))
        try:
            attributes = self.SecurityAttributes(ctypes.sizeof(self.SecurityAttributes), descriptor, False)
            # BYTE framing; reject remote clients. Only the first instance uses
            # FIRST_PIPE_INSTANCE, while a pending instance keeps the name owned.
            handle = self.kernel.CreateNamedPipeW(
                address, 0x3 | 0x40000000 | (0x80000 if first else 0), 0x8,
                max_clients + 1, 65536, 65536, 0, ctypes.byref(attributes)
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            return handle
        finally:
            self.kernel.LocalFree(descriptor)


@lru_cache(maxsize=1)
def _win():
    return _Windows()


class _PipePending:
    def __init__(self, address, first, max_clients):
        self.api = _win()
        self.handle = self.api.new_pipe(address, first, max_clients)
        self.overlapped = self.api.Overlapped()
        self.pending = False
        try:
            self.overlapped.hEvent = self.api.event()
            if not self.api.kernel.ConnectNamedPipe(self.handle, ctypes.byref(self.overlapped)):
                code = ctypes.get_last_error()
                if code == 997:
                    self.pending = True
                elif code != 535:  # Client connected between creation and this call.
                    raise ctypes.WinError(code)
        except BaseException:
            self.close()
            raise

    def ready(self, deadline):
        if self.pending:
            self.api.wait(self.overlapped.hEvent, deadline)
            count = self.api.dword()
            self.api.check(self.api.kernel.GetOverlappedResult(
                self.handle, ctypes.byref(self.overlapped), ctypes.byref(count), False
            ))
            self.pending = False

    def take(self):
        handle, self.handle = self.handle, None
        self.close()
        return _PipeChannel(handle, server=True)

    def close(self):
        if self.handle is not None:
            if self.pending:
                self.api.cancel_and_drain(self.handle, self.overlapped)
            self.api.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.overlapped.hEvent:
            self.api.kernel.CloseHandle(self.overlapped.hEvent)
            self.overlapped.hEvent = None


class _PipeChannel:
    def __init__(self, handle, *, server):
        self.handle, self.server, self.api = handle, server, _win()

    def _io(self, buffer, count, deadline, function):
        overlapped = self.api.Overlapped()
        overlapped.hEvent = self.api.event()
        transferred = self.api.dword()
        try:
            if not function(self.handle, buffer, count, ctypes.byref(transferred), ctypes.byref(overlapped)):
                if ctypes.get_last_error() != 997:
                    self.api.check(False)
                try:
                    self.api.wait(overlapped.hEvent, deadline)
                except BaseException:
                    self.api.cancel_and_drain(self.handle, overlapped)
                    raise
            self.api.check(self.api.kernel.GetOverlappedResult(
                self.handle, ctypes.byref(overlapped), ctypes.byref(transferred), False
            ))
            return transferred.value
        finally:
            self.api.kernel.CloseHandle(overlapped.hEvent)

    def read(self, count, deadline):
        _remaining(deadline)
        buffer = ctypes.create_string_buffer(count)
        size = self._io(buffer, count, deadline, self.api.kernel.ReadFile)
        return buffer.raw[:size]

    def write(self, data, deadline):
        _remaining(deadline)
        buffer = ctypes.create_string_buffer(bytes(data))
        return self._io(buffer, len(data), deadline, self.api.kernel.WriteFile)

    def peer(self):
        pid = self.api.dword()
        function = (self.api.kernel.GetNamedPipeClientProcessId if self.server
                    else self.api.kernel.GetNamedPipeServerProcessId)
        self.api.check(function(self.handle, ctypes.byref(pid)))
        return pid.value, None

    def close(self):
        if self.handle is not None:
            self.api.kernel.CloseHandle(self.handle)
            self.handle = None


class LocalListener:
    """One listening endpoint; closing it leaves accepted connections alone."""

    def __init__(self, root: Path, instance_id: str, max_clients: int = 8):
        if type(max_clients) is not int or not 1 <= max_clients <= 64:
            raise ValueError("Local IPC client limit must be between 1 and 64")
        identity = uuid.UUID(str(instance_id)).hex
        root = Path(root).expanduser().resolve()
        self._max_clients = max_clients
        self._connections = set()
        self._condition = threading.Condition()
        self._accept_lock = threading.Lock()
        self._closed = False
        self._socket_identity = None
        self._directory_identity = None
        self._socket = None
        self._pending = None
        if os.name == "nt":
            user_key = hashlib.sha256(_win().sid.encode()).hexdigest()[:16]
            root_key = hashlib.sha256(os.fsencode(os.path.normcase(root))).hexdigest()[:16]
            self.endpoint = Endpoint("pipe", f"{_PIPE_PREFIX}{user_key}-{root_key}-{identity}")
            self._pending = _PipePending(self.endpoint.address, True, max_clients)
        else:
            path = _unix_path(root, identity)
            parent_info = path.parent.lstat()
            self._directory_identity = (parent_info.st_dev, parent_info.st_ino)
            self.endpoint = Endpoint("unix", str(path))
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                self._socket.bind(str(path))
                info = path.lstat()
                self._socket_identity = (info.st_dev, info.st_ino)
                path.chmod(0o600)
                self._socket.listen(max_clients)
            except BaseException:
                self.close()
                raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _released(self, connection):
        with self._condition:
            self._connections.discard(connection)
            self._condition.notify_all()

    def accept(self, *, timeout: float) -> LocalConnection:
        deadline = _deadline(timeout)
        if not self._accept_lock.acquire(timeout=_remaining(deadline)):
            raise TimeoutError("Local IPC accept is already busy")
        try:
            with self._condition:
                while len(self._connections) >= self._max_clients and not self._closed:
                    self._condition.wait(_remaining(deadline))
                if self._closed:
                    raise EOFError("Local IPC listener is closed")
            if self._pending is not None:
                _remaining(deadline)
                self._pending.ready(deadline)
                next_pending = _PipePending(self.endpoint.address, False, self._max_clients)
                channel = self._pending.take()
                self._pending = next_pending
            else:
                self._socket.settimeout(_remaining(deadline))
                sock, _address = self._socket.accept()
                channel = _SocketChannel(sock)
                if channel.peer()[1] not in (None, os.geteuid()):
                    channel.close()
                    raise PermissionError("Local IPC peer belongs to a different user")
            connection = LocalConnection(channel, self._released)
            with self._condition:
                self._connections.add(connection)
            return connection
        finally:
            self._accept_lock.release()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        with self._accept_lock:
            if self._pending is not None:
                self._pending.close()
                self._pending = None
            if self._socket is not None:
                self._socket.close()
                self._socket = None
            if self._socket_identity is not None:
                path = Path(self.endpoint.address)
                with contextlib.suppress(FileNotFoundError):
                    parent = path.parent.lstat()
                    info = path.lstat()
                    if (stat.S_ISDIR(parent.st_mode) and
                            (parent.st_dev, parent.st_ino) == self._directory_identity and
                            path.parent.resolve() == path.parent and stat.S_ISSOCK(info.st_mode) and
                            (info.st_dev, info.st_ino) == self._socket_identity):
                        path.unlink()
                self._socket_identity = None


def connect(endpoint: Endpoint, *, timeout: float = 3.0) -> LocalConnection:
    deadline = _deadline(timeout)
    if not isinstance(endpoint, Endpoint) or not isinstance(endpoint.address, str):
        raise IPCError("Unsupported local IPC endpoint")
    if os.name == "nt" and endpoint.kind == "pipe":
        api = _win()
        user_key = hashlib.sha256(api.sid.encode()).hexdigest()[:16]
        pattern = re.escape(_PIPE_PREFIX + user_key + "-") + r"[0-9a-f]{16}-[0-9a-f]{32}"
        if not re.fullmatch(pattern, endpoint.address):
            raise IPCError("Only this user's local named-pipe endpoints are supported")
        while True:
            # Identification-only SQOS: the pipe server cannot impersonate this
            # client to perform unrelated authenticated actions.
            handle = api.kernel.CreateFileW(endpoint.address, 0xC0000000, 0, None, 3,
                                             0x40000000 | 0x100000 | 0x10000, None)
            if handle != ctypes.c_void_p(-1).value:
                return LocalConnection(_PipeChannel(handle, server=False))
            code = ctypes.get_last_error()
            if code != 231:
                raise ctypes.WinError(code)
            milliseconds = min(0xFFFFFFFE, math.ceil(_remaining(deadline) * 1000))
            if not api.kernel.WaitNamedPipeW(endpoint.address, milliseconds):
                code = ctypes.get_last_error()
                if code == 121:
                    raise TimeoutError("Local pipe connection deadline expired")
                raise ctypes.WinError(code)
            # Another client can claim the available instance before CreateFile.
            # Keep that bounded race from becoming a spin loop under contention.
            time.sleep(min(0.01, _remaining(deadline)))
    if os.name != "nt" and endpoint.kind == "unix":
        path = _unix_endpoint(endpoint.address)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(_remaining(deadline))
            sock.connect(str(path))
            channel = _SocketChannel(sock)
            if channel.peer()[1] not in (None, os.geteuid()):
                raise PermissionError("Local IPC server belongs to a different user")
            return LocalConnection(channel)
        except BaseException:
            sock.close()
            raise
    raise IPCError("Unsupported local IPC endpoint kind")
