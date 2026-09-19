"""Independent passive Windows package audit; no Core, host mutation or MATLAB.

Use the developer environment for JSON Schema checking. Every tested product
entrypoint imports from the newly extracted package, guarded before Core/service
construction. Integrity checks must pass before a package executable is run.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bundle_support import (
    NORMATIVE_FILES,
    PASSIVE_BOOTSTRAP,
    capture_source,
    check_versions,
    document_paths,
    privacy_findings,
    safe_file,
    sha256,
    tree_manifest,
    validate_archive_members,
    validate_document_links,
    validate_public_bytes,
    vendor_documents,
    verify_manifest,
    verify_product_wheel,
    verify_source,
)


def run_python(python: Path, args: list[str], cwd: Path, state_root: Path) -> dict:
    environment = os.environ.copy()
    environment.update(
        LOCALAPPDATA=str(state_root / "local-data"), CODEX_HOME=str(state_root / "codex")
    )
    environment.pop("MATLAB_COMPANION_MATLAB_ROOT", None)
    started = time.monotonic()
    completed = subprocess.run(
        [str(python), "-I", "-B", *args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return {
        "returncode": completed.returncode,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


PROBE = r"""
import asyncio
import importlib.metadata
import json
import sys
import tkinter
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import matlab_companion
import matlab_companion.setup_ui

async def main():
    root = Path(sys.argv[1])
    root.mkdir(parents=True, exist_ok=False)
    guards = root / "protocol-guards.json"
    parameters = StdioServerParameters(command=sys.executable,
        args=["-I", "-B", sys.argv[2], str(guards), "serve", "--root", str(root / "server")])
    calls = []
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listing = await session.list_tools()
        schemas = {tool.name: tool.output_schema for tool in listing.tools}
        assert len(schemas) == 6
        # Invalid inspect/job requests never enter their stateful code paths.
        for name, arguments in [
            ("matlab_status", {}),
            ("matlab_help", {}),
            ("matlab_inspect", {"path": ""}),
            ("matlab_artifacts", {"action": "read_schema", "operation": "linear_calibration"}),
            ("matlab_run", {"operation": "linear_calibration", "parameters": {}, "idempotency_key": "package-invalid-request"}),
            ("matlab_job", {"action": "status"}),
        ]:
            result = await session.call_tool(name, arguments)
            assert json.loads(result.content[0].text) == result.structured_content
            expected_error = name in ("matlab_inspect", "matlab_run", "matlab_job")
            assert bool(result.is_error) == expected_error, (name, result)
            assert result.structured_content["ok"] is not expected_error
            calls.append({"tool": name, "is_error": bool(result.is_error),
                          "structured": result.structured_content, "schema": schemas[name]})
        resources = await session.list_resources()
        assert len(resources.resources) == 10
        await session.read_resource("matlab-companion://schemas/linear_calibration/result")
    guard = json.loads(guards.read_text(encoding="utf-8"))
    assert guard["installed"] and not any(guard["attempts"].values()), guard
    assert not (root / "server").exists()
    # Import Setup and construct Tcl without constructing a visible/native UI.
    interpreter = tkinter.Tcl()
    return {"python": sys.executable, "module_path": matlab_companion.__file__,
            "module_version": matlab_companion.__version__,
            "metadata_version": importlib.metadata.version("matlab-companion"),
            "calls": calls, "resource_count": len(resources.resources),
            "tk": {"tcl_version": interpreter.call("info", "patchlevel"),
                   "setup_imported": True, "window_constructed": False},
            "guards": guard, "product_root_created": False}

