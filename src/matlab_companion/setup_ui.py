"""Ordinary-user setup with testable persistence and official CLI boundaries.

Importing this module never imports Tk, starts MATLAB or edits host configuration.
The graphical actions explicitly invoke the corresponding bounded operations.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from . import backend
from .diagnostics import passive_status, resolve_root
from .storage import atomic_json, default_root, digest, file_lock, read_json, utc_now

SERVER_NAME = "matlab-companion"


class SetupError(Exception):
    """An actionable setup failure whose message is suitable for the local UI."""


def load_settings(root: Path | None = None) -> dict:
    path = (root or default_root()) / "settings.json"
    if not path.exists():
        return {}
    try:
        settings = read_json(path)
        if not isinstance(settings, dict):
            raise TypeError("Settings must be an object")
        for name in ("allowed_roots", "output_roots"):
            if name in settings and (
                not isinstance(settings[name], list)
                or any(not isinstance(item, str) for item in settings[name])
            ):
                raise ValueError(f"{name} must be a list of paths")
        if "matlab_root" in settings and not isinstance(settings["matlab_root"], str):
            raise ValueError("matlab_root must be a path")
        return settings
    except (OSError, ValueError, TypeError) as error:
        raise SetupError(
            f"Existing settings could not be read. They were preserved at {path}."
        ) from error


def _directory(value: str | Path, label: str) -> Path:
    if not str(value).strip() or any(char in str(value) for char in ("\x00", "\r", "\n")):
        raise SetupError(f"Choose an existing {label} folder.")
    path = Path(value).expanduser().resolve()
    if not path.is_dir():
        raise SetupError(f"The selected {label} folder does not exist: {path}")
    return path


def _matlab_directory(value: str | Path) -> Path:
    path = _directory(value, "MATLAB installation")
    executable = path / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")
    if not executable.is_file():
        raise SetupError(
            "Choose the MATLAB installation folder containing bin/matlab, such as R2025b."
        )
    return path


def _append_root(existing: list[str], selected: Path) -> list[str]:
    result = list(existing)
    normalised = {os.path.normcase(str(Path(item).expanduser().resolve())) for item in existing}
    if os.path.normcase(str(selected)) not in normalised:
        result.append(str(selected))
    return result


def save_settings(
    root: Path,
    input_folder: str | Path,
    output_folder: str | Path,
    matlab_folder: str | Path,
) -> dict:
    """Add selected folder authorisations, preserving other adapters and values."""
    inputs = _directory(input_folder, "input")
    outputs = _directory(output_folder, "output")
    matlab = _matlab_directory(matlab_folder)
    root = root.resolve()
    with file_lock(root / ".settings.lock", timeout=5):
        existing = load_settings(root)
        updated = copy.deepcopy(existing)
        updated["allowed_roots"] = _append_root(existing.get("allowed_roots", []), inputs)
        updated["output_roots"] = _append_root(existing.get("output_roots", []), outputs)
        updated["matlab_root"] = str(matlab)
        if updated != existing:
            if (root / "settings.json").is_file():
                backup = root / "setup-recovery" / f"settings-{uuid.uuid4().hex}.json"
                atomic_json(backup, existing)
            atomic_json(root / "settings.json", updated)
        return updated


def runtime_python_path() -> Path:
    """Use the installation's interpreter, including a console peer of pythonw."""
    executable = Path(sys.executable).resolve()
    if executable.name.lower() == "pythonw.exe":
        console = executable.with_name("python.exe")
        if console.is_file():
            return console
    return executable


