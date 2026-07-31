from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_PATH = PROJECT_ROOT / "packaging" / "cpu_build_provenance.py"


def load_provenance() -> Any:
    spec = importlib.util.spec_from_file_location("cpu_build_provenance_test", PROVENANCE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def make_git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    package = repo / "src" / "live_subtitles"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text("build/\ndist/\ndata/\n.venv*/\n", encoding="utf-8")
    git(repo, "init", "-b", "main")
    git(repo, "config", "--local", "user.name", "Provenance Test")
    git(repo, "config", "--local", "user.email", "provenance@example.invalid")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    return repo, git(repo, "rev-parse", "HEAD")


def test_clean_repo_generates_fixed_path_safe_utf8_schema(tmp_path: Path) -> None:
    provenance = load_provenance()
    repo, commit = make_git_repo(tmp_path)
    output = repo / "build" / provenance.METADATA_NAME
    payload = provenance.write_metadata(repo, output)

    assert payload == {
        "schema_version": 1,
        "application_version": "0.2.0",
        "git_commit": commit,
        "runtime_family": "cpu",
        "working_tree_clean": True,
        "build_platform": "windows-x64",
        "spec": "packaging/combined_cpu.spec",
    }
    raw = output.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    serialized = raw.decode("utf-8")
    assert str(repo) not in serialized
    assert "Provenance Test" not in serialized
    assert "provenance@example.invalid" not in serialized
    assert "remote" not in serialized.casefold()


@pytest.mark.parametrize("dirty_kind", ["modified", "staged", "untracked"])
def test_dirty_repo_rejects_metadata_with_relative_status_only(
    tmp_path: Path, dirty_kind: str
) -> None:
    provenance = load_provenance()
    repo, _commit = make_git_repo(tmp_path)
    tracked = repo / "src" / "live_subtitles" / "__init__.py"
    if dirty_kind == "modified":
        tracked.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
    elif dirty_kind == "staged":
        tracked.write_text('__version__ = "0.1.1"\n', encoding="utf-8")
        git(repo, "add", tracked.relative_to(repo).as_posix())
    else:
        (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(provenance.CpuBuildProvenanceError) as raised:
        provenance.write_metadata(repo, repo / "build" / provenance.METADATA_NAME)
    message = str(raised.value)
    assert "not clean" in message
    assert str(repo) not in message
    assert any(code in message for code in (" M ", "M  ", "?? "))


def test_ignored_local_outputs_do_not_make_repo_dirty(tmp_path: Path) -> None:
    provenance = load_provenance()
    repo, _commit = make_git_repo(tmp_path)
    for relative in ("dist/candidate.bin", "data/log.txt", ".venv-cpu/marker"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ignored", encoding="utf-8")
    assert provenance.git_status(repo) == ()
    assert provenance.create_metadata(repo)["working_tree_clean"] is True


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_commit", "A" * 40, "lowercase SHA"),
        ("git_commit", "a" * 39, "lowercase SHA"),
        ("runtime_family", "gpu", "runtime_family"),
        ("working_tree_clean", False, "working_tree_clean"),
        ("build_platform", "linux-x64", "build_platform"),
        ("spec", "packaging/combined.spec", "spec"),
    ],
)
def test_provenance_validation_rejects_invalid_boundary(
    field: str, value: object, message: str
) -> None:
    provenance = load_provenance()
    payload = {
        "schema_version": 1,
        "application_version": "0.2.0",
        "git_commit": "a" * 40,
        "runtime_family": "cpu",
        "working_tree_clean": True,
        "build_platform": "windows-x64",
        "spec": "packaging/combined_cpu.spec",
    }
    payload[field] = value
    with pytest.raises(provenance.CpuBuildProvenanceError, match=message):
        provenance.validate_metadata(payload)


def test_provenance_rejects_missing_extra_and_absolute_path_fields() -> None:
    provenance = load_provenance()
    payload = {
        "schema_version": 1,
        "application_version": "0.2.0",
        "git_commit": "a" * 40,
        "runtime_family": "cpu",
        "working_tree_clean": True,
        "build_platform": "windows-x64",
        "spec": "packaging/combined_cpu.spec",
    }
    missing = dict(payload)
    missing.pop("spec")
    with pytest.raises(provenance.CpuBuildProvenanceError, match="missing"):
        provenance.validate_metadata(missing)
    extra = dict(payload, repository=r"C:\Users\person\repo")
    with pytest.raises(provenance.CpuBuildProvenanceError, match="unsupported"):
        provenance.validate_metadata(extra)


def test_provenance_loader_rejects_utf8_bom(tmp_path: Path) -> None:
    provenance = load_provenance()
    path = tmp_path / provenance.METADATA_NAME
    path.write_bytes(b"\xef\xbb\xbf{}")
    with pytest.raises(provenance.CpuBuildProvenanceError, match="BOM"):
        provenance.load_metadata(path)


def test_cli_writes_metadata_from_real_clean_git_repo(tmp_path: Path) -> None:
    repo, commit = make_git_repo(tmp_path)
    output = repo / "build" / "CPU_BUILD_METADATA.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(PROVENANCE_PATH),
            "--repo-root",
            str(repo),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["git_commit"] == commit
