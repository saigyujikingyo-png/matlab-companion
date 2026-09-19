"""Standard-library package admission checks; never import Core or start a service."""

from __future__ import annotations

import ast
import getpass
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tomllib
import zipfile
from html import unescape
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import unquote, urlsplit

DOCUMENT_ROOTS = {
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "AGENTS.md",
    "DEVELOPMENT_PRINCIPLES.md",
}
REFERENCE_FILES = {
    "CLOUD_STORAGE.md",
    "RUNTIME_LIFECYCLE.md",
    "governance/OWNERSHIP.md",
    "governance/incidents/CB-2026-001.md",
    "templates/LIFECYCLE_RECORD.md",
    "pyproject.toml",
    "uv.lock",
    "scripts/build_windows_bundle.py",
    "src/matlab_companion/__main__.py",
    "src/matlab_companion/backend.py",
    "src/matlab_companion/client.py",
    "src/matlab_companion/contracts.py",
    "src/matlab_companion/coordinator.py",
    "src/matlab_companion/core.py",
    "src/matlab_companion/native_session.py",
    "src/matlab_companion/server.py",
    "src/matlab_companion/setup_ui.py",
    "src/matlab_companion/startup.py",
    "tests/test_client_boundary.py",
    "tests/test_coordinator.py",
    "tests/test_recovery.py",
    "tests/test_startup.py",
}
NORMATIVE_FILES = {
    "DEVELOPMENT_PRINCIPLES.md",
    "CLOUD_STORAGE.md",
    "RUNTIME_LIFECYCLE.md",
    "governance/OWNERSHIP.md",
    "templates/LIFECYCLE_RECORD.md",
}
PRIVATE_PARTS = {".git", ".venv", ".env", ".local", "private", "__pycache__"}
CREDENTIAL_PATTERNS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{30,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
MAX_MARKDOWN_BYTES = 1024 * 1024


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_file(root, relative):
    root = Path(root).resolve()
    relative = str(relative)
    pieces = relative.split("/")
    if (
        not pieces
        or "\\" in relative
        or PureWindowsPath(relative).drive
        or PurePosixPath(relative).is_absolute()
        or any(not p or p in {".", ".."} or ":" in p or p.endswith((" ", ".")) for p in pieces)
    ):
        raise ValueError("Package paths must be relative and contained")
    current = root
    for piece in pieces:
        current = current / piece
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Package source contains a link or reparse point")
    if not current.is_file():
        raise ValueError("Package entry is not a regular file")
    return current


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args]).decode("utf-8")


