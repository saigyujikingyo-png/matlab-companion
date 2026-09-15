"""Audit public source contents and required entrypoints without native software."""

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
required = [
    "AGENTS.md",
    "DEVELOPMENT_PRINCIPLES.md",
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "uv.lock",
    "scripts/setup_codex_cloud.sh",
    "scripts/check_contracts.py",
    "scripts/smoke_mcp.py",
    "src/matlab_companion/contracts.py",
    "matlab/+companion/execute.m",
    "docs/CONTRACTS.md",
]
for name in required:
    assert (root / name).is_file(), name
patterns = [
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"sk-[A-Za-z0-9_-]{30,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]
count = 0
for folder in (
    "src",
    "matlab",
    "scripts",
    "tests",
    "docs",
    "examples",
    "packaging",
    "adapters",
    "acceptance",
    "verification",
):
    for path in (root / folder).rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        assert path.suffix.lower() not in {".exe", ".dll", ".mat", ".fig", ".zip", ".lic"}, path
        text = path.read_text(encoding="utf-8")
        assert not any(re.search(pattern, text) for pattern in patterns), (
            f"Credential-like content: {path}"
        )
        count += 1
print(
    f"PASS: {count} public source files audited; required entrypoints present; no bundled vendor runtime/native data."
)
