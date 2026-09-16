"""Harness process bootstrap only: no MATLAB, backend calls, or user store."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import mcp
import pytest

import matlab_companion

HARNESS_PATH = Path(__file__).resolve().parents[1] / "acceptance" / "native_r2_lifecycle.py"


def harness_module():
    spec = importlib.util.spec_from_file_location("native_r2_harness_test", HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_two_base_python_generations_preserve_controller_runtime_and_mcp(monkeypatch):
    harness = harness_module()
    monkeypatch.delenv(harness.BOOTSTRAP_CONTEXT_ENV, raising=False)
    expected = harness.bootstrap_context()
    # The first child imports this same helper, exactly as the acceptance worker
    # does. Its site.getsitepackages() is now base Python, not the initial venv.
    grandchild = (
        "import json,os,mcp,matlab_companion; "
        "print(json.dumps({'mcp':mcp.__file__,'runtime':matlab_companion.__file__,"
        f"'context':json.loads(os.environ[{harness.BOOTSTRAP_CONTEXT_ENV!r}])}}))"
    )
    child = (
        "import importlib.util,json,subprocess; "
        f"spec=importlib.util.spec_from_file_location('r2',{str(HARNESS_PATH)!r}); "
        "module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); "
        f"result=subprocess.run(module.python_command({grandchild!r}),capture_output=True,"
        "text=True,check=True,timeout=15); print(result.stdout,end='')"
    )
    result = subprocess.run(
        harness.python_command(child), capture_output=True, text=True, check=True, timeout=25
    )
    observed = json.loads(result.stdout)
    assert Path(observed["mcp"]).resolve() == Path(mcp.__file__).resolve()
    assert Path(observed["runtime"]).resolve() == Path(matlab_companion.__file__).resolve()
    assert observed["context"] == expected


def test_bootstrap_rejects_a_different_runtime_binding(monkeypatch, tmp_path):
    harness = harness_module()
    monkeypatch.setenv(
        harness.BOOTSTRAP_CONTEXT_ENV,
        json.dumps(
            {
                "runtime_parent": str(tmp_path),
                "site_roots": [str(tmp_path)],
            }
        ),
    )
    with pytest.raises(AssertionError, match="initial controller"):
        harness.python_command("raise AssertionError('must not run')")
