"""Independent Windows package audit; no live host changes or MATLAB launch.

Run with the developer environment for jsonschema validation. Every tested
product command and MCP server uses the newly extracted package interpreter.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import stat
import subprocess
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def privacy_findings(archived_files: dict[str, Path], repo: Path) -> list[dict]:
    fingerprints = {
        "builder_username": getpass.getuser(),
        "builder_checkout_backslash": str(repo),
        "builder_checkout_forward_slash": repo.as_posix(),
    }
    findings = []
    for relative, item in archived_files.items():
        data = item.read_bytes().lower()
        categories = []
        for category, value in fingerprints.items():
            for pattern in {value, value.replace("\\", "\\\\")}:
                if (
                    pattern.encode("utf-8").lower() in data
                    or pattern.encode("utf-16-le").lower() in data
                ):
                    categories.append(category)
                    break
        if categories:
            documented_example = (
                relative == "docs/ARCHITECTURE.md" and "builder_username" not in categories
            )
            findings.append(
                {
                    "path": relative,
                    "categories": categories,
                    "classification": "documented_checkout_example"
                    if documented_example
                    else "embedded_builder_metadata",
                }
            )
    return sorted(findings, key=lambda item: (item["path"].endswith(".pyc"), item["path"]))


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
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import matlab_companion
from matlab_companion.setup_ui import SetupWindow

async def main():
    root = Path(sys.argv[1])
    # Passive self-test no longer creates the acceptance parent directory.
    root.mkdir(parents=True)
    input_folder = root / "inputs"
    input_folder.mkdir()
    fixture = input_folder / "synthetic.csv"
    fixture.write_text("x,y\n0,1\n1,3\n2,5\n", encoding="utf-8")
    parameters = StdioServerParameters(command=sys.executable,
        args=["-I", "-B", "-m", "matlab_companion", "serve", "--root", str(root / "server"),
              "--allow-root", str(input_folder)])
    calls = []
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listing = await session.list_tools()
        schemas = {tool.name: tool.output_schema for tool in listing.tools}
        assert len(schemas) == 6
        for name, arguments in [
            ("matlab_status", {}),
            ("matlab_help", {}),
            ("matlab_inspect", {"path": str(fixture)}),
            ("matlab_artifacts", {"action": "read_schema", "operation": "linear_calibration"}),
            ("matlab_run", {"operation": "linear_calibration", "parameters": {}, "idempotency_key": "package-invalid-request"}),
            ("matlab_job", {"job_id": "00000000-0000-4000-8000-000000000000", "action": "status"}),
        ]:
            result = await session.call_tool(name, arguments)
            assert json.loads(result.content[0].text) == result.structured_content
            expected_error = name in ("matlab_run", "matlab_job")
            assert bool(result.is_error) == expected_error, (name, result)
            assert result.structured_content["ok"] is not expected_error
            calls.append({"tool": name, "is_error": bool(result.is_error),
                          "structured": result.structured_content, "schema": schemas[name]})
        resources = await session.list_resources()
        assert len(resources.resources) == 10
        await session.read_resource("matlab-companion://schemas/linear_calibration/result")
    window = SetupWindow(root / "gui-state")
    window.window.withdraw()
    window.window.update()
    hidden_state = window.window.state()
    tk_version = window.window.tk.call("info", "patchlevel")
    assert hidden_state == "withdrawn"
    window.window.destroy()
    assert not list(root.rglob("dispatch.json"))
    assert not list(root.rglob("backend-result.json"))
    return {"python": sys.executable, "module_path": matlab_companion.__file__,
            "calls": calls, "resource_count": len(resources.resources),
            "tk": {"state_during_update": hidden_state, "version": tk_version,
                   "constructed": True, "updated": True, "destroyed": True},
            "native_dispatch_files": 0}

print(json.dumps(asyncio.run(main()), ensure_ascii=True))
"""


