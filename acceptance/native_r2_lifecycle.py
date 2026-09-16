"""Opt-in Windows R2 native ownership acceptance with real SDK stdio clients.

Nothing launches without --run-native and explicit existing MATLAB/backend paths.
Three new private stores exercise submitting-client disconnect, explicit cancel,
and a precisely owned coordinator crash. An independently owned MATLAB sentinel
retains state and a held OS process handle throughout. Unknown jobs and all logs
are retained; no process-name kill, user-session attachment, or quarantine removal
is performed. The only forced stop targets the exact coordinator Popen handle in
the crash case (and the exact Python harness worker on its controller deadline).

The production Coordinator and OfficialBackend run unchanged. An acceptance-only
copy of companion.execute counts native entries and waits at most 90 seconds for
an owned release flag before calling the original entrypoint, renamed locally.
All scientific helpers retain their original bytes. This transparent delay makes
the interruption window reproducible; it is not a production workload benchmark.

The coordinator is explicitly prestarted with CREATE_BREAKAWAY_FROM_JOB, without
a fallback. Its actual outer Job membership is recorded. Acceptance covers one
frontend's SDK teardown, not closing the entire host application or outer OS Job.
Strict-host automatic bootstrap refusal is a separate portable test gate.

Default output is private temporary storage. --public-output optionally writes
an allowlisted receipt without paths, account names, PIDs, or session nonces.
No native acceptance is claimed by --help, syntax checks, or portable tests.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import shutil
import site
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from matlab_companion.backend import ASSETS, BACKEND_VERSION, backend_path, native_code_root
from matlab_companion.storage import atomic_json, digest, read_json, utc_now

IDLE_SECONDS = 5
START_SECONDS = 120
RESULT_SECONDS = 180
LATE_SECONDS = 60
DELAY_SECONDS = 90
WORKER_SECONDS = 900
FILETIME_UNIX_EPOCH = 116444736000000000
BOOTSTRAP_CONTEXT_ENV = "MATLAB_COMPANION_R2_PYTHON_CONTEXT"
SCOPE = (
    "Windows R2 production coordinator, real SDK stdio clients, synthetic native jobs, "
    "explicit cancel, coordinator crash and unrelated owned-sentinel preservation. "
    "Acceptance-only bounded native-entry delay; not a host-model or package-release gate."
)


def load_r1():
    """Use the independent held-handle oracle and sentinel, including under -I."""
    path = Path(__file__).with_name("native_r1_lifecycle.py")
    spec = importlib.util.spec_from_file_location("companion_r1_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


r1 = load_r1()
require = r1.require
optional_json = r1.optional_json


def bootstrap_context() -> dict:
    """Keep the first controller's dependency roots across base-interpreter hops."""
    import matlab_companion

    runtime_parent = str(Path(matlab_companion.__file__).resolve().parent.parent)
    inherited = os.environ.get(BOOTSTRAP_CONTEXT_ENV)
    context = (
        json.loads(inherited)
        if inherited
        else {
            "runtime_parent": runtime_parent,
            "site_roots": site.getsitepackages(),
        }
    )
    require(
        isinstance(context, dict)
        and set(context) == {"runtime_parent", "site_roots"}
        and context["runtime_parent"] == runtime_parent
        and isinstance(context["site_roots"], list)
        and context["site_roots"]
        and all(
            isinstance(path, str) and Path(path).is_absolute() for path in context["site_roots"]
        ),
        "Harness bootstrap must preserve the initial controller's actual runtime and dependencies",
    )
    return context


def python_command(code: str, *arguments) -> list[str]:
    # Avoid the Windows venv redirector: SDK teardown must own the real frontend.
    # After a venv -> base hop, site.getsitepackages() describes base Python, so
    # every further hop must inherit the original controller's locked deps.
    context = bootstrap_context()
    bootstrap = (
        "import os,sys,site; os.environ["
        + repr(BOOTSTRAP_CONTEXT_ENV)
        + "] = "
        + repr(json.dumps(context))
        + "; [site.addsitedir(p) for p in "
        + repr(context["site_roots"])
        + "]; sys.path.insert(0, "
        + repr(context["runtime_parent"])
        + "); "
    )
    return [sys._base_executable, "-I", "-B", "-c", bootstrap + code, *map(str, arguments)]


