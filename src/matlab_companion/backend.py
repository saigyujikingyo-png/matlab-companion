"""Pinned official MathWorks MCP subprocess adapter; no public evaluator."""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import shutil
import tempfile
import urllib.request
import uuid
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .storage import atomic_json, default_root, digest, read_json, utc_now

BACKEND_VERSION = "0.13.0"
ASSETS = {
    ("Windows", "AMD64"): (
        "matlab-mcp-server-windows-x64.exe",
        "4e065398cf86e9d1d4d3e30cec7faf6f16491ab08128da9a8336369166ad9917",
    ),
    ("Linux", "x86_64"): (
        "matlab-mcp-server-linux-x64",
        "07946705e488e9e13034bf1a08f6598e685bad30d5d78b93934cbe3002250704",
    ),
    ("Darwin", "arm64"): (
        "matlab-mcp-server-macos-arm64",
        "1c25441c23640d24b707466bf04032753129022b094ec9d770f2dbfde9527555",
    ),
    ("Darwin", "x86_64"): (
        "matlab-mcp-server-macos-x64",
        "11bcdeec8addb0a64a29da875b84aa613597483130ae494ca3993c7881f54f3f",
    ),
}


def backend_path(root: Path | None = None) -> Path:
    name, _ = ASSETS[(platform.system(), platform.machine())]
    return (root or default_root()) / "vendor" / BACKEND_VERSION / name


def install_backend(root: Path | None = None) -> Path:
    """Acquire only the official pinned asset and verify its published digest."""
    path = backend_path(root)
    name, expected = ASSETS[(platform.system(), platform.machine())]
    if path.is_file() and digest(path) == expected:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/matlab/matlab-mcp-server/releases/download/v{BACKEND_VERSION}/{name}"
    temporary = path.with_suffix(".download")
    with urllib.request.urlopen(url, timeout=60) as source, temporary.open("wb") as target:
        shutil.copyfileobj(source, target)
    if digest(temporary) != expected:
        temporary.unlink()
        raise ValueError("Official backend checksum did not match the pinned release")
    temporary.replace(path)
    path.chmod(0o755)
    licence_url = (
        f"https://raw.githubusercontent.com/matlab/matlab-mcp-server/v{BACKEND_VERSION}/LICENSE.md"
    )
    with urllib.request.urlopen(licence_url, timeout=30) as response:
        (path.parent / "LICENSE-MathWorks.md").write_bytes(response.read())
    atomic_json(
        path.parent / "source.json",
        {"version": BACKEND_VERSION, "url": url, "sha256": expected, "acquired_at": utc_now()},
    )
    return path


def matlab_root(settings_root: Path | None = None) -> Path | None:
    explicit = os.environ.get("MATLAB_COMPANION_MATLAB_ROOT")
    settings = (settings_root or default_root()) / "settings.json"
    if not explicit and settings.is_file():
        saved = read_json(settings)
        if not isinstance(saved, dict):
            raise ValueError("Installation settings must be an object")
        explicit = saved.get("matlab_root")
    if explicit:
        root = Path(explicit).expanduser().resolve()
        executable_name = "matlab.exe" if os.name == "nt" else "matlab"
        return root if (root / "bin" / executable_name).is_file() else None
    executable = shutil.which("matlab")
    if executable:
        return Path(executable).resolve().parent.parent
    if os.name == "nt":
        candidates = sorted(Path("C:/Program Files/MATLAB").glob("R20*"), reverse=True)
        if len(candidates) == 1:
            return candidates[0]
    return None


def native_code_root() -> Path:
    packaged = Path(__file__).parent / "matlab"
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "matlab"


def matlab_quote(path: Path) -> str:
    value = str(path.resolve()).replace("'", "''")
    if "\n" in value or "\r" in value:
        raise ValueError("Newlines are not allowed in an execution path")
    return "'" + value + "'"


def archive_backend_logs(short_logs: Path, job: Path) -> None:
    """Retain diagnostics and remove only the temporary directory created for this run."""
    resolved = short_logs.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if resolved.parent != temp_root or not resolved.name.startswith("mc-"):
        raise ValueError("Unexpected backend log directory")
    destination = job / "backend-logs"
    shutil.copytree(resolved, destination, symlinks=True)
    # Copy must succeed before deletion; resolved target is one owned direct temp child.
    shutil.rmtree(resolved)
    atomic_json(job / "backend-log-location.json", {"archived": "backend-logs"})


