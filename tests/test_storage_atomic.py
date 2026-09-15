"""Concurrent receipt writers must not share a temporary filename."""

import threading
from concurrent.futures import ThreadPoolExecutor

from matlab_companion import storage


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