def own_command(mode: str, directory: Path) -> list[str]:
    return python_command(
        "import runpy; sys.argv=[sys.argv[1],*sys.argv[2:]]; "
        "runpy.run_path(sys.argv[0],run_name='__main__')",
        Path(__file__).resolve(),
        mode,
        directory,
    )


def delayed_helpers(root: Path) -> Path:
    helpers = root / "native-helpers"
    shutil.copytree(native_code_root(), helpers)
    package = helpers / "+companion"
    original = (package / "execute.m").read_text(encoding="utf-8")
    require(
        original.startswith("function receipt = execute(requestPath)"),
        "The native entrypoint changed; review the acceptance instrumentation",
    )
    (package / "execute_native.m").write_text(
        original.replace(
            "function receipt = execute(requestPath)",
            "function receipt = execute_native(requestPath)",
            1,
        ),
        encoding="utf-8",
    )
    (package / "execute.m").write_text(
        f"""function receipt = execute(requestPath)
% Acceptance-only entry counter and bounded scheduling window; recipes unchanged.
job = fileparts(requestPath);
session = jsondecode(fileread(fullfile(job, 'native-session.json')));
fid = fopen(fullfile(job, 'r2-native-entries.log'), 'a', 'n', 'UTF-8');
assert(fid ~= -1, 'R2:EntryLog', 'Cannot record acceptance native entry');
fprintf(fid, '%s\\n', session.session_id);
assert(fclose(fid) == 0, 'R2:EntryLog', 'Cannot close acceptance entry log');
started = tic;
while ~isfile(fullfile(job, 'r2-release.flag')) && toc(started) < {DELAY_SECONDS}
    pause(0.05);
end
receipt = companion.execute_native(requestPath);
end
""",
        encoding="utf-8",
    )
    for source in (native_code_root() / "+companion").glob("*.m"):
        if source.name != "execute.m":
            require(
                digest(source) == digest(package / source.name), "Scientific helper copy changed"
            )
    return helpers


def coordinator_child(case: Path) -> int:
    """Instrument only native helper selection; run the production coordinator."""
    import matlab_companion.backend as backend_module
    from matlab_companion.coordinator import Coordinator

    ownership = read_json(case.parent / "ownership.json")
    require(ownership["kind"] == "native_r2_lifecycle", "Private ownership marker mismatch")
    backend_module.native_code_root = lambda: case.parent / "native-helpers"
    Coordinator(case / "store", allowed_roots=[case / "fixtures"], idle_seconds=IDLE_SECONDS).run()
    return 0


