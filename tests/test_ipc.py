"""Real local IPC boundaries; these tests never start the MATLAB backend."""

import ctypes
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest

from matlab_companion import ipc
from matlab_companion.ipc import Endpoint, IPCError, LocalListener, connect


@pytest.fixture
def listener(tmp_path):
    with LocalListener(tmp_path, str(uuid.uuid4())) as server:
        yield server


def pair(listener):
    client = connect(listener.endpoint, timeout=2)
    server = listener.accept(timeout=2)
    return client, server


def test_actual_round_trip_and_peer_identity(listener):
    client, server = pair(listener)
    with client, server:
        client.send_json({"request": "measure", "value": [1, None, "μ"]}, timeout=2)
        assert server.recv_json(timeout=2) == {"request": "measure", "value": [1, None, "μ"]}
        server.send_json({"ok": True}, timeout=2)
        assert client.recv_json(timeout=2) == {"ok": True}
        if os.name == "nt" or hasattr(socket, "SO_PEERCRED"):
            assert client.peer_pid() == os.getpid()
            assert server.peer_pid() == os.getpid()
        if hasattr(socket, "SO_PEERCRED"):
            assert client.peer_uid() == os.geteuid()
            assert server.peer_uid() == os.geteuid()
    assert set(asdict(listener.endpoint)) == {"kind", "address"}


def test_accept_timeout_does_not_destroy_listener(listener):
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        listener.accept(timeout=0.03)
    assert time.monotonic() - started < 1
    client, server = pair(listener)
    client.close()
    server.close()


def test_receive_timeout_closes_partial_stream(listener):
    client, server = pair(listener)
    with client, server:
        with pytest.raises(TimeoutError):
            client.recv_json(timeout=0.03)
        with pytest.raises(EOFError):
            server.recv_json(timeout=1)


@pytest.mark.parametrize("value", [[], {"value": float("nan")}, {"value": float("inf")}])
def test_invalid_outgoing_json_is_rejected_before_write(listener, value):
    client, server = pair(listener)
    with client, server:
        with pytest.raises(IPCError):
            client.send_json(value, timeout=1)
        client.send_json({"still": "usable"}, timeout=1)
        assert server.recv_json(timeout=1) == {"still": "usable"}


def test_outgoing_size_limit_preserves_connection(listener):
    client, server = pair(listener)
    with client, server:
        with pytest.raises(IPCError):
            client.send_json({"large": "x" * 100}, timeout=1, max_bytes=32)
        client.send_json({"ok": True}, timeout=1, max_bytes=32)
        assert server.recv_json(timeout=1, max_bytes=32) == {"ok": True}


@pytest.mark.parametrize("body", [b"[]", b'{"n":NaN}', b'{"n":1e999}', b"not-json",
                                  b'{"n":1,"n":2}', b'{"n":"\xff"}'])
def test_invalid_received_json_closes_only_connection(listener, body):
    client, server = pair(listener)
    with client, server:
        client._write_all(struct.pack("!I", len(body)) + body, time.monotonic() + 1)
        with pytest.raises(IPCError):
            server.recv_json(timeout=1)
    next_client, next_server = pair(listener)
    next_client.close()
    next_server.close()


def test_oversize_header_rejected_before_reading_body(listener):
    client, server = pair(listener)
    with client, server:
        client._write_all(struct.pack("!I", 33), time.monotonic() + 1)
        with pytest.raises(IPCError):
            server.recv_json(timeout=1, max_bytes=32)


def test_client_close_does_not_cancel_server_work(listener):
    client, server = pair(listener)
    received, completed = threading.Event(), threading.Event()

    def handle():
        with server:
            assert server.recv_json(timeout=1) == {"accepted": True}
            received.set()
            assert completed.wait(2)
            with pytest.raises((EOFError, OSError)):
                server.send_json({"completed": True}, timeout=1)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(handle)
        client.send_json({"accepted": True}, timeout=1)
        assert received.wait(2)
        client.close()
        completed.set()
        future.result(timeout=3)


def test_root_isolation(tmp_path):
    identity = str(uuid.uuid4())
    with (LocalListener(tmp_path / "one", identity) as first,
          LocalListener(tmp_path / "two", identity) as second):
        assert first.endpoint != second.endpoint