class OfficialBackend:
    def __init__(self, root: Path | None = None, timeout: float = 240):
        self.root = (root or default_root()).resolve()
        self.timeout = timeout

    def available(self) -> bool:
        try:
            return backend_path(self.root).is_file() and matlab_root(self.root) is not None
        except KeyError:  # No official asset for this platform; observation never installs it.
            return False

    async def execute(self, job: Path) -> None:
        binary = backend_path(self.root)
        installation = matlab_root(self.root)
        if not binary.is_file():
            raise FileNotFoundError("Install the official backend through MATLAB Companion setup")
        _, expected = ASSETS[(platform.system(), platform.machine())]
        if digest(binary) != expected:
            raise ValueError("Backend checksum mismatch; run setup to repair")
        if installation is None:
            raise FileNotFoundError("MATLAB was not found; select an installation in setup")
        session_id = str(uuid.uuid4())
        job_id = str(uuid.UUID(job.name))
        session_temporary = job / f"native-session-{session_id}.tmp"
        session_record = job / "native-session.json"
        launcher = job / "launch_companion.m"
        launcher.write_text(
            f"addpath({matlab_quote(native_code_root())});\n"
            # This observation identifies the MATLAB process; it never confirms a stop.
            "companion_session_pid = NaN;\n"
            "if exist('matlabProcessID', 'builtin') || exist('matlabProcessID', 'file')\n"
            "    companion_session_pid = matlabProcessID;\n"
            "end\n"
            "companion_session = struct('contract_version', '1.0', "
            f"'job_id', '{job_id}', 'session_id', '{session_id}', "
            "'matlab_pid', companion_session_pid);\n"
            "companion_session_bytes = unicode2native("
            "jsonencode(companion_session, 'ConvertInfAndNaN', true), 'UTF-8');\n"
            f"companion_session_file = fopen({matlab_quote(session_temporary)}, 'wb');\n"
            "if companion_session_file < 0\n"
            "    error('Companion:SESSION_IDENTITY_FAILED', 'Could not write session identity.');\n"
            "end\n"
            "try\n"
            "    companion_session_written = fwrite("
            "companion_session_file, companion_session_bytes, 'uint8');\n"
            "catch companion_session_error\n"
            "    fclose(companion_session_file);\n"
            "    rethrow(companion_session_error);\n"
            "end\n"
            "companion_session_closed = fclose(companion_session_file);\n"
            "if companion_session_written ~= numel(companion_session_bytes) "
            "|| companion_session_closed ~= 0\n"
            "    error('Companion:SESSION_IDENTITY_FAILED', 'Session identity write was incomplete.');\n"
            "end\n"
            f"if ~movefile({matlab_quote(session_temporary)}, {matlab_quote(session_record)}, 'f')\n"
            "    error('Companion:SESSION_IDENTITY_FAILED', 'Could not commit session identity.');\n"
            "end\n"
            f"companion.execute({matlab_quote(job / 'request.json')});\n",
            encoding="utf-8",
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper()
            in {
                "PATH",
                "WINDIR",
                "SYSTEMROOT",
                "SYSTEMDRIVE",
                "COMSPEC",
                "PATHEXT",
                "TEMP",
                "TMP",
                "USERPROFILE",
                "LOCALAPPDATA",
                "APPDATA",
                "HOME",
                "DISPLAY",
                "LANG",
                "LD_LIBRARY_PATH",
                "MLM_LICENSE_FILE",
                "LM_LICENSE_FILE",
            }
        }
        # Upstream creates a local socket below log-folder; long job paths exceed its socket limit.
        short_logs = Path(tempfile.mkdtemp(prefix="mc-"))
        atomic_json(job / "backend-log-location.json", {"path": str(short_logs)})
        parameters = StdioServerParameters(
            command=str(binary),
            args=[
                f"--matlab-root={installation}",
                "--matlab-session-mode=new",
                "--matlab-display-mode=nodesktop",
                f"--initial-working-folder={job}",
                "--disable-telemetry=true",
                f"--log-folder={short_logs}",
            ],
            env=environment,
        )
        # Request cancellation never means MATLAB computation has stopped. Core reconciles receipts.
        try:
            with (job / "backend-stderr.log").open("w", encoding="utf-8") as errors:
                async with (
                    stdio_client(parameters, errlog=errors) as (read, write),
                    ClientSession(read, write, read_timeout_seconds=self.timeout) as session,
                ):
                    await session.initialize()
                    result = await asyncio.wait_for(
                        session.call_tool("run_matlab_file", {"script_path": str(launcher)}),
                        timeout=self.timeout,
                    )
                    atomic_json(
                        job / "backend-result.json", result.model_dump(mode="json", by_alias=True)
                    )
                    if result.is_error and not (job / "receipt.json").exists():
                        raise RuntimeError(
                            "Official backend failed before producing a native receipt"
                        )
        finally:
            # An active or inaccessible upstream log is retained, never allowed to mask outcome.
            with contextlib.suppress(OSError):
                archive_backend_logs(short_logs, job)