class Owner:
    def __init__(self, case: Path, generation: int):
        self.case = case
        self.log = (case / f"coordinator-{generation}.log").open("w", encoding="utf-8")
        self.child = subprocess.Popen(
            own_command("--coordinator-root", case),
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB | subprocess.CREATE_NO_WINDOW,
        )
        self.observed = r1.ObservedProcess(self.child.pid)
        self.record = None
        self.crashed = False

    async def ready(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            require(self.child.poll() is None, "Owned coordinator exited before readiness")
            record = optional_json(self.case / "store" / "coordinator.json")
            if record and record["pid"] == self.child.pid:
                expected = f"windows-filetime:{self.observed.identity['creation_filetime']}"
                require(record["process_start"] == expected, "Coordinator birth identity mismatch")
                require(
                    Path(self.observed.identity["executable"]).resolve()
                    == Path(sys._base_executable).resolve(),
                    "Unexpected coordinator executable",
                )
                self.record = record
                return
            await asyncio.sleep(0.05)
        raise TimeoutError("Owned coordinator readiness deadline")

    def crash(self):
        require(self.observed.state() == "alive", "Coordinator exited before the crash injection")
        # Popen retains the precise process handle. No PID/name search or native termination.
        self.child.terminate()
        self.child.wait(timeout=5)
        require(self.observed.state() == "exited", "Exact coordinator stop was not observed")
        self.crashed = True

    async def idle_exit(self, *, degraded: bool):
        deadline = time.monotonic() + IDLE_SECONDS + 20
        while time.monotonic() < deadline and self.child.poll() is None:
            await asyncio.sleep(0.1)
        require(self.observed.state() == "exited", "Coordinator did not exit within idle bound")
        stopped = read_json(self.case / "store" / "coordinator-stopped.json")
        require(stopped["instance_id"] == self.record["instance_id"], "Stale idle receipt")
        require(
            stopped["reason"] == ("idle_degraded" if degraded else "idle"),
            "Idle classification did not match unresolved ownership",
        )
        require(self.child.returncode == 0, "Coordinator idle exit was not normal")
        return stopped

    def close_handles(self):
        self.observed.close()
        self.log.close()


@asynccontextmanager
async def frontend(case: Path, name: str):
    command = python_command(
        "from matlab_companion.__main__ import main; main()",
        "serve",
        "--root",
        case / "store",
        "--allow-root",
        case / "fixtures",
        "--idle-seconds",
        IDLE_SECONDS,
    )
    parameters = StdioServerParameters(command=command[0], args=command[1:])
    with (case / f"frontend-{name}.log").open("w", encoding="utf-8") as errors:
        async with stdio_client(parameters, errlog=errors) as (read, write):
            async with ClientSession(read, write) as session:
                await asyncio.wait_for(session.initialize(), timeout=20)
                yield session


async def call(session, tool: str, arguments: dict, *, expect_ok=True):
    response = await asyncio.wait_for(session.call_tool(tool, arguments), timeout=25)
    value = response.structured_content
    require(isinstance(value, dict), "MCP result omitted its structured contract")
    require(json.loads(response.content[0].text) == value, "MCP JSON fallback disagreed")
    require(
        bool(response.is_error) is (not value["ok"]), "MCP error flag disagreed with its contract"
    )
    require(bool(value["ok"]) == expect_ok, "Unexpected MCP result outcome")
    return value


def entry_count(job: Path) -> int:
    try:
        return len((job / "r2-native-entries.log").read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return 0


async def native_window(job: Path, installation: Path, lower_ns: int):
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        marker = optional_json(job / "native-session.json")
        lifecycle = optional_json(job / "native-lifecycle.json")
        if marker and lifecycle and entry_count(job):
            require(
                marker["contract_version"] == "1.0" and marker["job_id"] == job.name,
                "Native session marker mismatch",
            )
            require(marker["session_id"] == lifecycle["session_id"], "Launcher nonce mismatch")
            native = r1.ObservedProcess(marker["matlab_pid"])
            try:
                expected = installation / "bin" / "win64" / "MATLAB.exe"
                require(
                    Path(native.identity["executable"]).resolve() == expected.resolve(),
                    "Native executable differs from the selected installation",
                )
                created_ns = (native.identity["creation_filetime"] - FILETIME_UNIX_EPOCH) * 100
                require(
                    lower_ns - 100
                    <= created_ns
                    <= (job / "native-session.json").stat().st_mtime_ns + 100,
                    "Native process birth is outside the owned launch window",
                )
                require(not (job / "receipt.json").exists(), "Native delay window already ended")
                require(entry_count(job) == 1, "Native execution was repeated")
                require(
                    (job / "r2-native-entries.log").read_text(encoding="utf-8").splitlines()
                    == [marker["session_id"]],
                    "Native entry did not match its launcher nonce",
                )
                return native
            except BaseException:
                native.close()
                raise
        await asyncio.sleep(0.05)
    raise TimeoutError("Native identity and bounded delay window were not observed")


async def terminal(session, job_id: str):
    deadline = time.monotonic() + RESULT_SECONDS
    sequence = 0
    while time.monotonic() < deadline:
        response = await call(
            session,
            "matlab_job",
            {
                "job_id": job_id,
                "action": "wait",
                "after_event_seq": sequence,
                "timeout_seconds": 2,
            },
        )
        state = response["job"]
        require(state["event_seq"] >= sequence, "Job event sequence regressed")
        sequence = state["event_seq"]
        if state["state"] in {"completed", "cancelled", "failed", "unknown"}:
            return state
    raise TimeoutError("Terminal job observation deadline")


def prepare_case(root: Path, name: str, binary: Path, installation: Path):
    case = root / name
    (case / "fixtures").mkdir(parents=True)
    target = backend_path(case / "store")
    target.parent.mkdir(parents=True)
    shutil.copyfile(binary, target)
    require(digest(target) == digest(binary), "Isolated backend copy differs")
    atomic_json(case / "store" / "settings.json", {"matlab_root": str(installation)})
    source = case / "fixtures" / "synthetic.csv"
    source.write_text("x,y\n0,1\n1,3\n2,5\n3,7\n", encoding="utf-8", newline="\n")
    return case


async def submission(session, case: Path, operation: str):
    arguments = {"operation": operation, "parameters": {}, "idempotency_key": "owned-r2-case"}
    if operation == "data_profile":
        inspected = await call(
            session, "matlab_inspect", {"path": str(case / "fixtures" / "synthetic.csv")}
        )
        arguments["input_id"] = inspected["input"]["input_id"]
    else:
        arguments["parameters"] = {
            "initial_concentration": 2,
            "rate_constant": 0.25,
            "time_end": 8,
            "points": 41,
            "concentration_unit": "mmol/L",
            "time_unit": "s",
            "title": "R2 synthetic",
        }
    accepted = await call(session, "matlab_run", arguments)
    return accepted["job_id"], arguments


async def regular_case(case, installation, save, *, cancel=False):
    lower_ns = time.time_ns()
    owner, native = Owner(case, 1), None
    result = {"case": case.name, "operation": "first_order_kinetics" if cancel else "data_profile"}
    source_hash = digest(case / "fixtures" / "synthetic.csv")
    try:
        await owner.ready()
        result["coordinator"] = owner.record
        async with frontend(case, "observer") as observer:
            async with frontend(case, "submitter") as submitter:
                job_id, arguments = await submission(submitter, case, result["operation"])
                job = case / "store" / "jobs" / job_id
                result["job_id"] = job_id
                native = await native_window(job, installation, lower_ns)
                result["native_before"] = native.observation()
                dispatch_hash = digest(job / "dispatch.json")
                request_hash = digest(job / "request.json")
                session_hash = digest(job / "native-session.json")
                observed = await call(observer, "matlab_job", {"job_id": job_id})
                require(
                    observed["job"]["state"] == "running",
                    "Second client did not observe owned work",
                )
                save(case.name + "_native_window")
            require(owner.observed.state() == "alive", "Submitter teardown stopped coordinator")
            require(native.state() == "alive", "Submitter teardown stopped native computation")
            require(not (job / "cancel.flag").exists(), "Client disconnect implicitly cancelled")
            result["submitter_disconnect_preserved_owner"] = True
            result["submitter_disconnect_preserved_native"] = True
            repeated = await call(observer, "matlab_run", arguments)
            require(repeated["job_id"] == job_id, "Same idempotency key changed the job")
            result["same_job_observed"] = True
            if cancel:
                cancelled = await call(
                    observer, "matlab_job", {"job_id": job_id, "action": "cancel"}
                )
                result["cancel_response_state"] = cancelled["job"]["state"]
                result["native_alive_after_cancel_request"] = native.state() == "alive"
                require(
                    cancelled["job"]["state"] == "cancel_requested",
                    "Cancel request was not explicit",
                )
                require(
                    result["native_alive_after_cancel_request"],
                    "Cancel intent was confused with native stop",
                )
            (job / "r2-release.flag").touch()
            state = await terminal(observer, job_id)
            result["state"] = state["state"]
            require(
                state["state"] == ("cancelled" if cancel else "completed"),
                "Unexpected native terminal state",
            )
            lifecycle = read_json(job / "native-lifecycle.json")
            require(
                lifecycle["native_exited"] is True, "Production native exit gate was not confirmed"
            )
            require(
                native.state() == "exited", "Independent held handle did not confirm native exit"
            )
            result["native_lifecycle"] = lifecycle
            result["native_after"] = native.observation()
            result["native_entry_count"] = entry_count(job)
            require(result["native_entry_count"] == 1, "Native recipe was replayed")
            result["dispatch_preserved"] = digest(job / "dispatch.json") == dispatch_hash
            result["request_preserved"] = digest(job / "request.json") == request_hash
            result["session_preserved"] = digest(job / "native-session.json") == session_hash
            require(
                all(
                    result[key]
                    for key in ("dispatch_preserved", "request_preserved", "session_preserved")
                ),
                "Accepted dispatch or native session identity changed",
            )
            receipt = read_json(job / "receipt.json")
            result["verification"] = receipt["verification"]
            if not cancel:
                require(receipt["details"]["rows"] == 4, "Synthetic profile result changed")
                require(receipt["verification"]["native_reopen"], "Native MAT readback was absent")
        result["idle"] = await owner.idle_exit(degraded=False)
        require(
            digest(case / "fixtures" / "synthetic.csv") == source_hash, "Synthetic input changed"
        )
        result["outcome"] = "passed"
        return result
    finally:
        result.setdefault("outcome", "failed")
        result["coordinator_final_observation"] = owner.observed.observation()
        if native:
            result["native_final_observation"] = native.observation()
            native.close()
        atomic_json(case / "case-report.json", result)
        owner.close_handles()


async def crash_case(case, installation, save):
    lower_ns = time.time_ns()
    owner, replacement, native = Owner(case, 1), None, None
    result = {"case": case.name, "operation": "first_order_kinetics"}
    try:
        await owner.ready()
        result["coordinator"] = owner.record
        async with frontend(case, "before-crash") as client:
            job_id, arguments = await submission(client, case, result["operation"])
            job = case / "store" / "jobs" / job_id
            result["job_id"] = job_id
            native = await native_window(job, installation, lower_ns)
            hashes = {
                name: digest(job / name)
                for name in ("dispatch.json", "request.json", "native-session.json")
            }
            result["native_before"] = native.observation()
            owner.crash()
            save("coordinator_crash_injected")
        require(not (job / "receipt.json").exists(), "A receipt arrived before recovery inspection")
        replacement = Owner(case, 2)
        await replacement.ready()
        result["replacement"] = replacement.record
        async with frontend(case, "after-crash") as client:
            recovered = await call(client, "matlab_job", {"job_id": job_id})
            result["recovered_state"] = recovered["job"]["state"]
            require(
                result["recovered_state"] == "unknown",
                "Dispatched crash was not preserved as unknown",
            )
            require(
                (case / "store" / "executor-quarantine.json").is_file(), "Crash quarantine missing"
            )
            repeated = await call(client, "matlab_run", arguments)
            require(repeated["job_id"] == job_id, "Recovery changed the original idempotent job")
            before_jobs = set((case / "store" / "jobs").iterdir())
            blocked = await call(
                client,
                "matlab_run",
                arguments | {"idempotency_key": "must-remain-blocked"},
                expect_ok=False,
            )
            result["new_dispatch_error"] = blocked["error"]["code"]
            require(
                result["new_dispatch_error"] == "EXECUTOR_RECOVERY_REQUIRED",
                "New dispatch was not refused by the preserved execution quarantine",
            )
            require(
                set((case / "store" / "jobs").iterdir()) == before_jobs,
                "Quarantine accepted a new job",
            )
            result["new_dispatch_blocked"] = True
            (job / "r2-release.flag").touch()
            save("crash_unknown_quarantine_confirmed")
            deadline = time.monotonic() + LATE_SECONDS
            while time.monotonic() < deadline:
                if (job / "receipt.json").exists():
                    break
                if native.state() == "exited":
                    # A genuine receipt is published before process exit; allow file observation.
                    await asyncio.sleep(0.25)
                    break
                await call(client, "matlab_job", {"job_id": job_id})
                await asyncio.sleep(0.5)
            late = optional_json(job / "receipt.json")
            result["late_receipt_observed"] = late is not None
            reconciled = await call(client, "matlab_job", {"job_id": job_id, "action": "reconcile"})
            result["reconciled_state"] = reconciled["job"]["state"]
            require(
                result["reconciled_state"] == (late["state"] if late else "unknown"),
                "Late-receipt reconciliation disagreed with preserved evidence",
            )
            result["quarantine_preserved"] = (case / "store" / "executor-quarantine.json").is_file()
            require(result["quarantine_preserved"], "Recovery silently cleared quarantine")
            result["dispatch_preserved"] = all(
                digest(job / name) == value for name, value in hashes.items()
            )
            result["native_entry_count"] = entry_count(job)
            require(
                result["dispatch_preserved"] and result["native_entry_count"] == 1,
                "A dispatched native operation was modified or replayed",
            )
            result["native_after"] = native.observation()
            result["native_lifecycle"] = optional_json(job / "native-lifecycle.json")
        result["idle"] = await replacement.idle_exit(degraded=True)
        result["outcome"] = "passed"
        return result
    finally:
        result.setdefault("outcome", "failed")
        if native:
            result["native_final_observation"] = native.observation()
            native.close()
        atomic_json(case / "case-report.json", result)
        owner.close_handles()
        if replacement:
            replacement.close_handles()


def worker(root: Path) -> int:
    config = read_json(root / "ownership.json")
    require(config["kind"] == "native_r2_lifecycle", "Worker requires its owned directory")
    installation, binary = Path(config["matlab_root"]), Path(config["backend_binary"])
    report = {"outcome": "running", "cases": [], "events": []}

    def save(phase):
        report["events"].append({"phase": phase, "observed_at": utc_now()})
        atomic_json(root / "worker-report.json", report)

    async def run_cases():
        for name in ("disconnect", "cancel", "crash"):
            case = prepare_case(root, name, binary, installation)
            save(name + "_starting")
            if name == "crash":
                result = await crash_case(case, installation, save)
            else:
                result = await regular_case(case, installation, save, cancel=name == "cancel")
            report["cases"].append(result)
            save(name + "_passed")

    try:
        asyncio.run(run_cases())
        report["outcome"] = "passed"
        save("worker_completed")
        return 0
    except BaseException as error:  # noqa: BLE001 -- Preserve all unknown jobs without replay.
        report["outcome"] = "failed"
        report["error_type"] = type(error).__name__
        completed_cases = {item["case"] for item in report["cases"]}
        for name in ("disconnect", "cancel", "crash"):
            partial = optional_json(root / name / "case-report.json")
            if partial and name not in completed_cases:
                report["cases"].append(partial)
        (root / "worker-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        save("worker_failed")
        return 1


def public_receipt(private: dict) -> dict:
    cases = []
    fields = (
        "case",
        "operation",
        "outcome",
        "state",
        "recovered_state",
        "reconciled_state",
        "submitter_disconnect_preserved_owner",
        "submitter_disconnect_preserved_native",
        "same_job_observed",
        "cancel_response_state",
        "native_alive_after_cancel_request",
        "native_entry_count",
        "dispatch_preserved",
        "request_preserved",
        "session_preserved",
        "late_receipt_observed",
        "quarantine_preserved",
        "new_dispatch_blocked",
        "new_dispatch_error",
        "verification",
    )
    for item in private.get("worker", {}).get("cases", []):
        summary = {key: item.get(key) for key in fields if key in item}
        outer_job = item.get("coordinator", {}).get("windows_job") or {}
        summary["outer_job"] = {key: outer_job.get(key) for key in ("member", "limit_flags")}
        summary["lifetime_scope"] = (
            "Individual frontend disconnect; entire host/outer Job close is not covered"
        )
        summary["idle_reason"] = item.get("idle", {}).get("reason")
        summary["native_handle_state"] = item.get("native_final_observation", {}).get(
            "process_state"
        )
        summary["native_stop_observed"] = item.get("native_final_observation", {}).get(
            "native_stopped"
        )
        lifecycle = item.get("native_lifecycle") or {}
        summary["production_native_exited"] = lifecycle.get("native_exited")
        summary["production_rpc_response_observed"] = lifecycle.get("rpc_response_observed")
        cases.append(summary)
    return {
        **{
            key: private.get(key)
            for key in (
                "scope",
                "observed_at",
                "outcome",
                "source_commit",
                "source_dirty",
                "runtime_version",
                "runtime_sources",
                "native_sources",
                "harness_sha256",
                "r1_oracle_sha256",
                "instrumentation_sha256",
                "error_type",
            )
        },
        "source_commit_scope": "Working-directory checkout; runtime source hashes bind imported code separately",
        "platform": "Windows",
        "backend_version": BACKEND_VERSION,
        "injection": {
            "native_entry_delay_max_seconds": DELAY_SECONDS,
            "scientific_helpers_unchanged": True,
            "coordinator_start": "Explicit BREAKAWAY_FROM_JOB plus NO_WINDOW, no fallback",
        },
        "cases": cases,
        "sentinel": {
            key: private.get("sentinel", {}).get(key)
            for key in (
                "identity_observed",
                "state_preserved",
                "heartbeat_advanced",
                "samples",
                "heartbeat_read_retries",
                "matlab_release",
                "matlab_version",
                "cooperative_stop_acknowledged",
                "native_stop_observed",
            )
        },
        "limitations": [
            "Synthetic owned sentinel, not a user's existing session.",
            "Prestarted coordinator path; strict SDK automatic-start refusal has separate portable evidence.",
            "Cancel intent, terminal receipt, backend response and held-handle exit are separate observations.",
            "Unknown crash work and quarantine remain preserved even if a held handle later proves exit.",
            "No native result is replayed to repair this acceptance, and no default user settings are edited.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--run-native", action="store_true", help="Explicitly launch owned native acceptance"
    )
    parser.add_argument(
        "--matlab-root", type=Path, help="Existing licensed MATLAB R2025a+ installation"
    )
    parser.add_argument(
        "--backend-binary", type=Path, help="Existing pinned official backend; no download"
    )
    parser.add_argument(
        "--run-root", type=Path, help="New private directory, must not already exist"
    )
    parser.add_argument("--public-output", type=Path, help="Optional new sanitized public receipt")
    parser.add_argument("--worker-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--coordinator-root", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_root or args.coordinator_root:
        require(
            os.environ.get("MATLAB_COMPANION_R2_CHILD") == "1",
            "Internal mode requires its controller",
        )
        return (
            worker(args.worker_root.resolve())
            if args.worker_root
            else coordinator_child(args.coordinator_root.resolve())
        )
    if not args.run_native:
        parser.print_help()
        return 0
    require(os.name == "nt", "R2 native acceptance currently targets Windows")
    require(
        args.matlab_root is not None and args.backend_binary is not None,
        "Explicit installed paths are required",
    )
    installation, binary = args.matlab_root.resolve(), args.backend_binary.resolve()
    require((installation / "bin" / "matlab.exe").is_file(), "MATLAB installation was not found")
    _, expected = ASSETS[(platform.system(), platform.machine())]
    require(
        binary.is_file() and digest(binary) == expected, "Pinned official backend checksum mismatch"
    )
    require(
        not args.public_output or not args.public_output.exists(),
        "Choose a new public receipt path",
    )
    if args.run_root:
        root = args.run_root.resolve()
        root.mkdir(parents=True, exist_ok=False)
    else:
        root = Path(tempfile.mkdtemp(prefix="mc-r2-lifecycle-"))
    atomic_json(
        root / "ownership.json",
        {
            "kind": "native_r2_lifecycle",
            "nonce": str(uuid.uuid4()),
            "matlab_root": str(installation),
            "backend_binary": str(binary),
            "controller_pid": os.getpid(),
            "python_bootstrap": bootstrap_context(),
        },
    )
    helpers = delayed_helpers(root)
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
        "run_root": str(root),
        "source_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "source_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "runtime_version": importlib.metadata.version("matlab-companion"),
        "runtime_sources": {
            name: digest(Path(importlib.import_module("matlab_companion." + name).__file__))
            for name in (
                "backend",
                "native_session",
                "coordinator",
                "client",
                "core",
                "storage",
                "contracts",
                "server",
            )
        },
        "native_sources": {
            p.name: digest(p) for p in (native_code_root() / "+companion").glob("*.m")
        },
        "harness_sha256": digest(Path(__file__)),
        "r1_oracle_sha256": digest(Path(r1.__file__)),
        "instrumentation_sha256": {
            name: digest(helpers / "+companion" / name)
            for name in ("execute.m", "execute_native.m")
        },
    }
    r1.SENTINEL_LIFETIME = WORKER_SECONDS + r1.SENTINEL_START_TIMEOUT + 90
    sentinel = r1.Sentinel(root, installation, str(uuid.uuid4()))
    child = None
    print("Private R2 acceptance directory:", root, flush=True)
    try:
        sentinel.start()
        environment = os.environ.copy()
        environment["MATLAB_COMPANION_R2_CHILD"] = "1"
        environment.pop("MATLAB_COMPANION_MATLAB_ROOT", None)
        with (root / "worker-stdout.log").open("w", encoding="utf-8") as log:
            child = subprocess.Popen(
                own_command("--worker-root", root),
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            deadline, last_phase = time.monotonic() + WORKER_SECONDS, None
            while child.poll() is None:
                sentinel.check(deadline=deadline)
                current = optional_json(root / "worker-report.json") or {}
                phase = (current.get("events") or [{}])[-1].get("phase")
                if phase and phase != last_phase:
                    sentinel.check(phase, deadline=deadline)
                    print("R2 lifecycle:", phase, flush=True)
                    last_phase = phase
                if time.monotonic() >= deadline:
                    raise TimeoutError("Owned Python harness worker deadline exceeded")
                time.sleep(0.1)
        report["worker"] = read_json(root / "worker-report.json")
        require(
            child.returncode == 0 and report["worker"]["outcome"] == "passed",
            "Native R2 worker failed",
        )
        require(len(report["worker"]["cases"]) == 3, "Not all native lifecycle cases completed")
        sentinel.check("all_cases_completed")
        report["outcome"] = "passed"
    except BaseException as error:  # noqa: BLE001 -- Keep private diagnostics and unknown work.
        report["outcome"] = "failed"
        report["error_type"] = type(error).__name__
        (root / "controller-error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if child is not None and child.poll() is None:
            child.terminate()  # Only the exact Python harness worker; never a native process.
            child.wait(timeout=10)
        if "worker" not in report:
            report["worker"] = optional_json(root / "worker-report.json") or {}
        preserved = False
        if sentinel.native:
            try:
                sentinel.check("before_cooperative_stop")
                preserved = True
            except (AssertionError, OSError):
                report["outcome"] = "failed"
        cleanup = sentinel.stop()
        report["sentinel"] = {
            "identity_observed": sentinel.native is not None,
            "state_preserved": preserved,
            "heartbeat_advanced": bool(
                sentinel.latest and sentinel.latest["counter"] > sentinel.first_counter
            ),
            "samples": sentinel.samples,
            "heartbeat_read_retries": sentinel.read_retries,
            "matlab_release": sentinel.latest.get("matlab_release") if sentinel.latest else None,
            "matlab_version": sentinel.latest.get("matlab_version") if sentinel.latest else None,
            "cooperative_stop_acknowledged": cleanup["cooperative_stop_acknowledged"],
            "native_stop_observed": (cleanup.get("native_observation") or {}).get("native_stopped"),
        }
        if (
            not preserved
            or not report["sentinel"]["native_stop_observed"]
            or not report["sentinel"]["cooperative_stop_acknowledged"]
        ):
            report["outcome"] = "failed"
            report.setdefault("error_type", "SentinelPreservationOrStopUnconfirmed")
        report["sentinel_private"] = {"events": sentinel.events, "cleanup": cleanup}
        atomic_json(root / "report.json", report)
        if args.public_output:
            atomic_json(args.public_output.resolve(), public_receipt(report))
        print("R2 lifecycle outcome:", report["outcome"], flush=True)
        print("Private receipt:", root / "report.json", flush=True)
    return 0 if report["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
