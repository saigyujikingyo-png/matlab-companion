"""Private P2 transaction primitives; deliberately not connected to Setup or MCP.

The current Codex provider cannot switch an existing entry. Staging requires a
process-local capability issued only for a newly created temporary test root.
No Core, subprocess, native operation, job reconciliation or force cleanup lives
here. A future live inventory/conditional provider needs separate acceptance.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from .contracts import JobSummary
from .storage import atomic_json, file_lock, utc_now

MAX_EVENT_BYTES = 64 * 1024
MAX_EVENTS = 128
ROOT_METADATA = (
    "settings.json",
    "codex-connection.json",
    "idempotency.json",
    "coordinator.json",
    "coordinator-start.json",
    "coordinator-stopped.json",
    "executor-active.json",
    "executor-quarantine.json",
    "native-observation.json",
)
JOB_METADATA = (
    "state.json",
    "scheduler.json",
    "dispatch.json",
    "native-lifecycle.json",
    "native-session.json",
    "cancel.flag",
)
JOB_RESULT_MARKERS = ("receipt.json", "backend-result.json")
COVERAGE = frozenset(
    {
        "host_profiles",
        "mcp_entries",
        "plugin_wrappers",
        "shortcuts",
        "startup_entries",
        "scheduled_tasks",
        "services",
        "retained_versions",
        "processes",
    }
)
TRANSITIONS = {
    "prepared": {"admitted", "refused"},
    "admitted": {"stage_requested", "mutation_requested", "refused", "conflict"},
    "stage_requested": {"staged_verified", "unknown", "conflict"},
    "staged_verified": {"mutation_requested", "refused", "conflict"},
    "mutation_requested": {"mutation_observed", "unknown", "conflict"},
    "mutation_observed": {"unknown", "conflict"},
    "refused": set(),
    "unknown": {"unknown", "conflict"},
    "conflict": set(),
}


class ActivationError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def fail(code, message):
    raise ActivationError(code, message)


def canonical(value, *, max_bytes=MAX_EVENT_BYTES):
    try:
        raw = json.dumps(
            value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, RecursionError) as error:
        raise ActivationError("INVALID", "Invalid bounded transaction data") from error
    if len(raw) > max_bytes:
        fail("LIMIT", "Transaction data exceeds its byte bound")
    return raw


def fingerprint(value):
    return hashlib.sha256(canonical(value, max_bytes=4 * 1024 * 1024)).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail("INVALID", "Duplicate transaction metadata key")
        result[key] = value
    return result


def decode(raw):
    if len(raw) > MAX_EVENT_BYTES:
        fail("LIMIT", "Metadata exceeds its byte bound")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, RecursionError, UnicodeError) as error:
        raise ActivationError("INVALID", "Invalid metadata JSON") from error
    if not isinstance(value, dict):
        fail("INVALID", "Metadata must be an object")
    canonical(value)
    return value


def _ordinary(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        fail("ALIAS", "Links and reparse points are not an admitted root or metadata path")
    if not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
        fail("INCOMPLETE", "A selected entry is not an ordinary directory/file")
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        fail("ALIAS", "Hard-linked metadata cannot establish exclusive file identity")


def root_identity(value):
    raw = os.fspath(value)
    path = Path(raw)
    if (
        not path.is_absolute()
        or any(p in {".", ".."} for p in re.split(r"[/\\]", raw))
        or os.path.normcase(str(path.resolve(strict=True))) != os.path.normcase(raw)
    ):
        fail("ALIAS", "Use the exact existing canonical root without aliases")
    for item in reversed([path, *path.parents]):
        _ordinary(item.lstat())
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or not info.st_ino:
        fail("INCOMPLETE", "Root identity is unavailable")
    if os.name == "nt":
        from .ipc import _win

        account = _win().sid  # Read the current token; no endpoint is created.
    else:
        account = f"uid:{os.getuid()}"
    return {
        "path": str(path),
        "volume": str(info.st_dev),
        "file_id": str(info.st_ino),
        "account": account,
    }


def checked_path(root, relative, *, absent=False):
    if (
        not isinstance(relative, str)
        or not relative
        or "\\" in relative
        or any(
            not p
            or p in {".", ".."}
            or ":" in p
            or p.endswith((".", " "))
            or PureWindowsPath(p).is_reserved()
            or any(ord(c) < 32 or c in '<>"|?*' for c in p)
            for p in relative.split("/")
        )
    ):
        fail("ALIAS", "Only contained relative paths are supported")
    current = Path(root)
    for part in relative.split("/"):
        current = current / part
        try:
            _ordinary(current.lstat())
        except FileNotFoundError:
            if not absent:
                raise
    return current


def read_metadata(root, relative):
    path = checked_path(root, relative, absent=True)
    try:
        before = path.lstat()
    except FileNotFoundError:
        return {"exists": False}, None
    _ordinary(before)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_EVENT_BYTES:
        fail("LIMIT", "Selected metadata is not a bounded regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        _ordinary(opened)
        raw = stream.read(MAX_EVENT_BYTES + 1)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        opened.st_dev,
        opened.st_ino,
        opened.st_size,
        opened.st_mtime_ns,
    ) or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        fail("CHANGED", "Selected metadata changed during readback")
    if len(raw) > MAX_EVENT_BYTES:
        fail("LIMIT", "Selected metadata exceeds its byte bound")
    return {
        "exists": True,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "volume": str(before.st_dev),
        "file_id": str(before.st_ino),
        "mtime_ns": before.st_mtime_ns,
    }, raw


@dataclass(frozen=True)
class Limits:
    jobs: int = 10_000
    sources: int = 256
    processes: int = 4096
    metadata_bytes: int = 64 * 1024 * 1024
    seconds: float = 5.0

    def __post_init__(self):
        for name, maximum in (
            ("jobs", 10_000),
            ("sources", 256),
            ("processes", 4096),
            ("metadata_bytes", 64 * 1024 * 1024),
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= maximum:
                fail("LIMIT", "Invalid inventory limit")
        if not 0 < self.seconds <= 10:
            fail("LIMIT", "Invalid inventory deadline")


DEFAULT_LIMITS = Limits()


def _children(root, relative, maximum, deadline):
    folder = checked_path(root, relative, absent=True)
    try:
        entries = os.scandir(folder)
    except FileNotFoundError:
        return []
    values = []
    with entries:
        for entry in entries:
            if time.monotonic() >= deadline or len(values) >= maximum:
                fail("INCOMPLETE", "Inventory reached its count/time bound; nothing was truncated")
            # Windows DirEntry.stat may omit file ID/link count; use fresh lstat.
            info = Path(entry.path).lstat()
            _ordinary(info)
            values.append(
                {
                    "name": entry.name,
                    "directory": stat.S_ISDIR(info.st_mode),
                    "volume": str(info.st_dev),
                    "file_id": str(info.st_ino),
                }
            )
    return sorted(values, key=lambda row: row["name"])


def scan_metadata(root, identity, limits, deadline):
    if root_identity(root) != identity:
        fail("CHANGED", "Canonical root identity changed")
    records, jobs = {}, []
    total = 0

    def capture(relative):
        nonlocal total
        if time.monotonic() >= deadline:
            fail("INCOMPLETE", "Inventory deadline expired")
        record, raw = read_metadata(root, relative)
        records[relative] = record
        total += record.get("size_bytes", 0)
        if total > limits.metadata_bytes:
            fail("INCOMPLETE", "Selected metadata exceeds the total byte bound")
        return raw

    for name in ROOT_METADATA:
        raw = capture(name)
        if raw is not None:
            decode(raw)
        # Existing lifecycle evidence needs separate ownership review, not a
        # permissive interpretation or cleanup by this new transaction module.
        if raw is not None and name in {
            "coordinator.json",
            "coordinator-start.json",
            "executor-active.json",
            "executor-quarantine.json",
        }:
            fail("UNRESOLVED_OWNER", "Existing ownership metadata requires separate review")
    entries = _children(root, "jobs", limits.jobs, deadline)
    for entry in entries:
        job_id = entry["name"]
        if not entry["directory"] or str(uuid.UUID(job_id)) != job_id:
            fail("INCOMPLETE", "Unrecognized job directory identity")
        # Native receipts/backend responses may embed scientific results. Only
        # observe their presence; separate owner review handles their contents.
        result_markers = []
        for name in JOB_RESULT_MARKERS:
            path = checked_path(root, f"jobs/{job_id}/{name}", absent=True)
            try:
                info = path.lstat()
            except FileNotFoundError:
                info = None
            record = {"exists": info is not None, "content_read": False}
            if info is not None:
                _ordinary(info)
                record.update(
                    size_bytes=info.st_size,
                    volume=str(info.st_dev),
                    file_id=str(info.st_ino),
                    mtime_ns=info.st_mtime_ns,
                )
                result_markers.append(name)
            records[f"jobs/{job_id}/{name}"] = record
        raw_state = None
        for name in JOB_METADATA:
            raw = capture(f"jobs/{job_id}/{name}")
            if raw is not None and name.endswith(".json"):
                decode(raw)
            if name == "state.json":
                raw_state = raw
        if raw_state is None:
            fail("INCOMPLETE", "A job has no readable summary")
        state = JobSummary.model_validate(decode(raw_state))
        if state.job_id != job_id:
            fail("INCOMPLETE", "Job path and summary identity disagree")
        if state.state in {"queued", "running", "cancel_requested", "unknown", "interrupted"}:
            fail("UNRESOLVED_JOB", "Accepted or uncertain work requires separate owner review")
        if result_markers or any(
            records[f"jobs/{job_id}/{name}"]["exists"]
            for name in (
                "dispatch.json",
                "native-lifecycle.json",
                "native-session.json",
                "cancel.flag",
            )
        ):
            fail(
                "NATIVE_REVIEW",
                "Historical dispatch/native evidence is preserved for separate review",
            )
        jobs.append({"job_id": job_id, "state": state.state})
    inputs = _children(root, "inputs", limits.jobs, deadline)
    for entry in inputs:
        if entry["directory"] or not re.fullmatch(r"input-[0-9a-f]{32}\.json", entry["name"]):
            fail("INCOMPLETE", "Unrecognized registered-input metadata")
        decode(capture("inputs/" + entry["name"]))
    if entries != _children(root, "jobs", limits.jobs, deadline) or inputs != _children(
        root, "inputs", limits.jobs, deadline
    ):
        fail("CHANGED", "Metadata directory inventory changed during the scan")
    return {
        "root": identity,
        "records": records,
        "job_directories": entries,
        "input_records": inputs,
        "jobs": jobs,
        "selected_bytes": total,
    }


class CodexReadOnlyProvider:
    """No live completeness claim and no write implementation for the current CLI."""

    atomic_conditional = False

    def snapshot(self, identity, limits, deadline):
        return {
            "root": identity,
            "complete": False,
            "coverage": {},
            "sources": [],
            "processes": [],
            "reason": "Complete live launch-source adapter is not accepted",
        }

    def change(self, *args, **kwargs):
        fail(
            "CONDITIONAL_UNAVAILABLE",
            "The current Codex provider cannot conditionally change entries",
        )


def validate_external(value, identity, limits):
    if (
        not isinstance(value, dict)
        or value.get("root") != identity
        or value.get("complete") is not True
        or value.get("coverage") != dict.fromkeys(COVERAGE, True)
    ):
        fail("INCOMPLETE", "Launch/process visibility is incomplete for the declared scope")
    sources, processes = value.get("sources"), value.get("processes")
    if not isinstance(sources, list) or not isinstance(processes, list):
        fail("INCOMPLETE", "External inventory is not a complete list")
    if len(sources) > limits.sources or len(processes) > limits.processes:
        fail("INCOMPLETE", "External inventory exceeded its bound")
    seen = set()
    for source in sources:
        if (
            not isinstance(source, dict)
            or set(source) != {"id", "kind", "identity", "recognized"}
            or source["kind"] not in COVERAGE
            or source["recognized"] is not True
            or not isinstance(source["id"], str)
            or not source["id"]
            or source["id"] in seen
            or not isinstance(source["identity"], dict)
            or not source["identity"]
        ):
            fail("INCOMPLETE", "Unknown, duplicate or ambiguous launch source")
        seen.add(source["id"])
    for process in processes:
        if not isinstance(process, dict) or not all(
            process.get(name)
            for name in ("pid", "creation_identity", "executable", "account", "root")
        ):
            fail("INCOMPLETE", "A process incarnation is not fully visible")
    if processes:
        fail("LIVE_OWNER", "A declared old/new frontend or owner is still present")
    canonical(value)
    return value


@contextlib.contextmanager
def coordination(root):
    identity = root_identity(root)
    try:
        with contextlib.ExitStack() as stack:
            for name in (".activation.lock", ".setup-codex.lock"):
                path = checked_path(root, name, absent=True)
                stack.enter_context(file_lock(path, timeout=0))
            if root_identity(root) != identity:
                fail("CHANGED", "Root changed while acquiring cooperative locks")
            yield identity
    except TimeoutError as error:
        raise ActivationError("BUSY", "Cooperative setup/activation ownership is busy") from error


def admitted_snapshot(root, identity, provider, limits):
    deadline = time.monotonic() + limits.seconds
    try:
        # Existing coordinator order is lifetime -> startup. These probes never
        # wait, so observing a lifetime owner while holding startup cannot deadlock.
        with contextlib.ExitStack() as probes:
            for name in (".coordinator-start.lock", ".coordinator.lock", ".execution.lock"):
                probes.enter_context(file_lock(checked_path(root, name, absent=True), timeout=0))
            first = scan_metadata(root, identity, limits, deadline)
            external_first = validate_external(
                provider.snapshot(identity, limits, deadline), identity, limits
            )
            second = scan_metadata(root, identity, limits, deadline)
            external_second = validate_external(
                provider.snapshot(identity, limits, deadline), identity, limits
            )
            if time.monotonic() >= deadline:
                fail("INCOMPLETE", "The complete two-pass admission exceeded its deadline")
            if first != second or external_first != external_second:
                fail("CHANGED", "Two complete admission observations disagree")
            return {"metadata": second, "external": external_second}
    except TimeoutError as error:
        raise ActivationError("BUSY", "Startup/lifetime/executor ownership is busy") from error
    except ActivationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise ActivationError(
            "INCOMPLETE", "An inventory record could not be completely observed"
        ) from error


def observe_admission(root, provider=None, limits=DEFAULT_LIMITS):
    """Does not rewrite product metadata; cooperative lock files may be created."""
    provider = provider or CodexReadOnlyProvider()
    with coordination(root) as identity:
        return admitted_snapshot(root, identity, provider, limits)


def _exclusive_json(path, value):
    raw = canonical(value)
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        fail("UNKNOWN", "Exclusive write readback failed")


class Journal:
    """One append-only transaction per root; unknown records have no reset path."""

    def __init__(self, root):
        self.root = Path(root)
        self.identity = root_identity(root)
        self.directory = checked_path(root, ".activation", absent=True)

    def _read(self):
        try:
            return self._read_validated()
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ActivationError(
                "UNKNOWN", "Transaction readback is ambiguous; preserve every file"
            ) from error

    def _read_validated(self):
        if root_identity(self.root) != self.identity:
            fail("UNKNOWN", "Transaction root identity changed")
        checked_path(self.root, ".activation")
        entries = _children(self.root, ".activation", MAX_EVENTS + 1, time.monotonic() + 2)
        names = [row["name"] for row in entries]
        events = sorted(name for name in names if re.fullmatch(r"event-\d{4}\.json", name))
        if (
            len(events) < 1
            or len(events) > MAX_EVENTS
            or set(names) != set(events) | {"summary.json"}
            or events != [f"event-{i:04d}.json" for i in range(1, len(events) + 1)]
        ):
            fail("UNKNOWN", "Transaction inventory is incomplete or contains unrecognized files")
        previous, latest = None, None
        for revision, name in enumerate(events, 1):
            _, raw = read_metadata(self.root, ".activation/" + name)
            event = decode(raw)
            required = {
                "schema_version",
                "transaction_id",
                "revision",
                "phase",
                "root",
                "review",
                "operation",
                "observed_at",
                "previous_sha256",
            }
            if (
                set(event) != required
                or type(event["schema_version"]) is not int
                or event["schema_version"] != 1
                or type(event["revision"]) is not int
                or event["revision"] != revision
                or event["root"] != self.identity
                or event["previous_sha256"] != previous
                or event["phase"] not in TRANSITIONS
            ):
                fail("UNKNOWN", "Invalid transaction event identity or chain")
            if str(uuid.UUID(event["transaction_id"])) != event["transaction_id"]:
                fail("UNKNOWN", "Invalid transaction identifier")
            review = event["review"]
            if (
                not isinstance(review, dict)
                or set(review)
                != {
                    "source_commit",
                    "package_sha256",
                    "target",
                    "inventory_sha256",
                    "desired_target",
                }
                or not isinstance(review["source_commit"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", review["source_commit"])
                or not isinstance(review["package_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", review["package_sha256"])
                or not isinstance(review["target"], dict)
                or not review["target"]
                or (
                    review["desired_target"] is not None
                    and not isinstance(review["desired_target"], dict)
                )
                or (
                    review["inventory_sha256"] is not None
                    and (
                        not isinstance(review["inventory_sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", review["inventory_sha256"])
                    )
                )
            ):
                fail("UNKNOWN", "Invalid immutable review identity")
            operation = event["operation"]
            if event["phase"] in {"prepared", "admitted", "refused"}:
                if operation is not None:
                    fail("UNKNOWN", "An effect-free phase contains an operation")
            elif (
                not isinstance(operation, dict)
                or set(operation)
                != {
                    "operation_id",
                    "kind",
                    "expected_before",
                    "desired",
                    "observed_after",
                    "dispatched",
                    "completion_evidence",
                }
                or str(uuid.UUID(operation["operation_id"])) != operation["operation_id"]
                or operation["kind"] not in {"conditional_provider", "isolated_stage"}
                or operation["dispatched"] is not True
                or not isinstance(operation["expected_before"], dict)
                or not isinstance(operation["desired"], dict)
            ):
                fail("UNKNOWN", "Invalid requested operation")
            if latest is None:
                if event["phase"] != "prepared" or event["operation"] is not None:
                    fail("UNKNOWN", "Transaction does not start with an effect-free review")
            elif (
                event["transaction_id"] != latest["transaction_id"]
                or event["review"] != latest["review"]
                or event["phase"] not in TRANSITIONS[latest["phase"]]
            ):
                fail("UNKNOWN", "Transaction transition or immutable review changed")
            if latest and latest["operation"] is not None:
                # Reconciliation may add observations; it cannot rewrite the
                # requested operation, its expected-before value or its desired value.
                for key in ("operation_id", "kind", "expected_before", "desired", "dispatched"):
                    if not event["operation"] or event["operation"].get(key) != latest[
                        "operation"
                    ].get(key):
                        fail("UNKNOWN", "Requested operation identity changed")
            previous, latest = hashlib.sha256(raw).hexdigest(), event
        _, raw_summary = read_metadata(self.root, ".activation/summary.json")
        summary = decode(raw_summary)
        if summary != {
            "transaction_id": latest["transaction_id"],
            "revision": latest["revision"],
            "event_sha256": previous,
        }:
            fail("UNKNOWN", "Event/summary disagreement is preserved; no replay or repair")
        return latest, previous

    def _append(self, current, previous_hash, phase, operation=None):
        if current and current["revision"] > 0 and phase not in TRANSITIONS[current["phase"]]:
            fail("REFUSED", "This transaction cannot advance from its current phase")
        revision = current["revision"] + 1 if current else 1
        if revision > MAX_EVENTS:
            fail("LIMIT", "Transaction event limit reached; history was preserved")
        event = {
            **current,
            "revision": revision,
            "phase": phase,
            "operation": operation,
            "observed_at": utc_now(),
            "previous_sha256": previous_hash,
        }
        path = self.directory / f"event-{revision:04d}.json"
        _exclusive_json(path, event)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        atomic_json(
            self.directory / "summary.json",
            {
                "transaction_id": event["transaction_id"],
                "revision": revision,
                "event_sha256": digest,
            },
        )
        observed, _ = self._read()
        if observed != event:
            fail("UNKNOWN", "Transaction publication did not match readback")
        return event

    @classmethod
    def create(
        cls,
        root,
        *,
        source_commit,
        package_sha256,
        target,
        inventory_sha256=None,
        desired_target=None,
    ):
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit) or not re.fullmatch(
            r"[0-9a-f]{64}", package_sha256
        ):
            fail("INVALID", "A frozen source and package digest are required")
        if inventory_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", inventory_sha256):
            fail("INVALID", "Invalid reviewed inventory digest")
        if not isinstance(target, dict) or not target:
            fail("INVALID", "The complete reviewed target identity is required")
        canonical(target)
        if desired_target is not None:
            if not isinstance(desired_target, dict) or not desired_target:
                fail("INVALID", "The reviewed desired target must be a complete identity")
            canonical(desired_target)
        journal = cls(root)
        with coordination(root):
            # Exclusive directory creation also refuses partial or prior transactions.
            journal.directory.mkdir(mode=0o700)
            current = {
                "schema_version": 1,
                "transaction_id": str(uuid.uuid4()),
                "revision": 0,
                "phase": "prepared",
                "root": journal.identity,
                "review": {
                    "source_commit": source_commit,
                    "package_sha256": package_sha256,
                    "target": target,
                    "inventory_sha256": inventory_sha256,
                    "desired_target": desired_target,
                },
                "operation": None,
            }
            journal._append(current, None, "prepared")
        return journal

    def read(self):
        with coordination(self.root):
            return self._read()[0]

    def admit(self, provider=None, limits=DEFAULT_LIMITS):
        provider = provider or CodexReadOnlyProvider()
        with coordination(self.root) as identity:
            current, previous = self._read()
            if current["phase"] != "prepared":
                fail("REFUSED", "A transaction may not repeat its initial admission")
            observed = admitted_snapshot(self.root, identity, provider, limits)
            self._append(current, previous, "admitted")
            return observed

    def request_change(self, provider, expected_before, desired, *, limits=DEFAULT_LIMITS):
        # Capability check precedes any journal write or provider effect. The
        # production Codex provider has no conditional operation implementation.
        if provider.atomic_conditional is not True or isinstance(provider, CodexReadOnlyProvider):
            fail(
                "CONDITIONAL_UNAVAILABLE", "Existing host/profile/shortcut changes are unsupported"
            )
        with coordination(self.root) as identity:
            current, previous = self._read()
            if current["phase"] != "admitted" or current["operation"] is not None:
                fail("REFUSED", "An operation may be requested only once")
            admitted_snapshot(self.root, identity, provider, limits)
            observed = provider.read_target()
            if current["review"]["desired_target"] != desired:
                fail("CONFLICT", "Desired target differs from the frozen review")
            if observed != expected_before or current["review"]["target"] != expected_before:
                fail("CONFLICT", "The full target identity changed before dispatch")
            operation = {
                "operation_id": str(uuid.uuid4()),
                "kind": "conditional_provider",
                "expected_before": expected_before,
                "desired": desired,
                "observed_after": None,
                "dispatched": True,
                "completion_evidence": None,
            }
            current = self._append(current, previous, "mutation_requested", operation)
            try:
                receipt = provider.change(expected_before, desired, operation["operation_id"])
                observed = provider.read_target()
            except (OSError, TimeoutError, ValueError):
                latest, tip = self._read()
                return self._append(latest, tip, "unknown", operation)
            operation = {**operation, "observed_after": observed, "completion_evidence": receipt}
            confirmed = (
                isinstance(receipt, dict)
                and receipt.get("operation_id") == operation["operation_id"]
                and receipt.get("conditional_match") is True
                and receipt.get("revision") is not None
            )
            phase = (
                "mutation_observed"
                if observed == desired and confirmed
                else "conflict"
                if observed not in (expected_before, desired)
                else "unknown"
            )
            latest, tip = self._read()
            return self._append(latest, tip, phase, operation)

    def reconcile(self, observed):
        """Record readback of the same operation; do not call a provider or retry."""
        canonical(observed)
        with coordination(self.root):
            current, tip = self._read()
            operation = current["operation"]
            if (
                current["phase"] not in {"mutation_requested", "stage_requested", "unknown"}
                or not operation
            ):
                fail("REFUSED", "No unresolved requested operation can be reconciled here")
            operation = {**operation, "observed_after": observed}
            phase = (
                "unknown"
                if observed in (operation["expected_before"], operation["desired"])
                else "conflict"
            )
            return self._append(current, tip, phase, operation)


_STAGING_SCOPES = {}


@dataclass(frozen=True)
class IsolatedStageScope:
    root: Path
    identity: dict
    _key: object


def create_isolated_stage_scope(parent=None):
    """Create a fresh disposable test root; never bless an existing installation.

    No cleanup is automatic: interrupted stage contents remain available for
    assertions/review until the separately owned test fixture is removed.
    """
    parent = Path(parent or tempfile.gettempdir())
    parent_identity = root_identity(parent)
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if not parent.is_relative_to(temporary_root):
        fail(
            "REFUSED",
            "Isolated staging roots must be newly created under the OS temporary directory",
        )
    root = Path(tempfile.mkdtemp(prefix="matlab-p2-isolated-", dir=parent))
    if root_identity(parent) != parent_identity:
        fail("ALIAS", "Temporary parent changed during exclusive root creation")
    identity = root_identity(root)
    token = object()
    _STAGING_SCOPES[token] = dict(identity)
    return IsolatedStageScope(root, identity, token)


def _package_inventory(source, records):
    root_identity(source)
    if not isinstance(records, list) or not 1 <= len(records) <= 10_000:
        fail("LIMIT", "Invalid package file inventory")
    names = [row["path"] for row in records]
    if len({name.casefold() for name in names}) != len(names):
        fail("INVALID", "Duplicate or case-colliding package file")
    expected = {}
    total = 0
    for row in records:
        if (
            set(row) != {"path", "size_bytes", "sha256"}
            or type(row["size_bytes"]) is not int
            or row["size_bytes"] < 0
        ):
            fail("INVALID", "Invalid package record")
        total += row["size_bytes"]
        if row["size_bytes"] > 512 * 1024 * 1024 or total > 2 * 1024 * 1024 * 1024:
            fail("LIMIT", "Package exceeds the isolated stage byte bound")
        path = checked_path(source, row["path"])
        digest = _bounded_file_digest(path, row["size_bytes"])
        if path.stat().st_size != row["size_bytes"] or digest != row["sha256"]:
            fail("CHANGED", "Package bytes changed")
        expected[row["path"]] = row
    actual = set()
    seen = 0
    deadline = time.monotonic() + 10
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in [*dirs, *files]:
            seen += 1
            if seen > 20_000 or time.monotonic() >= deadline:
                fail("LIMIT", "Package tree exceeds its entry/time bound")
            _ordinary((Path(directory) / name).lstat())
        for name in files:
            actual.add((Path(directory) / name).relative_to(source).as_posix())
            if len(actual) > len(expected):
                fail("INVALID", "Unlisted package file")
    if actual != set(expected):
        fail("INVALID", "Missing or unlisted package file")
    return expected


def _bounded_file_digest(path, size):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        remaining = size
        while block := stream.read(min(1024 * 1024, remaining + 1)):
            remaining -= len(block)
            if remaining < 0:
                fail("CHANGED", "File grew past its reviewed size")
            digest.update(block)
    if remaining:
        fail("CHANGED", "File is shorter than its reviewed size")
    return digest.hexdigest()


def _copy_file(source, target, expected):
    digest = hashlib.sha256()
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        remaining = expected["size_bytes"]
        while block := incoming.read(min(1024 * 1024, remaining + 1)):
            remaining -= len(block)
            if remaining < 0:
                fail("UNKNOWN", "Source grew during stage copy")
            digest.update(block)
            outgoing.write(block)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if target.stat().st_size != expected["size_bytes"] or digest.hexdigest() != expected["sha256"]:
        fail("UNKNOWN", "Stage copy did not match expected bytes")


def stage_isolated(scope, journal, source, records, provider, *, limits=DEFAULT_LIMITS):
    if (
        not isinstance(scope, IsolatedStageScope)
        or _STAGING_SCOPES.get(scope._key) != scope.identity
        or scope.root != journal.root
        or root_identity(scope.root) != scope.identity
    ):
        fail("REFUSED", "Staging requires a newly issued isolated test-root capability")
    source = Path(source)
    expected = _package_inventory(source, records)
    with coordination(journal.root) as identity:
        current, tip = journal._read()
        if current["phase"] != "admitted" or current["operation"] is not None:
            fail("REFUSED", "Staging may be requested only once")
        admitted_snapshot(journal.root, identity, provider, limits)
        if current["review"]["inventory_sha256"] != fingerprint(records):
            fail("CONFLICT", "Package inventory does not match the frozen review")
        destination = checked_path(journal.root, "candidate", absent=True)
        if destination.exists():
            fail("CONFLICT", "Existing stage destination was preserved")
        desired = {
            "presence": True,
            "path": "candidate",
            "inventory_sha256": fingerprint(records),
            "source_commit": current["review"]["source_commit"],
            "package_sha256": current["review"]["package_sha256"],
        }
        operation = {
            "operation_id": str(uuid.uuid4()),
            "kind": "isolated_stage",
            "expected_before": {"presence": False, "path": "candidate"},
            "desired": desired,
            "observed_after": None,
            "dispatched": True,
            "completion_evidence": None,
        }
        journal._append(current, tip, "stage_requested", operation)
        try:
            destination.mkdir(mode=0o700)
            for relative, row in expected.items():
                target = checked_path(destination, relative, absent=True)
                target.parent.mkdir(parents=True, exist_ok=True)
                _copy_file(checked_path(source, relative), target, row)
            _package_inventory(destination, records)
            operation = {
                **operation,
                "observed_after": desired,
                "completion_evidence": {
                    "operation_id": operation["operation_id"],
                    "exclusive_create": True,
                },
            }
            phase = "staged_verified"
        except (OSError, ValueError):
            phase = "unknown"
        current, tip = journal._read()
        return journal._append(current, tip, phase, operation)