def audit(archive: Path, repo: Path) -> dict:
    archive = archive.resolve(strict=True)
    dist = (repo / "dist").resolve(strict=True)
    extraction = dist / f"package audit 中文-{uuid.uuid4().hex[:12]}"
    extraction.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as bundle_zip:
        names = bundle_zip.namelist()
        folded = [os.path.normcase(name) for name in names]
        if len(folded) != len(set(folded)):
            raise ValueError("Archive has duplicate or case-colliding paths")
        for info in bundle_zip.infolist():
            target = (extraction / info.filename).resolve()
            if not target.is_relative_to(extraction) or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Archive contains an escaping path or symbolic link")
        bundle_zip.extractall(extraction)
    manifests = list(extraction.glob("*/bundle-manifest.json"))
    if len(manifests) != 1:
        raise ValueError("Expected exactly one package manifest")
    bundle = manifests[0].parent
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    manifest_paths = set()
    mismatches = []
    for record in manifest["files"]:
        relative = record["path"]
        item = (bundle / relative).resolve()
        if not item.is_relative_to(bundle) or relative in manifest_paths:
            raise ValueError("Manifest contains an escaping or duplicate path")
        manifest_paths.add(relative)
        if not item.is_file():
            mismatches.append({"path": relative, "problem": "missing"})
        elif item.stat().st_size != record["size_bytes"] or sha256(item) != record["sha256"]:
            mismatches.append({"path": relative, "problem": "size_or_hash_mismatch"})
    archived_files = {
        item.relative_to(bundle).as_posix(): item for item in bundle.rglob("*") if item.is_file()
    }
    unlisted = sorted(set(archived_files) - manifest_paths - {"bundle-manifest.json"})
    # Scan only exact builder identity/path fingerprints, not generic variable names.
    findings = privacy_findings(archived_files, repo)
    embedded = [item for item in findings if item["classification"] == "embedded_builder_metadata"]
    python = bundle / "runtime" / "python.exe"
    state = extraction / "isolated acceptance state"
    self_test = run_python(
        python,
        ["-m", "matlab_companion", "self-test", "--root", str(state / "self-test")],
        extraction,
        state,
    )
    probe_script = extraction / "package_probe.py"
    probe_script.write_text(PROBE, encoding="utf-8")
    probe_run = run_python(
        python, [str(probe_script), str(state / "protocol-and-tk")], extraction, state
    )
    probe_summary = None
    schema_count = 0
    if probe_run["returncode"] == 0:
        result = json.loads(probe_run["stdout"])
        if not Path(result["python"]).is_relative_to(bundle) or not Path(
            result["module_path"]
        ).is_relative_to(bundle):
            raise ValueError("Probe imported outside the relocated package")
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
            "native_dispatch_files": result["native_dispatch_files"],
            "python_relative": Path(result["python"]).relative_to(bundle).as_posix(),
            "module_relative": Path(result["module_path"]).relative_to(bundle).as_posix(),
        }
    runtime_pass = (
        self_test["returncode"] == 0 and probe_run["returncode"] == 0 and schema_count == 6
    )
    return {
        "observed_at": datetime.now(UTC).isoformat(),
        "status": "pass"
        if runtime_pass and not mismatches and not unlisted and not embedded
        else "partial",
        "archive": archive.relative_to(repo).as_posix(),
        "archive_size_bytes": archive.stat().st_size,
        "archive_sha256": sha256(archive),
        "extraction_relative": extraction.relative_to(repo).as_posix(),
        "relocated_path_contains_spaces_and_chinese": True,
        "manifest": {
            "entries": len(manifest_paths),
            "mismatches": mismatches,
            "unlisted_file_count": len(unlisted),
            "unlisted_examples": unlisted[:20],
            "source_commit": manifest.get("source_commit"),
            "source_dirty": manifest.get("source_dirty"),
            "python": manifest.get("python"),
        },
        "privacy_scan": {
            "scope": "Exact local builder username and checkout path bytes, UTF-8/UTF-16; not a comprehensive secret audit.",
            "matched_file_count": len(findings),
            "embedded_builder_metadata_files": len(embedded),
            "non_bytecode_findings": [
                item for item in findings if not item["path"].endswith(".pyc")
            ],
            "findings": findings[:100],
            "truncated": len(findings) > 100,
        },
        "self_test": {
            "returncode": self_test["returncode"],
            "elapsed_seconds": self_test["elapsed_seconds"],
            "portable_pass_text_present": "PASS: portable" in self_test["stdout"],
            "stderr": self_test["stderr"][:5000],
        },
        "protocol_and_hidden_tk": {
            "returncode": probe_run["returncode"],
            "elapsed_seconds": probe_run["elapsed_seconds"],
            "result": probe_summary,
            "stderr": probe_run["stderr"][:5000],
        },
        "boundaries": {
            "visible_gui_opened": False,
            "host_configuration_changed": False,
            "matlab_launched": False,
            "vendor_downloaded": False,
            "fresh_device_acceptance": False,
            "host_model_acceptance": False,
            "native_artifact_delivery_acceptance": False,
            "note": "Package runtime/protocol/hidden-window checks only; valid only for the recorded archive SHA-256.",
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=Path("verification/package-check.json"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    report = audit(args.archive, repo)
    target = args.report if args.report.is_absolute() else repo / args.report
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "archive_sha256",
                    "manifest",
                    "self_test",
                    "protocol_and_hidden_tk",
                )
            },
            ensure_ascii=True,
        )
    )
    print(f"privacy_matched_files={report['privacy_scan']['matched_file_count']}")


if __name__ == "__main__":
    main()