def _codex_command(explicit: str | None) -> str:
    command = explicit or shutil.which("codex.exe" if os.name == "nt" else "codex")
    if not command and os.name == "nt":
        # The Windows desktop app supplies its CLI in its official local bin
        # directory without necessarily adding it to Explorer's inherited PATH.
        local = os.environ.get("LOCALAPPDATA")
        if local:
            installed = Path(local) / "OpenAI" / "Codex" / "bin"
            candidates = [p for p in installed.glob("*/codex.exe") if p.is_file()]
            if candidates:
                command = str(max(candidates, key=lambda p: p.stat().st_mtime_ns))
    if not command:
        raise SetupError(
            "Codex CLI was not found. Install Codex or make its official executable available, then reopen setup."
        )
    if Path(command).suffix.lower() in (".cmd", ".bat"):
        raise SetupError(
            "Select the official Codex executable; command-shell wrappers are not supported by this setup preview."
        )
    return command


def _invoke(command: list[str], runner: Callable) -> subprocess.CompletedProcess:
    try:
        return runner(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise SetupError(
            "Codex did not return a confirmed result. Check the existing connection before trying again."
        ) from error


def _codex_entries(command: str, runner: Callable) -> list[dict]:
    result = _invoke([command, "mcp", "list", "--json"], runner)
    if result.returncode != 0:
        raise SetupError(
            "Codex connections could not be read; setup preserved the existing host configuration."
        )
    try:
        entries = json.loads(result.stdout)
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or not isinstance(entry.get("name"), str)
            for entry in entries
        ):
            raise ValueError("Unexpected Codex result")
        return entries
    except (ValueError, TypeError) as error:
        raise SetupError(
            "Codex returned an unsupported connection format. No connection was changed."
        ) from error


def _selected_entry(entries: list[dict]) -> dict | None:
    matches = [entry for entry in entries if entry.get("name") == SERVER_NAME]
    if len(matches) > 1:
        raise SetupError(
            "Multiple MATLAB Companion connections were reported; preserve and review them in Codex."
        )
    return matches[0] if matches else None


def _matches(entry: dict, expected: dict) -> bool:
    transport = entry.get("transport", {})
    if not isinstance(transport, dict):
        return False
    return (
        transport.get("type") == "stdio"
        and os.path.normcase(str(transport.get("command", "")))
        == os.path.normcase(expected["command"])
        and transport.get("args", []) == expected["args"]
        and not transport.get("env")
        and not transport.get("env_vars")
        and not transport.get("cwd")
        and entry.get("enabled", True) is True
    )


def _display_entry(entry: dict) -> dict:
    """Display identity without copying connection environment or secrets."""
    transport = entry.get("transport", {})
    return {
        "name": SERVER_NAME,
        "transport": transport.get("type", "unknown") if isinstance(transport, dict) else "unknown",
        "command": transport.get("command") if isinstance(transport, dict) else None,
        "enabled": entry.get("enabled", True),
    }


def _entry_fingerprint(entry: dict) -> str:
    serialized = json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def connect_codex(
    root: Path,
    *,
    runtime_python: Path | None = None,
    codex_command: str | None = None,
    runner: Callable = subprocess.run,
) -> dict:
    """Create only an absent named entry through the official Codex CLI."""
    executable = (runtime_python or runtime_python_path()).resolve()
    if not executable.is_file():
        raise SetupError(
            "The installation's Python runtime is missing. Repair this installation before connecting."
        )
    root = root.resolve()
    command = _codex_command(codex_command)
    expected = {
        "command": str(executable),
        "args": ["-I", "-m", "matlab_companion", "serve", "--root", str(root)],
    }
    record_path = root / "codex-connection.json"
    with file_lock(root / ".setup-codex.lock", timeout=5):
        entry = _selected_entry(_codex_entries(command, runner))
        if entry is not None:
            if _matches(entry, expected):
                return {
                    "state": "already_connected",
                    "message": "The same MATLAB Companion connection is already configured.",
                }
            return {
                "state": "conflict",
                "message": "An existing MATLAB Companion connection uses different settings. It was preserved; review it in Codex before replacing it.",
                "existing": _display_entry(entry),
            }
        if record_path.exists():
            previous = read_json(record_path)
            atomic_json(root / "setup-recovery" / f"codex-{uuid.uuid4().hex}.json", previous)
        record = {
            "server_name": SERVER_NAME,
            "created_by_setup": True,
            "state": "planned",
            "expected": expected,
            "previous_entry": None,
            "observed_at": utc_now(),
            "rollback": "Remove only this named entry if its current command, arguments and options still match this record.",
        }
        atomic_json(record_path, record)
        try:
            result = _invoke(
                [command, "mcp", "add", SERVER_NAME, "--", expected["command"], *expected["args"]],
                runner,
            )
            if result.returncode != 0:
                raise SetupError(
                    "Codex did not confirm the connection. The recovery record was retained; inspect the existing connection before trying again."
                )
            entry = _selected_entry(_codex_entries(command, runner))
            if entry is None or not _matches(entry, expected):
                raise SetupError(
                    "Codex connection readback did not match this installation. The recovery record was retained; no automatic retry or removal was attempted."
                )
        except SetupError:
            record.update(state="uncertain", observed_at=utc_now())
            atomic_json(record_path, record)
            raise
        record.update(
            state="connected", observed_at=utc_now(), entry_sha256=_entry_fingerprint(entry)
        )
        atomic_json(record_path, record)
        return {
            "state": "connected",
            "message": "Codex connection saved and read back. Open a new Codex task to check tool discovery; model and file-delivery acceptance remain separate.",
            "receipt": str(record_path),
        }