def test_cross_process_identity_and_round_trip(listener):
    code = """
import json, os, sys
from matlab_companion.ipc import Endpoint, connect
with connect(Endpoint(**json.loads(sys.argv[1])), timeout=3) as channel:
    channel.send_json({'pid': os.getpid(), 'server_pid': channel.peer_pid()}, timeout=3)
    print(json.dumps(channel.recv_json(timeout=3)))
"""
    process = subprocess.Popen(
        [sys.executable, "-I", "-B", "-c", code, json.dumps(asdict(listener.endpoint))],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        with listener.accept(timeout=5) as channel:
            value = channel.recv_json(timeout=3)
            # A Windows venv python.exe can launch a separate real interpreter.
            assert value["pid"] > 0 and value["pid"] != os.getpid()
            if os.name == "nt" or hasattr(socket, "SO_PEERCRED"):
                assert value["server_pid"] == os.getpid()
                assert channel.peer_pid() == value["pid"]
            channel.send_json({"readback": "passed"}, timeout=3)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert json.loads(stdout) == {"readback": "passed"}
    finally:
        if process.poll() is None:
            process.kill()  # Only this test's Python process, never a native/backend process.
            process.communicate(timeout=5)


def test_partial_frame_deadline(listener):
    client, server = pair(listener)
    with client, server:
        client._write_all(b"\x00\x00", time.monotonic() + 1)
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            server.recv_json(timeout=0.03)
        assert time.monotonic() - started < 1


def test_write_backpressure_deadline(listener):
    client, server = pair(listener)
    with client, server:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            client.send_json({"body": "x" * (4 * 1024 * 1024)}, timeout=0.05)
        assert time.monotonic() - started < 2


def test_capacity_is_bounded_and_released(tmp_path):
    with LocalListener(tmp_path, str(uuid.uuid4()), max_clients=1) as server:
        first, accepted_first = pair(server)
        with first, accepted_first, connect(server.endpoint, timeout=1) as second:
            with pytest.raises(TimeoutError):
                server.accept(timeout=0.03)
            accepted_first.close()
            with server.accept(timeout=1) as accepted_second:
                second.send_json({"accepted": 2}, timeout=1)
                assert accepted_second.recv_json(timeout=1) == {"accepted": 2}


def test_listener_close_does_not_close_accepted_connection(listener):
    client, server = pair(listener)
    listener.close()
    with client, server:
        client.send_json({"still": "running"}, timeout=1)
        assert server.recv_json(timeout=1) == {"still": "running"}


def test_reject_network_endpoint():
    with pytest.raises(IPCError):
        connect(Endpoint("tcp", "localhost:8899"), timeout=0.1)


@pytest.mark.skipif(os.name != "nt", reason="Windows named-pipe ACL and flags")
def test_windows_pipe_explicit_acl_and_creation_flags(tmp_path, monkeypatch):
    from ctypes import wintypes as w

    api = ipc._win()
    original = api.kernel.CreateNamedPipeW
    calls = []

    def recording_create(*args):
        attributes = args[7]._obj
        calls.append((args[1], args[2], bool(attributes.lpSecurityDescriptor), attributes.bInheritHandle))
        return original(*args)

    monkeypatch.setattr(api.kernel, "CreateNamedPipeW", recording_create)
    identity = str(uuid.uuid4())
    with LocalListener(tmp_path, identity) as server:
        security = ctypes.WinDLL("advapi32", use_last_error=True)
        pointer = ctypes.POINTER
        security.GetSecurityInfo.argtypes = [w.HANDLE, ctypes.c_int, w.DWORD] + [pointer(w.LPVOID)] * 5
        security.GetSecurityInfo.restype = w.DWORD
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            w.LPVOID, w.DWORD, w.DWORD, pointer(w.LPWSTR), pointer(w.DWORD)]
        security.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = w.BOOL
        descriptor, text = w.LPVOID(), w.LPWSTR()
        assert security.GetSecurityInfo(server._pending.handle, 6, 4, None, None, None, None,
                                        ctypes.byref(descriptor)) == 0
        try:
            assert security.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor, 1, 4, ctypes.byref(text), None)
            assert text.value == f"D:P(A;;FA;;;{api.sid})"
        finally:
            if text:
                api.kernel.LocalFree(text)
            api.kernel.LocalFree(descriptor)
        with pytest.raises(OSError):
            LocalListener(tmp_path, identity)
        # Record only successful listener operations for the first-instance assertion.
        calls.pop()
        client, accepted = pair(server)
        client.close()
        accepted.close()
    assert len(calls) == 2
    assert calls[0][0] & 0x80000  # FILE_FLAG_FIRST_PIPE_INSTANCE
    assert not calls[1][0] & 0x80000
    assert all(mode & 0x8 and explicit and not inherit for _, mode, explicit, inherit in calls)


@pytest.mark.skipif(os.name != "nt", reason="Windows local named-pipe address")
def test_windows_remote_pipe_address_is_rejected(listener):
    endpoint = Endpoint("pipe", listener.endpoint.address.replace("\\\\.\\", "\\\\localhost\\", 1))
    with pytest.raises(IPCError):
        connect(endpoint, timeout=0.1)


@pytest.mark.skipif(os.name == "nt", reason="POSIX pathname socket permissions")
def test_unix_permissions_and_only_owned_socket_cleanup(listener):
    path = Path(listener.endpoint.address)
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_uid == os.geteuid()
    retained = path.parent / "retain.txt"
    retained.write_text("keep", encoding="utf-8")
    listener.close()
    assert not path.exists()
    assert path.parent.is_dir()
    assert retained.read_text() == "keep"
    retained.unlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX pathname replacement")
def test_unix_close_preserves_replaced_path(listener):
    path = Path(listener.endpoint.address)
    path.unlink()
    path.write_text("replacement", encoding="utf-8")
    listener.close()
    assert path.read_text() == "replacement"
    path.unlink()


@pytest.mark.skipif(os.name == "nt", reason="POSIX owner-only directory")
@pytest.mark.parametrize("unsafe", ["permissions", "symlink"])
def test_unix_refuses_unsafe_runtime_directory(tmp_path, monkeypatch, unsafe):
    monkeypatch.setattr(ipc.tempfile, "gettempdir", lambda: str(tmp_path))
    root = tmp_path / "root"
    key = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    directory = tmp_path / f"mc-ipc-{os.geteuid()}-{key}"
    if unsafe == "permissions":
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
    else:
        outside = tmp_path / "outside"
        outside.mkdir(mode=0o700)
        directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError):
        LocalListener(root, str(uuid.uuid4()))