print(json.dumps(asyncio.run(main()), ensure_ascii=True))
"""


def audit(archive: Path, repo: Path, expected_source: str) -> dict:
    source = capture_source(repo)
    if source["source_commit"] != expected_source:
        raise ValueError("Audit requires the exact committed source used for this package")
    version = check_versions(repo)
    archive = archive.resolve(strict=True)
    dist = (repo / "dist").resolve(strict=True)
    extraction = dist / f"package audit 中文-{uuid.uuid4().hex[:12]}"
    extraction.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as bundle_zip:
        package_name = validate_archive_members(bundle_zip.infolist())
        if package_name != f"MATLAB-Companion-{version}-windows-x64":
            raise ValueError("Archive root does not identify the expected package version")
        bundle_zip.extractall(extraction)
    bundle = extraction / package_name
    manifest_path = safe_file(bundle, "bundle-manifest.json")
    manifest_hash = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity_before = verify_manifest(bundle, manifest)
    if (
        manifest.get("source_commit") != expected_source
        or manifest.get("source_dirty") is not False
        or manifest.get("source_tree") != source["source_tree"]
        or manifest.get("version") != version
    ):
        raise ValueError("Manifest source/version identity mismatch")
    provenance_path = safe_file(bundle, "build-provenance.json")
    if sha256(provenance_path) != manifest.get("provenance_sha256"):
        raise ValueError("Build provenance digest mismatch")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if (
        provenance.get("source_commit") != expected_source
        or provenance.get("source_tree") != source["source_tree"]
        or provenance.get("version") != version
    ):
        raise ValueError("Build provenance source/version identity mismatch")
    references = document_paths(source)
    expected_references = {name: source["source_files_sha256"][name] for name in references}
    if provenance.get("reference_files_sha256") != expected_references:
        raise ValueError("Package reference allowlist/source identity mismatch")
    if provenance.get("normative_files_sha256") != {
        name: expected_references[name] for name in NORMATIVE_FILES
    }:
        raise ValueError("Normative copy identity mismatch")
    for name, expected in expected_references.items():
        path = safe_file(bundle, name)
        if sha256(path) != expected:
            raise ValueError("Packaged reference is not byte-identical to its source")
        validate_public_bytes(path)
    if provenance.get("lock_sha256") != source["source_files_sha256"]["uv.lock"]:
        raise ValueError("Lock identity mismatch")
    if provenance.get("requirements_sha256") != sha256(safe_file(bundle, "requirements.txt")):
        raise ValueError("Exported requirements identity mismatch")
    # The engineering build retains its wheel and dependency downloads beside
    # the ZIP. Their hashes bind the archive receipt to actual selected inputs.
    product = provenance["product_wheel"]
    retained_wheel = safe_file(archive.parent, product["name"])
    if (
        sha256(retained_wheel) != product["sha256"]
        or retained_wheel.stat().st_size != product["size_bytes"]
    ):
        raise ValueError("Retained product wheel identity mismatch")
    if tree_manifest(archive.parent / "dependency-wheels") != provenance["dependency_wheels"]:
        raise ValueError("Retained dependency wheel inventory mismatch")
    vendor_copies = vendor_documents(bundle)
    if provenance.get("vendor_document_copies") != vendor_copies:
        raise ValueError("Vendor document provenance mismatch")
    wheel_identity = verify_product_wheel(
        retained_wheel, source, bundle / "runtime/Lib/site-packages"
    )
    files = {row["path"]: bundle / row["path"] for row in manifest["files"]}
    files["bundle-manifest.json"] = manifest_path
    links = validate_document_links(
        bundle, [name for name in files if name != "bundle-manifest.json"]
    )
    findings = privacy_findings(files, repo)
    if any(row["classification"] == "embedded_builder_metadata" for row in findings):
        raise ValueError("Package contains embedded builder identity or checkout path")
    for name, path in files.items():
        if name.startswith("runtime/Lib/site-packages/matlab_companion/"):
            validate_public_bytes(path)

    # All static admission checks above must pass before executing the package.
    python = safe_file(bundle, "runtime/python.exe")
    state = extraction / "isolated acceptance state"
    state.mkdir()
    bootstrap = extraction / "guarded_entrypoint.py"
    bootstrap.write_text(PASSIVE_BOOTSTRAP, encoding="utf-8")
    self_guards = state / "self-test-guards.json"
    self_test = run_python(
        python,
        [str(bootstrap), str(self_guards), "self-test", "--root", str(state / "self-test")],
        extraction,
        state,
    )
    probe_script = extraction / "package_probe.py"
    probe_script.write_text(PROBE, encoding="utf-8")
    probe_run = run_python(
        python,
        [str(probe_script), str(state / "protocol-and-tk"), str(bootstrap)],
        extraction,
        state,
    )
    probe_summary = None
    schema_count = 0
    if probe_run["returncode"] == 0:
        result = json.loads(probe_run["stdout"])
        if (
            not Path(result["python"]).is_relative_to(bundle)
            or not Path(result["module_path"]).is_relative_to(bundle)
            or result["module_version"] != version
            or result["metadata_version"] != version
        ):
            raise ValueError("Probe did not use the exact relocated package and version")
        for call in result["calls"]:
            Draft202012Validator.check_schema(call["schema"])
            Draft202012Validator(call["schema"]).validate(call["structured"])
            schema_count += 1
        probe_summary = {
            "tool_calls": [
                {"tool": item["tool"], "is_error": item["is_error"]} for item in result["calls"]
            ],
            "validated_output_schemas": schema_count,
            "resource_count": result["resource_count"],
            "tk": result["tk"],
            "guards": result["guards"],
            "product_root_created": result["product_root_created"],
            "python_relative": Path(result["python"]).relative_to(bundle).as_posix(),
            "module_relative": Path(result["module_path"]).relative_to(bundle).as_posix(),
            "module_version": result["module_version"],
            "metadata_version": result["metadata_version"],
        }
    guards = json.loads(self_guards.read_text(encoding="utf-8")) if self_guards.exists() else None
    guards_pass = guards and guards["installed"] and not any(guards["attempts"].values())
    integrity_after = verify_manifest(bundle, manifest)
    if sha256(manifest_path) != manifest_hash:
        raise ValueError("Manifest changed during passive execution")
    verify_source(repo, source)
    runtime_pass = (
        self_test["returncode"] == 0
        and "PASS: portable" in self_test["stdout"]
        and guards_pass
        and not (state / "self-test").exists()
        and probe_run["returncode"] == 0
        and schema_count == 6
    )
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "status": "pass" if runtime_pass else "fail",
        "archive": archive.relative_to(repo).as_posix(),
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "manifest_sha256": manifest_hash,
        "product_wheel_sha256": product["sha256"],
        "extraction_relative": extraction.relative_to(repo).as_posix(),
        "relocated_path_contains_spaces_and_chinese": True,
        "manifest": {
            "before": integrity_before,
            "after": integrity_after,
            "source_commit": expected_source,
            "source_tree": source["source_tree"],
            "source_dirty": False,
            "version": version,
            "python": manifest["python"],
        },
        "document_links": links,
        "product_identity": wheel_identity,
        "vendor_document_copies": vendor_copies,
        "normative_copies_verified": len(NORMATIVE_FILES),
        "privacy_scan": {
            "scope": "Exact builder username/checkout bytes and bounded credential patterns in authored references/product files; not a comprehensive secret audit.",
            "embedded_builder_metadata_files": 0,
            "findings": findings,
        },
        "self_test": {
            "returncode": self_test["returncode"],
            "elapsed_seconds": self_test["elapsed_seconds"],
            "portable_pass_text_present": "PASS: portable" in self_test["stdout"],
            "guards": guards,
            "product_root_created": (state / "self-test").exists(),
            "stderr": self_test["stderr"][:5000],
        },
        "passive_protocol": {
            "returncode": probe_run["returncode"],
            "elapsed_seconds": probe_run["elapsed_seconds"],
            "result": probe_summary,
            "stderr": probe_run["stderr"][:5000],
        },
        "boundaries": {
            "scope": "Unpublished P1 package admission only",
            "guarded_passive_checks": True,
            "core_started": False,
            "visible_gui_opened": False,
            "host_configuration_changed": False,
            "matlab_launched": False,
            "fresh_device_acceptance": False,
            "host_model_acceptance": False,
            "installed_activation": False,
            "native_artifact_delivery_acceptance": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-source", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        report = audit(args.archive, repo, args.expected_source)
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        zipfile.BadZipFile,
    ) as error:
        report = {"status": "fail", "error_type": type(error).__name__, "error": str(error)}
    target = args.report if args.report.is_absolute() else repo / args.report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
