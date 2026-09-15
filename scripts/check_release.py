"""Audit public source contents and required entrypoints without native software."""

import re
import struct
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
    "adapters/codex/matlab-companion/assets/icon.png",
    "adapters/codex/matlab-companion/assets/icon.ico",
]
for name in required:
    assert (root / name).is_file(), name
patterns = [
    r"gh[pousr]_[A-Za-z0-9]{30,}",
    r"sk-[A-Za-z0-9_-]{30,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
]
icon_folder = root / "adapters/codex/matlab-companion/assets"
icon_paths = {icon_folder / "icon.png", icon_folder / "icon.ico"}
png_signature = b"\x89PNG\r\n\x1a\n"
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
        if path in icon_paths:
            data = path.read_bytes()
            assert 32 <= len(data) <= 2 * 1024 * 1024, f"Invalid icon size: {path}"
            if path.suffix == ".png":
                assert data.startswith(png_signature), f"Invalid PNG: {path}"
                assert data[8:16] == b"\x00\x00\x00\rIHDR", f"Missing PNG header: {path}"
                width, height = struct.unpack_from(">II", data, 16)
                assert 16 <= width == height <= 2048, f"Invalid PNG dimensions: {path}"
            else:
                assert data[:4] == b"\x00\x00\x01\x00", f"Invalid ICO: {path}"
                frames = struct.unpack_from("<H", data, 4)[0]
                assert 1 <= frames <= 8 and len(data) >= 6 + 16 * frames, path
                for index in range(frames):
                    size, offset = struct.unpack_from("<II", data, 6 + 16 * index + 8)
                    assert 6 + 16 * frames <= offset < offset + size <= len(data), path
                    assert data[offset : offset + 8] == png_signature, path
            # Preserve credential scanning for the two explicitly permitted binary assets.
            text = data.decode("latin-1")
        else:
            text = path.read_text(encoding="utf-8")
        assert not any(re.search(pattern, text) for pattern in patterns), (
            f"Credential-like content: {path}"
        )
        count += 1
print(
    f"PASS: {count} public source files audited; required entrypoints present; no bundled vendor runtime/native data."
)