def rollback_codex(
    root: Path,
    *,
    codex_command: str | None = None,
    runner: Callable = subprocess.run,
) -> dict:
    root = root.resolve()
    command = _codex_command(codex_command)
    path = root / "codex-connection.json"
    with file_lock(root / ".setup-codex.lock", timeout=5):
        if not path.is_file():
            raise SetupError("This setup has no owned Codex connection to remove.")
        record = read_json(path)
        if record.get("created_by_setup") is not True or not isinstance(
            record.get("expected"), dict
        ):
            raise SetupError("The recovery record does not authorise removing this connection.")
        entry = _selected_entry(_codex_entries(command, runner))
        if entry is None:
            return {
                "state": "already_removed",
                "message": "The named Codex connection is already absent.",
            }
        if not _matches(entry, record["expected"]) or _entry_fingerprint(entry) != record.get(
            "entry_sha256"
        ):
            raise SetupError(
                "The Codex connection has changed since setup. It was preserved; review it in Codex."
            )
        result = _invoke([command, "mcp", "remove", SERVER_NAME], runner)
        if result.returncode != 0 or _selected_entry(_codex_entries(command, runner)) is not None:
            raise SetupError(
                "Codex did not confirm removal. Inspect the existing connection before trying again."
            )
        record.update(state="removed", observed_at=utc_now())
        atomic_json(path, record)
        return {
            "state": "removed",
            "message": "Only this setup's unchanged MATLAB Companion connection was removed. Research files and other plugins were retained.",
        }


def quarantine_status(root: Path) -> dict:
    path = root / "executor-quarantine.json"
    if not path.is_file():
        return {"state": "clear", "job_id": None, "reason": None, "sha256": None}
    try:
        value = read_json(path)
        return {
            "state": "quarantined",
            "job_id": value.get("job_id"),
            "reason": value.get("reason"),
            "sha256": digest(path),
        }
    except (OSError, ValueError, AttributeError) as error:
        raise SetupError(
            "The executor recovery marker could not be read; it was preserved for review."
        ) from error


