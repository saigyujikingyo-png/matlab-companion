"""Build a relocatable preview from a local CPython and hash-locked dependencies."""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import time
import zipfile
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
    if any(
        not p.name.startswith("pip-") for p in (base / "Lib" / "site-packages").glob("*.dist-info")
    ):
        raise SystemExit("Base CPython contains installed packages; use a clean managed runtime")
    version = "0.1.0a1"
    staging = repo / "dist" / f"bundle-{time.time_ns()}"
    bundle = staging / f"MATLAB-Companion-{version}-windows-x64"
    bundle.mkdir(parents=True)
    runtime = bundle / "runtime"
    shutil.copytree(
        base, runtime, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages")
    )
    run("uv", "build", "--wheel", "--out-dir", str(staging))
    requirements = staging / "requirements.txt"
    run(
        "uv",
        "export",
        "--locked",
        "--no-dev",
        "--no-emit-project",
        "--no-header",
        "--quiet",
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
    # uv generates absolute-interpreter console launchers. The bundle uses -m
    # entrypoints, so exclude these non-relocatable auxiliary executables.
    generated_bin = target / "bin"
    removed = set()
    if generated_bin.is_dir():
        for launcher in generated_bin.iterdir():
            if launcher.is_file():
                removed.add(launcher.relative_to(target).as_posix())
                launcher.unlink()
    for record_path in target.glob("*.dist-info/RECORD"):
        with record_path.open(newline="", encoding="utf-8") as stream:
            records = [
                row for row in csv.reader(stream) if row[0].replace("\\", "/") not in removed
            ]
        with record_path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(records)
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
    for name in (
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "AGENTS.md",
        "DEVELOPMENT_PRINCIPLES.md",
    ):
        shutil.copy2(repo / name, bundle / name)
    shutil.copytree(repo / "docs", bundle / "docs")
    shutil.copytree(
        repo / "verification", bundle / "verification", ignore=shutil.ignore_patterns("private")
    )
    # Local wheel provenance would expose a developer-only file URL in the public package.
    for metadata in target.glob("matlab_companion-*.dist-info/direct_url.json"):
        metadata.unlink()
        record_path = metadata.parent / "RECORD"
        with record_path.open(newline="", encoding="utf-8") as stream:
            records = [row for row in csv.reader(stream) if not row[0].endswith("/direct_url.json")]
        with record_path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(records)
    shutil.copy2(requirements, bundle / "requirements.txt")
    native = target / "matlab_companion" / "matlab" / "+companion" / "execute.m"
    assert native.is_file()
    run(
        str(runtime / "python.exe"),
        "-I",
        "-B",
        "-c",
        "import tkinter,matlab_companion.setup_ui; print('Packaged UI imports passed')",
    )
    run(
        str(runtime / "python.exe"),
        "-I",
        "-B",
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
    archive = staging / (bundle.name + ".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for member in [f["path"] for f in files] + ["bundle-manifest.json"]:
            output.write(bundle / member, bundle.name + "/" + member)
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
