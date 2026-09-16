"""Real coordinator/client processes with portable receipts, never licensed MATLAB.

The controlled worker uses test_recovery's explicitly fake artifact bytes. These
checks establish local ownership and transport behavior, not native acceptance.
SDK disconnect checks use a prestarted owner; automatic startup is tested from
ordinary Python clients. No check promises survival after host/outer Job closure.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import site
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from matlab_companion import __version__
from matlab_companion.client import CoordinatorClient
from matlab_companion.coordinator import PROTOCOL_VERSION, resolved_configuration
from matlab_companion.ipc import LocalListener
from matlab_companion.storage import atomic_json, process_alive, process_start_identity, read_json

REPOSITORY = Path(__file__).resolve().parents[1]
IDLE_SECONDS = 0.5
PRESTART_IDLE_SECONDS = 3.0


def python_command(code, *arguments):
    # The Windows venv executable is a redirector. Launch the real interpreter so
    # SDK process teardown targets the actual frontend, then expose locked deps.
    paths = [str(REPOSITORY / "src"), str(REPOSITORY / "tests")]
    bootstrap = (
        "import sys, site; [site.addsitedir(p) for p in "
        + repr(site.getsitepackages())
        + "]; sys.path[:0] = "
        + repr(paths)
        + "; "
    )
    return [sys._base_executable, "-I", "-B", "-c", bootstrap + code, *map(str, arguments)]


def process_options(*, independent=False):
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW
        if independent:
            flags |= subprocess.CREATE_BREAKAWAY_FROM_JOB
        return {"creationflags": flags}
    return {"start_new_session": independent}


def eventually(predicate, *, timeout=10, description="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.025)
    raise AssertionError(f"Timed out observing {description}")


async def eventually_async(predicate, *, timeout=10, description="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        await asyncio.sleep(0.025)
    raise AssertionError(f"Timed out observing {description}")


def source_file(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "profile.csv"
    source.write_text("concentration,absorbance\n1,3\n2,5\n", encoding="utf-8")
    return source


def _controlled_owner(root, inputs, control):
    """Private child helper; production launchers cannot select a fake backend."""
    from test_recovery import ReceiptBackend

    from matlab_companion.coordinator import Coordinator

    class ControlledBackend(ReceiptBackend):
        async def execute(self, job):
            with (control / "dispatches.txt").open("a", encoding="utf-8") as stream:
                stream.write(job.name + "\n")
            atomic_json(control / "entered.json", {"job_id": job.name, "pid": os.getpid()})
            deadline = time.monotonic() + 30
            while not (control / "release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Portable worker release was not observed")
                await asyncio.sleep(0.025)
            await super().execute(job)

    Coordinator(
        root,
        allowed_roots=[inputs],
        idle_seconds=PRESTART_IDLE_SECONDS,
        backend=ControlledBackend(),
    ).run()


@contextmanager
def controlled_owner(tmp_path, source):
    root, control = tmp_path / "store", tmp_path / "control"
    control.mkdir()
    code = (
        "from pathlib import Path; from test_coordinator import _controlled_owner; "
        "_controlled_owner(*(Path(p) for p in sys.argv[1:]))"
    )
    with (control / "owner.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            python_command(code, root, source.parent, control),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            **process_options(independent=True),
        )
        try:

            def ready():
                assert child.poll() is None, (control / "owner.log").read_text(encoding="utf-8")
                return (root / "coordinator.json").is_file()

            eventually(ready, description="prestarted coordinator readiness")
            yield root, control, child
        finally:
            (control / "release").touch()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # This Popen handle owns only our fake coordinator, never MATLAB.
                child.terminate()
                child.wait(timeout=5)


@asynccontextmanager
async def sdk_frontend(root, inputs):
    command = python_command(
        "from matlab_companion.__main__ import main; main()",
        "serve",
        "--root",
        root,
        "--allow-root",
        inputs,
        "--idle-seconds",
        IDLE_SECONDS,
    )
    parameters = StdioServerParameters(command=command[0], args=command[1:])
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session, tool, arguments):
    response = await session.call_tool(tool, arguments)
    assert not response.is_error, response
    payload = response.structured_content
    assert payload is not None and payload["ok"], payload
    assert json.loads(response.content[0].text) == payload
    return payload


def test_two_stdio_clients_keep_one_owned_job_after_submitter_disconnect(tmp_path):
    source = source_file(tmp_path)
    with controlled_owner(tmp_path, source) as (root, control, owner):
        identity = read_json(root / "coordinator.json")
        assert identity["pid"] == owner.pid
        assert identity["process_start"] == process_start_identity(owner.pid)

        async def exercise():
            # Observer is the outer context so only the submitting SDK client is
            # closed while the fake worker is deterministically still blocked.
            async with sdk_frontend(root, source.parent) as observer:
                async with sdk_frontend(root, source.parent) as submitter:
                    inspected = await call(submitter, "matlab_inspect", {"path": str(source)})
                    arguments = {
                        "operation": "data_profile",
                        "input_id": inspected["input"]["input_id"],
                        "parameters": {},
                        "idempotency_key": "two-client-disconnect",
                    }
                    accepted = await call(submitter, "matlab_run", arguments)
                    job_id = accepted["job_id"]
                    await eventually_async(
                        lambda: (control / "entered.json").exists(),
                        description="fake backend entry",
                    )
                    observed = await call(observer, "matlab_job", {"job_id": job_id})
                    assert observed["job"]["state"] == "running"
                    assert observed["job"]["phase"] == "executing"
                    sequence = observed["job"]["event_seq"]
                    assert (
                        read_json(root / "coordinator.json")["instance_id"]
                        == identity["instance_id"]
                    )

                assert owner.poll() is None
                assert not (root / "jobs" / job_id / "cancel.flag").exists()
                still_running = await call(observer, "matlab_job", {"job_id": job_id})
                assert still_running["job"]["state"] == "running"
                assert still_running["job"]["event_seq"] == sequence
                (control / "release").touch()
                deadline = time.monotonic() + 10
                while True:
                    observed = await call(
                        observer,
                        "matlab_job",
                        {
                            "job_id": job_id,
                            "action": "wait",
                            "after_event_seq": sequence,
                            "timeout_seconds": 1,
                        },
                    )
                    sequence = observed["job"]["event_seq"]
                    if observed["job"]["state"] == "completed":
                        break
                    assert time.monotonic() < deadline, observed
                assert observed["job_id"] == observed["job"]["job_id"] == job_id
                assert observed["result"]["operation"] == "data_profile"
                replay = await call(observer, "matlab_run", arguments)
                assert replay["job_id"] == job_id
                assert (control / "dispatches.txt").read_text().splitlines() == [job_id]
                return job_id

        job_id = asyncio.run(exercise())
        assert owner.wait(timeout=10) == 0, (control / "owner.log").read_text(encoding="utf-8")
        assert not (root / "coordinator.json").exists()
        assert not process_alive(owner.pid)
        assert read_json(root / "coordinator-stopped.json")["reason"] == "idle"
        assert read_json(root / "jobs" / job_id / "state.json")["state"] == "completed"
        assert (root / "jobs" / job_id / "receipt.json").is_file()
        assert (
            root / "jobs" / job_id / "outputs" / "input.csv"
        ).read_bytes() == source.read_bytes()


def test_real_auto_start_is_passive_until_inspection_and_exits_without_deleting_inputs(tmp_path):
    source = source_file(tmp_path)
    root = tmp_path / "automatic store"
    client = CoordinatorClient(root, [source.parent], idle_seconds=IDLE_SECONDS)
    status = client.call("matlab_status", {})
    assert status["ok"]
    assert not root.exists(), "Passive status must not create or start the coordinator"
    inspected = client.call("matlab_inspect", {"path": str(source)})
    assert inspected["ok"], inspected
    record = read_json(root / "coordinator.json")
    assert record["pid"] != os.getpid()
    assert process_alive(record["pid"])
    assert process_start_identity(record["pid"]) == record["process_start"]
    client.close()
    eventually(lambda: not process_alive(record["pid"]), description="automatic owner idle exit")
    assert not (root / "coordinator.json").exists()
    assert read_json(root / "coordinator-stopped.json")["reason"] == "idle"
    assert source.read_text() == "concentration,absorbance\n1,3\n2,5\n"
    assert list((root / "inputs").glob("*.json"))
    assert not list((root / "jobs").iterdir())


def test_changed_configuration_cannot_silently_join_or_replace_a_live_owner(tmp_path):
    source = source_file(tmp_path)
    with controlled_owner(tmp_path, source) as (root, _control, owner):
        before = (root / "coordinator.json").read_bytes()
        client = CoordinatorClient(root, [tmp_path / "another input"], idle_seconds=IDLE_SECONDS)
        refused = client.call("matlab_inspect", {"path": str(source)})
        assert not refused["ok"]
        assert refused["error"]["code"] == "COORDINATOR_CONFIGURATION_CHANGED"
        assert (root / "coordinator.json").read_bytes() == before
        assert owner.poll() is None
        assert not list((root / "inputs").iterdir())


def test_lost_rpc_response_is_not_automatically_retransmitted(tmp_path):
    root = tmp_path / "store"
    root.mkdir()
    instance = str(uuid.uuid4())
    _, fingerprint = resolved_configuration(root)
    received = []
    failures = []
    with LocalListener(root, instance) as listener:
        atomic_json(
            root / "coordinator.json",
            {
                "protocol": PROTOCOL_VERSION,
                "instance_id": instance,
                "pid": os.getpid(),
                "process_start": process_start_identity(os.getpid()),
                "version": __version__,
                "root": str(root.resolve()),
                "configuration_sha256": fingerprint,
                "endpoint": {"kind": listener.endpoint.kind, "address": listener.endpoint.address},
            },
        )

        def consume_without_response():
            try:
                with listener.accept(timeout=3) as connection:
                    received.append(connection.recv_json(timeout=3))
                    atomic_json(
                        root / "accepted-once.json", {"request_id": received[0]["request_id"]}
                    )
                try:
                    second = listener.accept(timeout=0.3)
                except TimeoutError:
                    return
                with second:
                    received.append(second.recv_json(timeout=1))
            except Exception as error:  # noqa: BLE001 - return worker failures to pytest.
                failures.append(error)

        thread = threading.Thread(target=consume_without_response)
        thread.start()
        response = CoordinatorClient(root).call(
            "matlab_inspect", {"path": str(tmp_path / "file.csv")}
        )
        thread.join(5)
        assert not thread.is_alive()
        assert not failures
        assert not response["ok"]
        assert response["error"]["code"] == "COORDINATOR_RESPONSE_UNCONFIRMED"
        assert len(received) == 1
        assert read_json(root / "accepted-once.json")["request_id"] == received[0]["request_id"]


def test_two_initial_client_processes_share_a_single_automatically_started_owner(tmp_path):
    source = source_file(tmp_path)
    root, release = tmp_path / "shared store", tmp_path / "connect now"
    code = "from test_coordinator import _initial_client; _initial_client(*sys.argv[1:])"
    children = []
    child_outputs = []
    try:
        for index in range(2):
            children.append(
                subprocess.Popen(
                    python_command(
                        code,
                        root,
                        source,
                        release,
                        tmp_path / f"client-{index}.json",
                        sys.executable,
                    ),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    **process_options(),
                )
            )
        eventually(
            lambda: all((tmp_path / f"client-{index}.json.ready").exists() for index in range(2)),
            description="both client processes waiting at the connect barrier",
        )
        release.touch()
        results = []
        for index, child in enumerate(children):
            out, error = child.communicate(timeout=20)
            child_outputs.append(
                {"client": index, "returncode": child.returncode, "stdout": out, "stderr": error}
            )
            assert child.returncode == 0
            results.append(read_json(tmp_path / f"client-{index}.json"))
        if (
            os.name == "nt"
            and len(results) == 2
            and all(
                item["response"].get("ok") is False
                and (item["response"].get("error") or {}).get("code")
                == "COORDINATOR_START_BLOCKED"
                and item["owner"] is None
                and len(item.get("launches", [])) == 1
                and item["launches"][0].get("creationflags") == 150994944
                and item["launches"][0].get("error", {}).get("winerror") == 5
                and item["launches"][0].get("error", {}).get("errno") == 13
                and "launcher_pid" not in item["launches"][0]
                for item in results
            )
            and (
                not root.exists()
                or all(
                    path.name == ".coordinator-start.lock" and path.is_file()
                    for path in root.iterdir()
                )
            )
        ):
            pytest.skip(
                "Windows runner rejected both nested CREATE_BREAKAWAY_FROM_JOB | "
                "CREATE_NO_WINDOW launches with WinError 5 (errno 13); no process, "
                "owner, job store or native marker was created. Positive auto-start "
                "is unsupported here; the separate strict-Job refusal test still applies."
            )
        if not all(item["response"]["ok"] for item in results):
            pytest.fail("Initial clients did not both connect; full diagnostics follow", pytrace=False)
        assert results[0]["owner"]["instance_id"] == results[1]["owner"]["instance_id"]
        assert results[0]["owner"]["pid"] == results[1]["owner"]["pid"]
        assert (
            results[0]["response"]["input"]["sha256"] == results[1]["response"]["input"]["sha256"]
        )
        owner_pid = results[0]["owner"]["pid"]
        eventually(lambda: not process_alive(owner_pid), description="shared owner idle exit")
        assert not (root / "coordinator.json").exists()
    except BaseException:
        # Captured stdout is shown in full on failure; assertion repr truncates
        # the response error codes that distinguish blocked/failed/unready owners.
        diagnostics = {"clients": child_outputs, "records": {}, "owner_logs": {}}
        for index in range(2):
            record = tmp_path / f"client-{index}.json"
            if record.is_file():
                try:
                    diagnostics["records"][str(index)] = json.loads(
                        record.read_text(encoding="utf-8")
                    )
                except (OSError, ValueError) as error:
                    diagnostics["records"][str(index)] = {"read_error": repr(error)}
            for suffix in ("owner.stdout", "owner.stderr"):
                log = record.with_suffix("." + suffix)
                if log.is_file():
                    diagnostics["owner_logs"][f"{index}.{suffix}"] = log.read_text(
                        encoding="utf-8", errors="replace"
                    )
        print("Initial-client startup diagnostics:\n" + json.dumps(diagnostics, indent=2))
        raise
    finally:
        release.touch()
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.communicate(timeout=5)


def _initial_client(root, source, release, result, runtime):
    from matlab_companion import coordinator

    # Start each real client through the base interpreter, but let production
    # auto-start use the installed/venv runtime it would normally receive.
    sys.executable = runtime
    result = Path(result)
    result.with_suffix(result.suffix + ".ready").touch()
    eventually(lambda: Path(release).exists(), description="simultaneous client release")
    original_popen = coordinator.subprocess.Popen
    launches = []
    owners = []

    def observed_popen(*args, **kwargs):
        # Observe the real production startup, changing only its discarded log
        # destinations. Keep command, environment, flags and lifetimes unchanged.
        launch = {"command": args[0], "creationflags": kwargs.get("creationflags", 0)}
        launches.append(launch)
        try:
            with (
                result.with_suffix(".owner.stdout").open("ab") as stdout,
                result.with_suffix(".owner.stderr").open("ab") as stderr,
            ):
                child = original_popen(*args, **(kwargs | {"stdout": stdout, "stderr": stderr}))
            owners.append(child)
            launch["launcher_pid"] = child.pid
            return child
        except OSError as error:
            launch["error"] = {
                "type": type(error).__name__,
                "errno": error.errno,
                "winerror": getattr(error, "winerror", None),
                "message": str(error),
            }
            raise

    coordinator.subprocess.Popen = observed_popen
    try:
        response = CoordinatorClient(
            root, [Path(source).parent], idle_seconds=PRESTART_IDLE_SECONDS
        ).call("matlab_inspect", {"path": source})
    finally:
        coordinator.subprocess.Popen = original_popen
    for launch, owner in zip(launches, owners, strict=False):
        launch["launcher_returncode_at_response"] = owner.poll()
    metadata = Path(root) / "coordinator.json"
    atomic_json(
        result,
        {
            "response": response,
            "owner": read_json(metadata) if metadata.exists() else None,
            "launches": launches,
        },
    )


@pytest.mark.skipif(os.name != "nt", reason="Public Windows Job ownership boundary")
def test_restrictive_windows_job_refuses_background_start_without_child_fallback(tmp_path):
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    job = kernel.CreateJobObjectW(None, None)
    assert job, ctypes.WinError(ctypes.get_last_error())
    root = tmp_path / "blocked store"
    code = (
        "from pathlib import Path; from matlab_companion.client import CoordinatorClient; "
        "sys.stdin.readline(); import json; "
        "print(json.dumps(CoordinatorClient(sys.argv[1],idle_seconds=.5).call("
        "'matlab_inspect',{'path':str(Path(sys.argv[1])/'selected.csv')})))"
    )
    child = None
    try:
        child = subprocess.Popen(
            python_command(code, root),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **process_options(),
        )
        # The barrier keeps our own child idle until it joins a fresh Job with
        # default limits: breakaway is forbidden. No unrelated process joins it.
        assert kernel.AssignProcessToJobObject(job, int(child._handle)), ctypes.WinError(
            ctypes.get_last_error()
        )
        output, error = child.communicate("start\n", timeout=15)
        assert child.returncode == 0, error
        response = json.loads(output)
        assert not response["ok"]
        assert response["error"]["code"] == "COORDINATOR_START_BLOCKED"
        assert "No ordinary child fallback" in response["error"]["message"]
        assert not (root / "coordinator.json").exists()
        assert not (root / "jobs").exists()
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.communicate(timeout=5)
        kernel.CloseHandle(job)