def clear_quarantine(root: Path, *, confirmed_stopped: bool, expected_sha256: str) -> dict:
    """Clear only the displayed marker after explicit user confirmation; never kill."""
    if confirmed_stopped is not True:
        raise SetupError(
            "First confirm that this job's owned MATLAB session has stopped. Setup does not stop MATLAB processes."
        )
    root = root.resolve()
    try:
        with file_lock(root / ".recovery.lock"), file_lock(root / ".execution.lock"):
            current = quarantine_status(root)
            if current["state"] == "clear":
                return {
                    "state": "already_clear",
                    "message": "There is no executor quarantine marker.",
                }
            if not expected_sha256 or current["sha256"] != expected_sha256:
                raise SetupError(
                    "The recovery marker changed. Refresh setup and review the new job before confirming again."
                )
            active_path = root / "executor-active.json"
            active = None
            active_sha256 = None
            if active_path.exists():
                try:
                    active_bytes = active_path.read_bytes()
                    active = json.loads(active_bytes.decode("utf-8-sig"))
                    active_sha256 = hashlib.sha256(active_bytes).hexdigest()
                except (OSError, ValueError) as error:
                    raise SetupError(
                        "The active executor marker could not be read. Both recovery markers were preserved."
                    ) from error
                if (
                    not isinstance(active, dict)
                    or not isinstance(active.get("job_id"), str)
                    or active["job_id"] != current["job_id"]
                ):
                    raise SetupError(
                        "The active executor marker identifies a different or unknown job. Both markers were preserved."
                    )
            record_path = root / "setup-recovery" / f"executor-{uuid.uuid4().hex}.json"
            atomic_json(
                record_path,
                {
                    "observed_at": utc_now(),
                    "user_confirmed_owned_session_stopped": True,
                    "previous_quarantine": current,
                    "previous_active_executor": active,
                    "active_executor_sha256": active_sha256,
                    "action": "clear_quarantine_only",
                },
            )
            target = root / "executor-quarantine.json"
            if digest(target) != expected_sha256:
                raise SetupError(
                    "The recovery marker changed while saving the receipt; it was preserved."
                )
            if active_sha256 is None:
                if active_path.exists():
                    raise SetupError(
                        "The active executor marker appeared while saving the receipt. Both markers were preserved."
                    )
            elif not active_path.is_file() or digest(active_path) != active_sha256:
                raise SetupError(
                    "The active executor marker changed while saving the receipt. Both markers were preserved."
                )
            else:
                # Keep quarantine blocking if removal fails after retiring the matching active marker.
                active_path.unlink()
            target.unlink()
            return {
                "state": "cleared",
                "message": "Executor quarantine cleared after your confirmation. Existing jobs and artifacts are unchanged; reconcile the original job before repeating work.",
                "receipt": str(record_path),
            }
    except (TimeoutError, PermissionError) as error:
        raise SetupError(
            "The executor or recovery coordinator is still busy. Its quarantine marker was preserved."
        ) from error


def start_job_service(root: Path) -> dict:
    """Explicit user action for hosts that cannot launch an independent child."""
    from .client import CoordinatorClient
    from .core import WorkflowError

    try:
        record = CoordinatorClient(root, idle_seconds=300)._ensure()
    except WorkflowError as error:
        raise SetupError(error.message) from error
    return {
        "state": "ready",
        "message": f"Job service is ready. Return to your agent and use the original job or idempotency key. The service exits after {record['idle_seconds']:g} idle seconds. Accepted queued work may resume; dispatched work is never replayed.",
    }


def setup_status(root: Path) -> dict:
    """Passive checks only: do not construct Core, which can resume queued jobs."""
    settings = load_settings(root)
    installation = backend.matlab_root(root)
    installed = installation is not None
    try:
        binary = backend.backend_path(root)
        _, expected = backend.ASSETS[(backend.platform.system(), backend.platform.machine())]
        verified_backend = binary.is_file() and digest(binary) == expected
    except (KeyError, OSError):
        verified_backend = False
    return {
        "status": passive_status(root),
        "backend_verified": verified_backend,
        "matlab_installation_found": installed,
        "native_execution": "unverified",
        "licence": "unverified",
        "host_delivery": "unverified",
        "input_folders": len(settings.get("allowed_roots", [])),
        "output_folders": len(settings.get("output_roots", [])),
        "quarantine": quarantine_status(root),
    }


