"""Create and validate path-safe provenance for the CPU-only onedir build."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
RUNTIME_FAMILY = "cpu"
BUILD_PLATFORM = "windows-x64"
SPEC_PATH = "packaging/combined_cpu.spec"
METADATA_NAME = "CPU_BUILD_METADATA.json"
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+|(?:^|[\s\"'])/(?:Users|home)/)",
    re.IGNORECASE,
)
REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "application_version",
        "git_commit",
        "runtime_family",
        "working_tree_clean",
        "build_platform",
        "spec",
    }
)


class CpuBuildProvenanceError(RuntimeError):
    """Raised when CPU build provenance cannot be trusted."""


def read_application_version(version_source: Path) -> str:
    """Read the single application version without importing the package."""

    tree = ast.parse(version_source.read_text(encoding="utf-8"), filename=str(version_source))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str) and value:
                        return value
    raise CpuBuildProvenanceError("Unable to read the application version.")


def _run_git(repo_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CpuBuildProvenanceError("Unable to inspect Git build provenance.") from exc
    return completed.stdout


def git_commit(repo_root: Path) -> str:
    commit = _run_git(repo_root, "rev-parse", "HEAD").strip()
    if SHA_PATTERN.fullmatch(commit) is None:
        raise CpuBuildProvenanceError("Git HEAD is not a 40-character lowercase SHA.")
    return commit


def git_status(repo_root: Path) -> tuple[str, ...]:
    output = _run_git(
        repo_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    return tuple(line for line in output.splitlines() if line)


def _safe_status_entry(line: str) -> str:
    status = line[:2] if len(line) >= 2 else "??"
    relative = line[3:] if len(line) >= 4 else "<unknown>"
    relative = relative.replace("\r", "?").replace("\n", "?")
    if ABSOLUTE_PATH_PATTERN.search(relative):
        relative = "<invalid-path>"
    return f"{status} {relative}"


def ensure_clean_worktree(repo_root: Path) -> None:
    changes = git_status(repo_root)
    if changes:
        details = "; ".join(_safe_status_entry(line) for line in changes)
        raise CpuBuildProvenanceError(f"Git working tree is not clean: {details}")


def create_metadata(repo_root: Path) -> dict[str, object]:
    resolved = repo_root.resolve()
    ensure_clean_worktree(resolved)
    version = read_application_version(
        resolved / "src" / "live_subtitles" / "__init__.py"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "application_version": version,
        "git_commit": git_commit(resolved),
        "runtime_family": RUNTIME_FAMILY,
        "working_tree_clean": True,
        "build_platform": BUILD_PLATFORM,
        "spec": SPEC_PATH,
    }


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_strings(item)


def validate_metadata(
    payload: Mapping[str, object],
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
) -> dict[str, object]:
    missing = sorted(REQUIRED_FIELDS.difference(payload))
    if missing:
        raise CpuBuildProvenanceError(
            "CPU build provenance is missing: " + ", ".join(missing)
        )
    unexpected = sorted(set(payload).difference(REQUIRED_FIELDS))
    if unexpected:
        raise CpuBuildProvenanceError(
            "CPU build provenance contains unsupported fields: " + ", ".join(unexpected)
        )
    if payload["schema_version"] != SCHEMA_VERSION:
        raise CpuBuildProvenanceError("CPU build provenance schema_version is invalid.")
    version = payload["application_version"]
    if not isinstance(version, str) or not version:
        raise CpuBuildProvenanceError("CPU build provenance version is invalid.")
    if expected_version is not None and version != expected_version:
        raise CpuBuildProvenanceError(
            f"CPU build provenance version mismatch: expected {expected_version}, found {version}."
        )
    commit = payload["git_commit"]
    if not isinstance(commit, str) or SHA_PATTERN.fullmatch(commit) is None:
        raise CpuBuildProvenanceError(
            "CPU build provenance commit is not a 40-character lowercase SHA."
        )
    if expected_commit is not None:
        if SHA_PATTERN.fullmatch(expected_commit) is None:
            raise CpuBuildProvenanceError("Expected commit is not a lowercase SHA.")
        if commit != expected_commit:
            raise CpuBuildProvenanceError(
                f"CPU build provenance commit mismatch: expected {expected_commit}, found {commit}."
            )
    if payload["runtime_family"] != RUNTIME_FAMILY:
        raise CpuBuildProvenanceError("CPU build provenance runtime_family is not cpu.")
    if payload["working_tree_clean"] is not True:
        raise CpuBuildProvenanceError("CPU build provenance working_tree_clean is not true.")
    if payload["build_platform"] != BUILD_PLATFORM:
        raise CpuBuildProvenanceError("CPU build provenance build_platform is invalid.")
    if payload["spec"] != SPEC_PATH:
        raise CpuBuildProvenanceError("CPU build provenance spec is invalid.")
    if any(ABSOLUTE_PATH_PATTERN.search(text) for text in _walk_strings(payload)):
        raise CpuBuildProvenanceError("CPU build provenance contains an absolute user path.")
    return dict(payload)


def load_metadata(
    path: Path,
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
) -> dict[str, object]:
    if not path.is_file():
        raise CpuBuildProvenanceError(f"CPU build provenance is missing: {METADATA_NAME}")
    try:
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raise CpuBuildProvenanceError("CPU build provenance must not contain a UTF-8 BOM.")
        payload = json.loads(raw.decode("utf-8"))
    except CpuBuildProvenanceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CpuBuildProvenanceError("CPU build provenance is not valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise CpuBuildProvenanceError("CPU build provenance root must be an object.")
    return validate_metadata(
        payload,
        expected_version=expected_version,
        expected_commit=expected_commit,
    )


def write_metadata(repo_root: Path, output: Path) -> dict[str, object]:
    payload = create_metadata(repo_root)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.write_text(rendered, encoding="utf-8", newline="\n")
    temporary.replace(output)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = write_metadata(args.repo_root, args.output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
