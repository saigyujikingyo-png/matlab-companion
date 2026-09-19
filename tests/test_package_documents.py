"""Portable package admission tests; no product owner or native process starts."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bundle_support as bundle


def write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def committed_repo(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    write(repo, "README.md", "# Package\n")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    commit(repo, "Initial snapshot")
    return repo


def commit(repo, message):
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Package Test",
            "-c",
            "user.email=package-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


def test_source_copy_readback_and_changed_head_rejected(committed_repo, tmp_path):
    source = bundle.capture_source(committed_repo)
    destination = tmp_path / "frozen"
    bundle.copy_snapshot(committed_repo, destination, source)
    bundle.verify_snapshot_bytes(destination, source)
    write(committed_repo, "README.md", "# Changed\n")
    subprocess.run(["git", "-C", str(committed_repo), "add", "README.md"], check=True)
    commit(committed_repo, "Changed source")
    with pytest.raises(ValueError, match="identity or bytes changed"):
        bundle.verify_source(committed_repo, source)
    # The separate frozen bytes did not change with the live checkout.
    bundle.verify_snapshot_bytes(destination, source)
    write(destination, "README.md", "# Tampered frozen file\n")
    with pytest.raises(ValueError, match="Frozen source bytes changed"):
        bundle.verify_snapshot_bytes(destination, source)


@pytest.mark.parametrize("relative", ["README.md", "untracked.txt"])
def test_source_rejects_dirty_or_untracked_input(committed_repo, relative):
    write(committed_repo, relative, "dirty\n")
    with pytest.raises(ValueError, match="clean committed"):
        bundle.capture_source(committed_repo)


def test_source_change_during_capture_rejected(committed_repo, monkeypatch):
    original = bundle.sha256

    def changing_hash(path):
        value = original(path)
        path.write_text("Changed during capture\n", encoding="utf-8")
        return value

    monkeypatch.setattr(bundle, "sha256", changing_hash)
    with pytest.raises(ValueError, match="Source changed"):
        bundle.capture_source(committed_repo)


def test_copy_rejects_bytes_changed_after_capture(committed_repo, tmp_path):
    source = bundle.capture_source(committed_repo)
    write(committed_repo, "README.md", "# Changed after capture\n")
    with pytest.raises(ValueError, match="copy failed readback"):
        bundle.copy_snapshot(committed_repo, tmp_path / "frozen", source)


def version_fixture(root):
    write(root, "pyproject.toml", '[project]\nversion="0.1.0a4"\n')
    write(root, "src/matlab_companion/__init__.py", '__version__ = "0.1.0a4"\n')
    write(root, "uv.lock", '[[package]]\nname="matlab-companion"\nversion="0.1.0a4"\n')
    write(
        root,
        "adapters/codex/matlab-companion/.codex-plugin/plugin.json",
        '{"version":"0.1.0-alpha.4"}',
    )
    write(
        root,
        "adapters/codex/matlab-companion/skills/matlab-workflow/SKILL.md",
        "`0.1.0a4` / `0.1.0-alpha.4`",
    )


@pytest.mark.parametrize(
    "relative",
    [
        "pyproject.toml",
        "src/matlab_companion/__init__.py",
        "uv.lock",
        "adapters/codex/matlab-companion/.codex-plugin/plugin.json",
        "adapters/codex/matlab-companion/skills/matlab-workflow/SKILL.md",
    ],
)
def test_version_drift_rejected(tmp_path, relative):
    version_fixture(tmp_path)
    assert bundle.check_versions(tmp_path) == "0.1.0a4"
    path = tmp_path / relative
    path.write_text(
        path.read_text(encoding="utf-8").replace("a4", "a3").replace("alpha.4", "alpha.3"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bundle.check_versions(tmp_path)


def test_document_allowlist_is_exact_and_private_dependencies_are_refused():
    required = bundle.DOCUMENT_ROOTS | bundle.REFERENCE_FILES
    assert len(bundle.REFERENCE_FILES) == 22
    assert (
        set(
            bundle.document_paths({"source_files_sha256": dict.fromkeys(required | {"secret.csv"})})
        )
        == required
    )
    for missing in ["RUNTIME_LIFECYCLE.md", "src/matlab_companion/startup.py"]:
        with pytest.raises(ValueError, match="not committed"):
            bundle.document_paths({"source_files_sha256": dict.fromkeys(required - {missing})})
    with pytest.raises(ValueError, match="Private"):
        bundle.document_paths(
            {"source_files_sha256": dict.fromkeys(required | {"verification/private/receipt.json"})}
        )


def test_all_repository_documents_close_offline_and_keep_normative_bytes(tmp_path):
    repo = SCRIPTS.parent
    tracked = [p for p in bundle.git(repo, "ls-files", "-z").split("\0") if p]
    snapshot = {"source_files_sha256": {p: bundle.sha256(repo / p) for p in tracked}}
    copied = bundle.copy_documents(repo, tmp_path, snapshot)
    result = bundle.validate_document_links(tmp_path, copied)
    assert result["local_links"] >= 185
    assert result["broken_links"] == 0
    for name in bundle.NORMATIVE_FILES:
        assert (tmp_path / name).read_bytes() == (repo / name).read_bytes()


def test_markdown_anchors_references_unicode_and_code_blocks(tmp_path):
    write(
        tmp_path,
        "README.md",
        "# Readme\n[go][target]\n![image](image.bin)\n"
        '[target]: <docs/中文 file.md#use-code> "title"\n'
        '[same](#readme)\n< a>\n<a href="docs/中文%20file.md#repeat-1">HTML</a>\n'
        "```text\n[ignored](missing.txt)\n```\n`[also ignored](missing.txt)`\n",
    )
    write(
        tmp_path, "docs/中文 file.md", '# Use `code`\n## Repeat\n## Repeat\n<a id="explicit"></a>\n'
    )
    write(tmp_path, "image.bin", "image")
    result = bundle.validate_document_links(
        tmp_path, ["README.md", "docs/中文 file.md", "image.bin"]
    )
    assert result["local_links"] == 4


@pytest.mark.parametrize(
    "target",
    [
        "missing.md",
        "readme.md",
        "#missing",
        "../escape.md",
        "%2e%2e/escape.md",
        "file:///C:/private.md",
        "C:/private.md",
        "/absolute.md",
        "%5C%5Cserver/share.md",
        "README.md:stream",
    ],
)
def test_invalid_document_targets_are_refused(tmp_path, target):
    write(tmp_path, "README.md", f"# Readme\n[bad]({target})\n")
    with pytest.raises(ValueError):
        bundle.validate_document_links(tmp_path, ["README.md"])


def test_unresolved_reference_and_case_collision_refused(tmp_path):
    write(tmp_path, "README.md", "[bad][undefined]\n")
    with pytest.raises(ValueError, match="no target definition"):
        bundle.validate_document_links(tmp_path, ["README.md"])
    with pytest.raises(ValueError, match="Case-colliding"):
        bundle.validate_document_links(tmp_path, ["README.md", "readme.md"])


@pytest.mark.parametrize(
    "name", ["../out", "/absolute", "C:/out", "a:stream", "a\\b", "./file", "a//file", "file."]
)
def test_unsafe_manifest_paths_are_refused(tmp_path, name):
    with pytest.raises(ValueError):
        bundle.safe_file(tmp_path, name)


def test_source_link_is_refused(tmp_path):
    target = write(tmp_path, "real.md", "real")
    link = tmp_path / "link.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("Creating a Windows symlink needs an available privilege")
    with pytest.raises(ValueError, match="link or reparse"):
        bundle.safe_file(tmp_path, "link.md")


def test_manifest_tamper_extra_and_duplicate_are_refused(tmp_path):
    data = write(tmp_path, "file.txt", "original")
    manifest = {"files": bundle.tree_manifest(tmp_path)}
    write(tmp_path, "bundle-manifest.json", json.dumps(manifest))
    assert bundle.verify_manifest(tmp_path, manifest)["entries"] == 1
    data.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="size/hash mismatch"):
        bundle.verify_manifest(tmp_path, manifest)
    data.write_text("original", encoding="utf-8")
    extra = write(tmp_path, "unlisted.txt", "extra")
    with pytest.raises(ValueError, match="unlisted"):
        bundle.verify_manifest(tmp_path, manifest)
    extra.unlink()
    with pytest.raises(ValueError, match="Duplicate"):
        bundle.verify_manifest(tmp_path, {"files": manifest["files"] * 2})


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "pkg/../outside",
        "pkg/C:/file",
        "pkg/a:stream",
        "pkg/a\\b",
        "pkg/CON",
        "pkg/a.",
        "pkg//a",
        "pkg/./a",
        "/pkg/a",
    ],
)
def test_unsafe_zip_paths_rejected_before_extract(name):
    with pytest.raises(ValueError):
        bundle.validate_archive_members([zipfile.ZipInfo(name)])


def test_zip_root_collision_and_symlink_are_refused():
    for names in [["pkg/a", "pkg/A"], ["pkg/a", "other/b"], ["pkg/a", "pkg/a/b"]]:
        with pytest.raises(ValueError):
            bundle.validate_archive_members([zipfile.ZipInfo(name) for name in names])
    info = zipfile.ZipInfo("pkg/link")
    info.external_attr = 0o120777 << 16
    with pytest.raises(ValueError):
        bundle.validate_archive_members([info])
    assert bundle.validate_archive_members([zipfile.ZipInfo("pkg/safe")]) == "pkg"


def test_public_reference_credentials_and_builder_identity_are_refused(tmp_path, monkeypatch):
    path = write(tmp_path, "reference.txt", "ghp_" + "A" * 31)
    with pytest.raises(ValueError, match="Credential-like"):
        bundle.validate_public_bytes(path)
    monkeypatch.setattr(bundle.getpass, "getuser", lambda: "builder-private-identity")
    path.write_bytes("builder-private-identity".encode("utf-16-le"))
    found = bundle.privacy_findings({"reference.txt": path}, tmp_path)
    assert found[0]["classification"] == "embedded_builder_metadata"


def load_audit():
    spec = importlib.util.spec_from_file_location(
        "package_audit_tests", SCRIPTS.parent / "tests/manual_package_audit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_rejects_invalid_package_before_any_execution(tmp_path, monkeypatch):
    audit = load_audit()
    monkeypatch.setattr(audit, "capture_source", lambda repo: {"source_commit": "a" * 40})
    monkeypatch.setattr(audit, "check_versions", lambda repo: "0.1.0a4")

    def prohibited(*args, **kwargs):
        pytest.fail("An unvalidated package must not execute")

    monkeypatch.setattr(audit, "run_python", prohibited)
    (tmp_path / "dist").mkdir()
    archive = tmp_path / "dist/invalid.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../outside", "bad")
    with pytest.raises(ValueError):
        audit.audit(archive, tmp_path, "a" * 40)


def test_passive_bootstrap_prevents_each_prohibited_boundary(tmp_path, monkeypatch):
    # Fake modules let us test guard installation without importing/constructing
    # a real Core, coordinator or native backend.
    import types

    core = types.ModuleType("matlab_companion.core")
    core.Core = type("Core", (), {})
    coordinator = types.ModuleType("matlab_companion.coordinator")
    client = types.ModuleType("matlab_companion.client")
    client.CoordinatorClient = type("CoordinatorClient", (), {})
    entry = types.ModuleType("matlab_companion.__main__")

    def invoke():
        for operation in [
            core.Core,
            coordinator.spawn_coordinator,
            client.CoordinatorClient._ensure,
            subprocess.Popen,
        ]:
            with pytest.raises(AssertionError, match="Passive package admission forbids"):
                operation()

    entry.main = invoke
    package = types.ModuleType("matlab_companion")
    package.__path__ = []
    for module in [package, core, coordinator, client, entry]:
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(sys, "argv", ["guard", str(tmp_path / "guards.json"), "self-test"])
    original_popen = subprocess.Popen
    import atexit

    callbacks = []
    monkeypatch.setattr(atexit, "register", callbacks.append)
    try:
        exec(compile(bundle.PASSIVE_BOOTSTRAP, "<passive-guard-test>", "exec"), {})  # noqa: S102 - trusted audit bootstrap, fake modules
    finally:
        subprocess.Popen = original_popen
    result = json.loads((tmp_path / "guards.json").read_text(encoding="utf-8"))
    assert result == {
        "installed": True,
        "attempts": {"core": 1, "service": 1, "ensure": 1, "subprocess": 1},
    }


def test_product_wheel_source_and_installed_bytes_must_agree(tmp_path):
    installed = tmp_path / "site-packages"
    target = write(installed, "matlab_companion/__init__.py", '__version__ = "0.1.0a4"\n')
    source = {"source_files_sha256": {"src/matlab_companion/__init__.py": bundle.sha256(target)}}
    wheel = tmp_path / "product.whl"
    with zipfile.ZipFile(wheel, "w") as output:
        output.write(target, "matlab_companion/__init__.py")
    assert bundle.verify_product_wheel(wheel, source, installed)["product_files"] == 1
    target.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="Installed product bytes"):
        bundle.verify_product_wheel(wheel, source, installed)
    target.write_text('__version__ = "0.1.0a4"\n', encoding="utf-8")
    extra = write(installed, "matlab_companion/extra.py", "extra")
    with pytest.raises(ValueError, match="unexpected source files"):
        bundle.verify_product_wheel(wheel, source, installed)
    extra.unlink()
    with zipfile.ZipFile(wheel, "w") as output:
        output.writestr("matlab_companion/__init__.py", "altered")
    with pytest.raises(ValueError, match="wheel bytes"):
        bundle.verify_product_wheel(wheel, source, installed)
