"""Build a relocatable preview from a local CPython and hash-locked dependencies."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from matlab_companion.storage import digest


def run(*args):
    subprocess.run(args, check=True)


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Build on Windows x64 with the managed CPython 3.12 runtime")
    repo = Path(__file__).resolve().parents[1]
    base = Path(sys.base_prefix)
    # A clean runtime is required; never copy the developer virtualenv or installed packages.
    if any((base / "Lib" / "site-packages").glob("*.dist-info")):
        raise SystemExit("Base CPython contains installed packages; use a clean managed runtime")
    version = "0.1.0a1"
    staging = repo / "dist" / f"bundle-{time.time_ns()}"
    bundle = staging / f"MATLAB-Companion-{version}-windows-x64"
    bundle.mkdir(parents=True)
    runtime = bundle / "runtime"
    shutil.copytree(base, runtime, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    run("uv", "build", "--wheel", "--out-dir", str(staging))
    requirements = staging / "requirements.txt"
    run(
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--output-file",
        str(requirements),
    )
    target = runtime / "Lib" / "site-packages"
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime / "python.exe"),
        "--target",
        str(target),
        "--require-hashes",
        "--only-binary",
        ":all:",
        "-r",
        str(requirements),
    )
    wheel = next(staging.glob("*.whl"))
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime / "python.exe"),
        "--target",
        str(target),
        "--no-deps",
        str(wheel),
    )
    # No Python file association or PATH changes are needed by end users.
    (bundle / "Start Setup.vbs").write_text(
        'Set shell = CreateObject("WScript.Shell")\n'
        'Set fs = CreateObject("Scripting.FileSystemObject")\n'
        "base = fs.GetParentFolderName(WScript.ScriptFullName)\n"
        'shell.Run Chr(34) & base & "\\runtime\\pythonw.exe" & Chr(34) & '
        '" -I -m matlab_companion setup", 1, False\n',
        encoding="utf-8",
    )
    (bundle / "Run Self Test.cmd").write_text(
        '@echo off\r\n"%~dp0runtime\\python.exe" -I -m matlab_companion self-test\r\npause\r\n',
        encoding="utf-8",
    )
    for name in ("README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(repo / name, bundle / name)
    shutil.copytree(repo / "docs", bundle / "docs")
    shutil.copy2(requirements, bundle / "requirements.txt")
    native = target / "matlab_companion" / "matlab" / "+companion" / "execute.m"
    assert native.is_file()
    run(
        str(runtime / "python.exe"),
        "-I",
        "-c",
        "import tkinter,matlab_companion.setup_ui; print('Packaged UI imports passed')",
    )
    run(
        str(runtime / "python.exe"),
        "-I",
        "-m",
        "matlab_companion",
        "self-test",
        "--root",
        str(staging / "isolated-self-test"),
    )
    files = [
        {
            "path": p.relative_to(bundle).as_posix(),
            "size_bytes": p.stat().st_size,
            "sha256": digest(p),
        }
        for p in sorted(bundle.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]
    manifest = {
        "version": version,
        "python": sys.version.split()[0],
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "files": files,
    }
    (bundle / "bundle-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    archive = Path(shutil.make_archive(str(staging / bundle.name), "zip", staging, bundle.name))
    (archive.with_suffix(".sha256")).write_text(
        f"{digest(archive)}  {archive.name}\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "archive": str(archive),
                "size_bytes": archive.stat().st_size,
                "sha256": digest(archive),
                "expanded_bytes": sum(f["size_bytes"] for f in files),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