def capture_source(repo):
    repo = Path(repo).resolve()
    if git(repo, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("A clean committed source snapshot is required before packaging")
    commit = git(repo, "rev-parse", "HEAD").strip()
    tree = git(repo, "rev-parse", "HEAD^{tree}").strip()
    paths = sorted(p for p in git(repo, "ls-files", "-z").split("\0") if p)
    if not paths or len({p.casefold() for p in paths}) != len(paths):
        raise ValueError("Source file list is empty or has case collisions")
    hashes = {}
    for relative in paths:
        if any(p.casefold() in PRIVATE_PARTS for p in PurePosixPath(relative).parts):
            raise ValueError("Private paths cannot enter a public source snapshot")
        path = safe_file(repo, relative)
        hashes[relative] = sha256(path)
    if (
        commit != git(repo, "rev-parse", "HEAD").strip()
        or git(repo, "status", "--porcelain", "--untracked-files=all").strip()
    ):
        raise ValueError("Source changed while its snapshot was being captured")
    return {"source_commit": commit, "source_tree": tree, "source_files_sha256": hashes}


def verify_source(repo, snapshot):
    if capture_source(repo) != snapshot:
        raise ValueError("Source identity or bytes changed during packaging")


def copy_snapshot(repo, destination, snapshot):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name, expected in snapshot["source_files_sha256"].items():
        original = safe_file(repo, name)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        if sha256(target) != expected:
            raise ValueError("Source snapshot copy failed readback")
    verify_source(repo, snapshot)


def check_versions(repo):
    repo = Path(repo)
    project = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    tree = ast.parse((repo / "src/matlab_companion/__init__.py").read_text(encoding="utf-8"))
    module = [
        ast.literal_eval(n.value)
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets)
    ]
    locked = tomllib.loads((repo / "uv.lock").read_text(encoding="utf-8"))
    entries = [p for p in locked["package"] if p["name"] == "matlab-companion"]
    if module != [version] or len(entries) != 1 or entries[0]["version"] != version:
        raise ValueError("Project, module and locked root versions disagree")
    match = re.fullmatch(r"(\d+\.\d+\.\d+)a(\d+)", version)
    if not match:
        raise ValueError("A distinct alpha package version is required")
    plugin_version = f"{match[1]}-alpha.{match[2]}"
    folder = repo / "adapters/codex/matlab-companion"
    plugin = json.loads((folder / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    guidance = (folder / "skills/matlab-workflow/SKILL.md").read_text(encoding="utf-8")
    if (
        plugin["version"] != plugin_version
        or f"`{version}`" not in guidance
        or f"`{plugin_version}`" not in guidance
    ):
        raise ValueError("Plugin metadata and guidance must identify the same candidate")
    return version


def document_paths(snapshot):
    tracked = set(snapshot["source_files_sha256"])
    required = DOCUMENT_ROOTS | REFERENCE_FILES
    if not required <= tracked:
        raise ValueError("Required public package references are not committed")
    paths = required | {p for p in tracked if PurePosixPath(p).parts[0] in {"docs", "verification"}}
    for path in paths:
        if any(p.casefold() in PRIVATE_PARTS for p in PurePosixPath(path).parts):
            raise ValueError("Private package document dependency refused")
    return sorted(paths)


def validate_public_bytes(path):
    raw = Path(path).read_bytes()
    if any(pattern.search(raw) for pattern in CREDENTIAL_PATTERNS):
        raise ValueError("Credential-like bytes in a public package reference")


def copy_documents(repo, bundle, snapshot):
    copied = {}
    for name in document_paths(snapshot):
        original = safe_file(repo, name)
        validate_public_bytes(original)
        target = Path(bundle) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, target)
        if sha256(target) != snapshot["source_files_sha256"][name]:
            raise ValueError("Package reference copy changed bytes")
        copied[name] = sha256(target)
    return copied


def without_code(text, *, keep_inline=False):
    lines = []
    fence = None
    for line in text.splitlines():
        opening = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if opening:
            token = opening[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            lines.append("")
        elif fence is not None or line.startswith(("    ", "\t")):
            lines.append("")
        else:
            lines.append(re.sub(r"(`+)(.*?)\1", r"\2" if keep_inline else "", line))
    return "\n".join(lines)


class HTMLReferences(HTMLParser):
    def __init__(self):
        super().__init__()
        self.anchors = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.anchors.add(values["id"])
        if tag == "a" and values.get("name"):
            self.anchors.add(values["name"])
        for name in ("href", "src"):
            if values.get(name):
                self.links.append(values[name])


def markdown_references(text):
    clean = without_code(text)
    parser = HTMLReferences()
    parser.feed(clean)
    anchors = set(parser.anchors)
    counts = {}
    previous = ""
    for line in without_code(text, keep_inline=True).splitlines():
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+\s*)?$", line)
        title = (
            heading[1]
            if heading
            else previous
            if re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", line) and previous.strip()
            else None
        )
        if title:
            title = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", title)
            title = unescape(re.sub(r"<[^>]+>", "", title)).lower()
            slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
            index = counts.get(slug, 0)
            counts[slug] = index + 1
            anchors.add(slug if not index else f"{slug}-{index}")
        previous = line
    definition = re.compile(r"^\s{0,3}\[([^]]+)\]:\s*(<[^>]+>|\S+)(?:\s+.*)?$", re.MULTILINE)
    definitions = {m[1].strip().casefold(): m[2].strip("<>") for m in definition.finditer(clean)}
    clean = definition.sub("", clean)
    inline = re.compile(r"!?\[[^]\n]*\]\((<[^>]+>|(?:[^()\n]|\([^()\n]*\))*)\)")
    links = list(parser.links)
    for match in inline.finditer(clean):
        target = match[1].strip()
        if target.startswith("<"):
            target = target[1 : target.index(">")]
        else:
            target = re.split(r"\s+[\"\']", target, maxsplit=1)[0]
        links.append(target)
    clean = inline.sub("", clean)
    references = re.compile(r"!?\[([^]\n]+)\]\[([^]\n]*)\]")
    for match in references.finditer(clean):
        key = (match[2] or match[1]).strip().casefold()
        if key not in definitions:
            raise ValueError("Markdown reference has no target definition")
        links.append(definitions[key])
    clean = references.sub("", clean)
    for match in re.finditer(r"!?\[([^]\n]+)\]", clean):
        key = match[1].strip().casefold()
        if key in definitions:
            links.append(definitions[key])
    return links, anchors


def validate_document_links(bundle, paths):
    bundle = Path(bundle).resolve()
    paths = sorted(set(paths))
    if len({p.casefold() for p in paths}) != len(paths):
        raise ValueError("Case-colliding package paths")
    parsed = {}
    for name in paths:
        if name.endswith(".md"):
            path = safe_file(bundle, name)
            if path.stat().st_size > MAX_MARKDOWN_BYTES:
                raise ValueError("Package Markdown exceeds its size limit")
            parsed[name] = markdown_references(path.read_text(encoding="utf-8"))
    local_count = 0
    for name, (links, _) in parsed.items():
        for target in links:
            url = urlsplit(target)
            if url.scheme in {"https", "http", "mailto"}:
                continue
            if url.scheme or url.netloc or "\\" in unquote(target):
                raise ValueError(f"Unapproved absolute/URI package link in {name}")
            decoded = unquote(url.path)
            if PureWindowsPath(decoded).drive or decoded.startswith("/"):
                raise ValueError("Absolute filesystem package link")
            # Normalize '..' only for containment; check every resulting path
            # component with lstat before following anything in the package.
            parts = (
                list(PurePosixPath(name).parent.parts)
                if decoded
                else list(PurePosixPath(name).parts)
            )
            for part in PurePosixPath(decoded).parts:
                if part == "..":
                    if not parts:
                        raise ValueError("Package link escapes its root")
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            relative = "/".join(parts)
            if relative not in paths:
                raise ValueError(f"Missing or case-mismatched packaged link: {name} -> {relative}")
            safe_file(bundle, relative)
            if url.fragment and (
                relative not in parsed or unquote(url.fragment) not in parsed[relative][1]
            ):
                raise ValueError(f"Missing packaged anchor: {name} -> {relative}#{url.fragment}")
            local_count += 1
    return {"markdown_files": len(parsed), "local_links": local_count, "broken_links": 0}


def tree_manifest(root):
    root = Path(root)
    records = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Package tree contains a link or reparse point")
        if path.is_file():
            records.append({"path": relative, "size_bytes": info.st_size, "sha256": sha256(path)})
    if len({r["path"].casefold() for r in records}) != len(records):
        raise ValueError("Case collision in package manifest")
    return records


def verify_manifest(bundle, manifest):
    records = manifest["files"]
    names = [r["path"] for r in records]
    if len(set(names)) != len(names) or len({n.casefold() for n in names}) != len(names):
        raise ValueError("Duplicate manifest member")
    for record in records:
        path = safe_file(bundle, record["path"])
        if path.stat().st_size != record["size_bytes"] or sha256(path) != record["sha256"]:
            raise ValueError("Package manifest size/hash mismatch")
    actual = {r["path"] for r in tree_manifest(bundle)}
    if actual != set(names) | {"bundle-manifest.json"}:
        raise ValueError("Package contains missing or unlisted files")
    return {"entries": len(names), "mismatches": 0, "unlisted_files": 0}


def privacy_findings(files, repo):
    fingerprints = {
        "builder_username": getpass.getuser(),
        "builder_checkout_backslash": str(repo),
        "builder_checkout_forward_slash": Path(repo).as_posix(),
    }
    findings = []
    for relative, item in files.items():
        raw = Path(item).read_bytes().lower()
        categories = []
        for category, value in fingerprints.items():
            for pattern in {value, value.replace("\\", "\\\\")}:
                if (
                    pattern.encode("utf-8").lower() in raw
                    or pattern.encode("utf-16-le").lower() in raw
                ):
                    categories.append(category)
                    break
        if categories:
            example = relative == "docs/ARCHITECTURE.md" and "builder_username" not in categories
            findings.append(
                {
                    "path": relative,
                    "categories": categories,
                    "classification": "documented_checkout_example"
                    if example
                    else "embedded_builder_metadata",
                }
            )
    return findings


def verify_snapshot_bytes(root, snapshot):
    for name, expected in snapshot["source_files_sha256"].items():
        if sha256(safe_file(root, name)) != expected:
            raise ValueError("Frozen source bytes changed during the build")


def validate_archive_members(infos):
    """Validate every member before extraction or execution, including on Windows."""
    names = [info.filename for info in infos]
    if not names or len({name.casefold() for name in names}) != len(names):
        raise ValueError("Archive has duplicate or case-colliding paths")
    top_levels = set()
    for info in infos:
        name = info.filename
        parts = name.split("/")
        if (
            info.is_dir()
            or getattr(info, "orig_filename", name) != name
            or "\\" in name
            or PureWindowsPath(name).drive
            or any(
                not part
                or part in {".", ".."}
                or ":" in part
                or part.endswith((" ", "."))
                or PureWindowsPath(part).is_reserved()
                for part in parts
            )
            or len(parts) < 2
            or stat.S_ISLNK(info.external_attr >> 16)
        ):
            raise ValueError("Archive contains an unsafe path or symbolic link")
        top_levels.add(parts[0])
    if len(top_levels) != 1:
        raise ValueError("Archive must contain exactly one package root")
    # A file cannot also be the parent of another member.
    folded = {name.casefold() for name in names}
    if any(
        "/".join(name.split("/")[:i]).casefold() in folded
        for name in names
        for i in range(1, len(name.split("/")))
    ):
        raise ValueError("Archive has a file/directory collision")
    return next(iter(top_levels))


# Runs only in an isolated package-audit child, never in installed product code.
PASSIVE_BOOTSTRAP = r"""
import atexit
import json
import subprocess
import sys
from pathlib import Path
from matlab_companion.core import Core
import matlab_companion.coordinator as coordinator
import matlab_companion.client as client
from matlab_companion.__main__ import main

receipt = Path(sys.argv[1])
counts = {"core": 0, "service": 0, "ensure": 0, "subprocess": 0}
def record():
    receipt.write_text(json.dumps({"installed": True, "attempts": counts}), encoding="utf-8")
def forbid(name):
    def blocked(*args, **kwargs):
        counts[name] += 1
        record()
        raise AssertionError("Passive package admission forbids " + name)
    return blocked
Core.__init__ = forbid("core")
coordinator.spawn_coordinator = forbid("service")
client.spawn_coordinator = forbid("service")
client.CoordinatorClient._ensure = forbid("ensure")
subprocess.Popen = forbid("subprocess")
record()
atexit.register(record)
sys.argv = ["matlab_companion", *sys.argv[2:]]
main()
"""


def verify_product_wheel(wheel, source, installed):
    """Compare all shipped product bytes to S and to their wheel installation."""
    expected = {}
    for name, digest in source["source_files_sha256"].items():
        if name.startswith("src/matlab_companion/"):
            expected[name.removeprefix("src/")] = digest
        elif name.startswith("matlab/"):
            expected["matlab_companion/" + name] = digest
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
        names = [info.filename for info in members]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Duplicate/case-colliding product wheel member")
        actual = {name for name in names if name.startswith("matlab_companion/")}
        if actual != set(expected):
            raise ValueError("Product wheel source inventory mismatch")
        for name, digest in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Product wheel bytes do not match the committed snapshot")
            if sha256(safe_file(installed, name)) != digest:
                raise ValueError("Installed product bytes do not match its wheel/source")
    installed_files = {
        "matlab_companion/" + row["path"]
        for row in tree_manifest(Path(installed) / "matlab_companion")
    }
    if installed_files != set(expected):
        raise ValueError("Installed product has missing or unexpected source files")
    return {"product_files": len(expected), "source_wheel_installed_match": True}
