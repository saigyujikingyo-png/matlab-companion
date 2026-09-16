"""Concurrent receipt writers must not share a temporary filename."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from matlab_companion import storage


@pytest.mark.skipif(storage.os.name != "nt", reason="Windows CRT read sharing errors")
def test_crt_read_denial_without_winerror_is_retried_for_a_short_race(tmp_path, monkeypatch):
    from pathlib import Path

    target = tmp_path / "state.json"
    storage.atomic_json(target, {"state": "running"})
    original_open = Path.open
    denied_reads = []

    def temporarily_denied(path, *args, **kwargs):
        if path == target and len(denied_reads) < 2:
            denied_reads.append(path)
            # Python's CRT-backed file open can report errno only, unlike
            # os.replace's WinError. Both occur during Windows replace races.
            raise PermissionError(13, "Permission denied", str(path))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", temporarily_denied)
    assert storage.read_json(target) == {"state": "running"}
    assert len(denied_reads) == 2


@pytest.mark.skipif(storage.os.name != "nt", reason="Windows bounded sharing retries")
def test_persistent_access_denial_preserves_original_and_ends_retry(tmp_path, monkeypatch):
    target = tmp_path / "state.json"
    storage.atomic_json(target, {"state": "queued"})
    original = target.read_bytes()
    attempts = []

    def denied(source, destination):
        attempts.append(destination)
        error = PermissionError("Persistent read-only target")
        error.winerror = 5
        raise error

    monkeypatch.setattr(storage.os, "replace", denied)
    started = time.monotonic()
    with pytest.raises(PermissionError, match="Persistent read-only target"):
        storage.atomic_json(target, {"state": "running"})
    assert 0.2 <= time.monotonic() - started < 2
    assert len(attempts) > 1
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_replacement_waits_for_a_short_lived_reader_without_corruption(
    tmp_path, monkeypatch
):
    target = tmp_path / "state.json"
    storage.atomic_json(target, {"state": "queued"})
    opened, attempted = threading.Event(), threading.Event()
    real_load = storage.json.load
    real_replace = storage.os.replace

    def held_reader(stream):
        opened.set()
        assert attempted.wait(3), "Replacement did not reach the open reader"
        return real_load(stream)

    def replacing(source, destination):
        try:
            return real_replace(source, destination)
        finally:
            attempted.set()

    monkeypatch.setattr(storage.json, "load", held_reader)
    monkeypatch.setattr(storage.os, "replace", replacing)
    with ThreadPoolExecutor(max_workers=1) as readers:
        reader = readers.submit(storage.read_json, target)
        assert opened.wait(3)
        try:
            storage.atomic_json(target, {"state": "running"})
        finally:
            attempted.set()
        assert reader.result(timeout=3) == {"state": "queued"}
    assert storage.read_json(target) == {"state": "running"}


def test_simultaneous_same_process_writers_publish_complete_independent_documents(
    tmp_path, monkeypatch
):
    target = tmp_path / "receipt.json"
    first_ready, second_done = threading.Event(), threading.Event()
    first_thread = None
    real_replace = storage.os.replace

    def controlled_replace(source, destination):
        if threading.get_ident() == first_thread:
            first_ready.set()
            assert second_done.wait(5)
        return real_replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", controlled_replace)

    def first_write():
        nonlocal first_thread
        first_thread = threading.get_ident()
        storage.atomic_json(target, {"writer": "first", "values": list(range(100))})

    def second_write():
        assert first_ready.wait(5)
        try:
            storage.atomic_json(target, {"writer": "second", "values": list(range(200))})
        finally:
            second_done.set()

    with ThreadPoolExecutor(max_workers=2) as writers:
        first = writers.submit(first_write)
        second = writers.submit(second_write)
        first.result(timeout=10)
        second.result(timeout=10)
    assert storage.read_json(target) == {"writer": "first", "values": list(range(100))}
    assert list(tmp_path.iterdir()) == [target]