class SetupWindow:
    def __init__(self, root: Path | None = None):
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.root = resolve_root(root)
        self.window = tk.Tk()
        self.window.title("MATLAB Companion setup")
        self.window.geometry("850x700")
        self.window.minsize(690, 560)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.buttons = []
        self.quarantine = {"sha256": None}
        self.input_folder = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.matlab_folder = tk.StringVar()
        self.confirm_stopped = tk.BooleanVar(value=False)
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        ttk.Label(frame, text="MATLAB Companion", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        source_checkout = Path(__file__).resolve().parents[2] / "pyproject.toml"
        mode = (
            "Development installation: keep this checkout and its environment in place."
            if source_checkout.is_file()
            else "Keep this installation folder in place after connecting your agent."
        )
        ttk.Label(frame, text=mode, wraplength=760).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 14)
        )
        fields = (
            ("Input folder", self.input_folder),
            ("Output folder", self.output_folder),
            ("MATLAB installation", self.matlab_folder),
        )
        for row, (label, variable) in enumerate(fields, start=2):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
            ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", padx=8)

            def browse(var=variable, title=label):
                selected = filedialog.askdirectory(
                    parent=self.window,
                    title=f"Choose {title.lower()}",
                    initialdir=var.get() or str(Path.home()),
                    mustexist=True,
                )
                if selected:
                    var.set(selected)

            ttk.Button(frame, text="Browse…", command=browse).grid(row=row, column=2)
        ttk.Label(
            frame,
            text="Existing authorised folders and other plugin settings are retained. MATLAB and its licence are supplied separately.",
            wraplength=760,
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(5, 12))
        actions = ttk.Frame(frame)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew")
        for label, callback in (
            ("Save folders", self._save),
            ("Install / verify backend", self._install),
            ("Check setup", self._check),
            ("Save and connect Codex", self._connect),
            ("Undo this Codex connection", self._undo),
        ):
            button = ttk.Button(actions, text=label, command=callback)
            button.pack(side="left", padx=(0, 5), pady=4)
            self.buttons.append(button)
        ttk.Label(
            frame,
            text="Check setup is passive: it does not launch MATLAB or verify a licence, native result or agent delivery.",
            wraplength=560,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(5, 12))
        service_button = ttk.Button(frame, text="Start job service", command=self._service)
        service_button.grid(row=7, column=2, sticky="e", pady=(5, 12))
        self.buttons.append(service_button)
        recovery = ttk.LabelFrame(frame, text="Executor recovery", padding=10)
        recovery.grid(row=8, column=0, columnspan=3, sticky="ew")
        self.recovery_label = ttk.Label(
            recovery, text="Checking saved recovery state…", wraplength=740
        )
        self.recovery_label.pack(anchor="w")
        ttk.Checkbutton(
            recovery,
            text="I verified that the displayed job's owned MATLAB session has stopped.",
            variable=self.confirm_stopped,
        ).pack(anchor="w", pady=6)
        recover_button = ttk.Button(
            recovery, text="Clear this executor quarantine", command=self._recover
        )
        recover_button.pack(anchor="w")
        self.buttons.append(recover_button)
        self.output = tk.Text(frame, height=13, wrap="word", state="disabled")
        self.output.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(12, 0))
        frame.rowconfigure(9, weight=1)
        self._load_fields()
        self.window.after(100, self._poll)
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)

    def _log(self, text: str):
        self.output.configure(state="normal")
        self.output.insert("end", text + "\n\n")
        self.output.see("end")
        self.output.configure(state="disabled")

    def _load_fields(self):
        try:
            settings = load_settings(self.root)
            for key, variable in (
                ("allowed_roots", self.input_folder),
                ("output_roots", self.output_folder),
            ):
                value = next((item for item in settings.get(key, []) if Path(item).is_dir()), "")
                variable.set(value)
            selected = backend.matlab_root(self.root)
            self.matlab_folder.set(str(selected) if selected else "")
            self._refresh_recovery()
            self._log(
                "Choose your folders, save them, then install or verify the official MATLAB backend. Connect Codex when ready."
            )
        except SetupError as error:
            self._log(str(error))

    def _refresh_recovery(self):
        self.quarantine = quarantine_status(self.root)
        self.confirm_stopped.set(False)
        if self.quarantine["state"] == "clear":
            self.recovery_label.configure(
                text="No executor quarantine marker. Setup never stops MATLAB processes."
            )
        else:
            self.recovery_label.configure(
                text=f"Job: {self.quarantine['job_id']}\n{self.quarantine['reason']}\nVerify that only this job's owned MATLAB session has stopped before clearing this marker. Existing jobs are retained."
            )

    def _start(self, label: str, action: Callable):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state="disabled")
        self._log(label)

        def worker():
            try:
                self.events.put((True, action()))
            except Exception as error:  # noqa: BLE001 - restore the GUI after any worker failure.
                message = (
                    str(error)
                    if isinstance(error, SetupError)
                    else f"The operation could not finish ({type(error).__name__}). Existing settings and recovery records were retained."
                )
                self.events.put((False, {"message": message}))

        threading.Thread(target=worker, name="matlab-companion-setup", daemon=True).start()

    def _poll(self):
        try:
            _success, result = self.events.get_nowait()
            self.busy = False
            for button in self.buttons:
                button.configure(state="normal")
            self._log(result.get("message", "Finished."))
            if result.get("existing"):
                entry = result["existing"]
                self._log(
                    f"Existing connection: {entry['name']} ({entry['transport']}); command: {entry['command'] or 'remote connection'}. Its values were preserved."
                )
            try:
                self._refresh_recovery()
            except SetupError as error:
                self._log(str(error))
        except queue.Empty:
            pass
        self.window.after(100, self._poll)

    def _selected_folders(self):
        return self.input_folder.get(), self.output_folder.get(), self.matlab_folder.get()

    def _save(self):
        selected = self._selected_folders()

        def save():
            save_settings(self.root, *selected)
            return {
                "message": "Selected folders saved. Existing authorisations and unrelated settings were retained."
            }

        self._start("Saving selected folders…", save)

    def _install(self):
        def install():
            backend.install_backend(self.root)
            return {
                "message": "Official MATLAB MCP backend downloaded or reused and verified against the pinned SHA-256. MATLAB execution and its licence still need separate acceptance."
            }

        self._start("Installing or verifying the official backend…", install)

    def _check(self):
        def check():
            status = setup_status(self.root)
            return {
                "message": f"Backend checksum: {'verified' if status['backend_verified'] else 'not verified'}. MATLAB installation: {'found' if status['matlab_installation_found'] else 'not selected or not found'}. Saved folders: {status['input_folders']} input, {status['output_folders']} output. Native execution, licence and host delivery remain unverified by this passive check."
            }

        self._start("Checking saved settings without launching MATLAB…", check)

    def _connect(self):
        selected = self._selected_folders()

        def connect():
            save_settings(self.root, *selected)
            return connect_codex(self.root)

        self._start("Saving folders and connecting Codex through its official CLI…", connect)

    def _service(self):
        self._start(
            "Starting the independent job service; previously accepted queued work may resume…",
            lambda: start_job_service(self.root),
        )

    def _undo(self):
        self._start(
            "Checking the setup-owned Codex connection before removal…",
            lambda: rollback_codex(self.root),
        )

    def _recover(self):
        confirmed = self.confirm_stopped.get()
        fingerprint = self.quarantine.get("sha256")
        self._start(
            "Reviewing the displayed executor recovery marker…",
            lambda: clear_quarantine(
                self.root, confirmed_stopped=confirmed, expected_sha256=fingerprint
            ),
        )

    def run(self):
        self.window.mainloop()


def main(root: Path | None = None):
    try:
        window = SetupWindow(root)
    except ImportError as error:
        raise SetupError(
            "This development Python installation lacks Tk. Use a complete packaged runtime or install the development GUI dependency; it is not a one-click installation."
        ) from error
    window.run()


if __name__ == "__main__":
    main()
