"""Build an unpublished Windows candidate from one clean committed snapshot."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import tomllib
import zipfile
from pathlib import Path

from bundle_support import (
    NORMATIVE_FILES,
    PASSIVE_BOOTSTRAP,
    capture_source,
    check_versions,
    copy_documents,
    copy_snapshot,
    privacy_findings,
    sha256,
    tree_manifest,
    validate_document_links,
    validate_public_bytes,
    vendor_documents,
    verify_manifest,
    verify_product_wheel,
    verify_snapshot_bytes,
    verify_source,
)


def run(*args, cwd=None, env=None):
    return subprocess.run(args, check=True, cwd=cwd, env=env)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise SystemExit("Build on Windows x64 with the managed CPython 3.12 runtime")
    repo = Path(__file__).resolve().parents[1]
    snapshot = capture_source(repo)  # Freeze S before a wheel or package exists.
    version = check_versions(repo)
    base = Path(sys.base_prefix)
    if any(
        not p.name.startswith("pip-") for p in (base / "Lib" / "site-packages").glob("*.dist-info")
    ):
        raise SystemExit("Base CPython contains installed packages; use a clean managed runtime")
    staging = repo / "dist" / f"bundle-{time.time_ns()}"
    staging.mkdir(parents=True, exist_ok=False)
    source = staging / "source"
    copy_snapshot(repo, source, snapshot)
    bundle = staging / f"MATLAB-Companion-{version}-windows-x64"
    bundle.mkdir()
    runtime = bundle / "runtime"
    shutil.copytree(
        base, runtime, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages")
    )
    runtime_files = tree_manifest(runtime)
    runtime_digest = hashlib.sha256(
        json.dumps(runtime_files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    uv_version = subprocess.check_output(["uv", "--version"], text=True).strip()

    # Resolve the declared build backend in a separate environment and retain
    # its exact installed versions. It is never copied into the product runtime.
    build_env = staging / "build-environment"
    run("uv", "venv", "--python", sys.executable, str(build_env), cwd=source)
    build_python = build_env / "Scripts" / "python.exe"
    build_requires = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))[
        "build-system"
    ]["requires"]
    run("uv", "pip", "install", "--python", str(build_python), *build_requires, "pip", cwd=source)
    build_versions = json.loads(
        subprocess.check_output(
            [
                str(build_python),
                "-I",
                "-B",
                "-c",
                (
                    "import importlib.metadata as m,json; print(json.dumps(sorted("
                    "[{'name': d.metadata['Name'], 'version': d.version} for d in m.distributions()],"
                    "key=lambda d:d['name'])))"
                ),
            ],
            text=True,
        )
    )
    run(
        "uv",
        "build",
        "--wheel",
        "--no-sources",
        "--no-build-isolation",
        "--python",
        str(build_python),
        "--out-dir",
        str(staging),
        str(source),
        cwd=source,
    )
    wheels = list(staging.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected one product wheel")
    wheel = wheels[0]
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
        cwd=source,
    )
    wheelhouse = staging / "dependency-wheels"
    wheelhouse.mkdir()
    run(
        str(build_python),
        "-I",
        "-B",
        "-m",
        "pip",
        "download",
        "--disable-pip-version-check",
        "--require-hashes",
        "--only-binary=:all:",
        "--dest",
        str(wheelhouse),
        "-r",
        str(requirements),
        cwd=source,
    )
    dependency_wheels = tree_manifest(wheelhouse)
    if not dependency_wheels or any(not row["path"].endswith(".whl") for row in dependency_wheels):
        raise ValueError("Hash-locked dependency download did not produce only wheels")
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
        "--no-index",
        "--find-links",
        str(wheelhouse),
        "--link-mode",
        "copy",
        "-r",
        str(requirements),
        cwd=source,
    )
    run(
        "uv",
        "pip",
        "install",
        "--python",
        str(runtime / "python.exe"),
        "--target",
        str(target),
        "--no-deps",
        "--link-mode",
        "copy",
        str(wheel),
        cwd=source,
    )

    # The product uses -I/-m; auxiliary absolute-interpreter launchers and the
    # developer wheel file URL must not be distributed. Preserve other metadata.
    generated_bin = target / "bin"
    removed = set()
    if generated_bin.is_dir():
        for launcher in generated_bin.iterdir():
            if launcher.is_file():
                removed.add(launcher.relative_to(target).as_posix())
                launcher.unlink()
    for metadata in target.glob("matlab_companion-*.dist-info/direct_url.json"):
        removed.add(metadata.relative_to(target).as_posix())
        metadata.unlink()
    for record_path in target.glob("*.dist-info/RECORD"):
        with record_path.open(newline="", encoding="utf-8") as stream:
            records = [
                row for row in csv.reader(stream) if row[0].replace("\\", "/") not in removed
            ]
        with record_path.open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(records)
    (bundle / "Start Setup.vbs").write_text(
        'Set shell = CreateObject("WScript.Shell")\n'
        'Set fs = CreateObject("Scripting.FileSystemObject")\n'
        "base = fs.GetParentFolderName(WScript.ScriptFullName)\n"
        'shell.Run Chr(34) & base & "\\runtime\\pythonw.exe" & Chr(34) & '
        '" -I -m matlab_companion setup", 1, False\n',
        encoding="utf-8",
    )
    (bundle / "Run Self Test.cmd").write_text(
        '@echo off\n"%~dp0runtime\\python.exe" -I -m matlab_companion self-test\npause\n',
        encoding="utf-8",
    )
    reference_hashes = copy_documents(source, bundle, snapshot)
    shutil.copy2(requirements, bundle / "requirements.txt")
    if not (target / "matlab_companion/matlab/+companion/execute.m").is_file():
        raise ValueError("Packaged MATLAB workflow source is missing")
    for authored in (target / "matlab_companion").rglob("*"):
        if authored.is_file():
            validate_public_bytes(authored)

    environment = os.environ.copy()
    environment.update(
        LOCALAPPDATA=str(staging / "isolated-local-data"),
        CODEX_HOME=str(staging / "isolated-codex"),
    )
    environment.pop("MATLAB_COMPANION_MATLAB_ROOT", None)
    # This bootstrap blocks accidental regressions before any Core/service or
    # native process starts, while allowing the passive self-test entrypoint.
    run(
        str(runtime / "python.exe"),
        "-I",
        "-B",
        "-c",
        "import tkinter,matlab_companion.setup_ui; print('Packaged UI imports passed')",
        cwd=staging,
        env=environment,
    )
    run(
        str(runtime / "python.exe"),
        "-I",
        "-B",
        "-c",
        PASSIVE_BOOTSTRAP,
        str(staging / "self-test-guards.json"),
        "self-test",
        "--root",
        str(staging / "isolated-self-test"),
        cwd=staging,
        env=environment,
    )
    guard = json.loads((staging / "self-test-guards.json").read_text(encoding="utf-8"))
    if not guard["installed"] or any(guard["attempts"].values()):
        raise ValueError("Passive self-test attempted a prohibited operation")
    if (staging / "isolated-self-test").exists():
        raise ValueError("Passive self-test unexpectedly created product state")

    vendor_copies = vendor_documents(bundle, copy=True)
    wheel_identity = verify_product_wheel(wheel, snapshot, target)
    links = validate_document_links(bundle, [row["path"] for row in tree_manifest(bundle)])
    verify_snapshot_bytes(source, snapshot)
    verify_source(repo, snapshot)
    provenance = {
        "schema_version": 1,
        "scope": "unpublished P1 engineering package; no activation",
        "source_commit": snapshot["source_commit"],
        "source_tree": snapshot["source_tree"],
        "version": version,
        "uv": uv_version,
        "build_environment": build_versions,
        "lock_sha256": sha256(source / "uv.lock"),
        "requirements_sha256": sha256(requirements),
        "product_wheel": {
            "name": wheel.name,
            "sha256": sha256(wheel),
            "size_bytes": wheel.stat().st_size,
        },
        "dependency_wheels": dependency_wheels,
        "python_distribution": {
            "version": sys.version.split()[0],
            "architecture": "x64",
            "copied_file_count": len(runtime_files),
            "copied_tree_manifest_sha256": runtime_digest,
            "python_exe_sha256": sha256(runtime / "python.exe"),
            "checksum_scope": "Copied clean distribution tree before dependencies; not an upstream archive checksum",
        },
        "reference_files_sha256": reference_hashes,
        "normative_files_sha256": {
            name: reference_hashes[name] for name in sorted(NORMATIVE_FILES)
        },
        "document_links": links,
        "product_identity": wheel_identity,
        "vendor_document_copies": vendor_copies,
    }
    write_json(bundle / "build-provenance.json", provenance)
    files = tree_manifest(bundle)
    if any(
        row["path"].endswith(".pyc") or "__pycache__" in row["path"].split("/") for row in files
    ):
        raise ValueError("Bytecode cannot enter a relocatable package")
    findings = privacy_findings({row["path"]: bundle / row["path"] for row in files}, repo)
    if any(row["classification"] == "embedded_builder_metadata" for row in findings):
        raise ValueError("Builder identity or checkout path embedded in package")
    manifest = {
        "schema_version": 1,
        "version": version,
        "python": sys.version.split()[0],
        "source_commit": snapshot["source_commit"],
        "source_tree": snapshot["source_tree"],
        "source_dirty": False,
        "provenance_sha256": sha256(bundle / "build-provenance.json"),
        "files": files,
    }
    write_json(bundle / "bundle-manifest.json", manifest)
    verify_manifest(bundle, manifest)
    archive = staging / (bundle.name + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as output:
        for member in [row["path"] for row in files] + ["bundle-manifest.json"]:
            output.write(bundle / member, bundle.name + "/" + member)
    verify_snapshot_bytes(source, snapshot)
    verify_source(repo, snapshot)
    verify_manifest(bundle, manifest)
    archive.with_suffix(".sha256").write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )
    receipt = {
        "archive": str(archive),
        "size_bytes": archive.stat().st_size,
        "sha256": sha256(archive),
        "source_commit": snapshot["source_commit"],
        "wheel_sha256": sha256(wheel),
        "manifest_sha256": sha256(bundle / "bundle-manifest.json"),
        "expanded_bytes": sum(row["size_bytes"] for row in files),
        "document_links": links,
    }
    write_json(staging / "build-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
