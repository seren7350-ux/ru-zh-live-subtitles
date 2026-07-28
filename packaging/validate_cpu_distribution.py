"""Validate and inventory an already-built CPU-only onedir."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cpu_build_provenance
import cpu_package_policy
from analyze_distribution import analyze_distribution


def validate_distribution(
    distribution: Path,
    *,
    repo_root: Path,
    expected_commit: str,
) -> dict[str, object]:
    resolved_repo = repo_root.resolve()
    current_head = cpu_build_provenance.git_commit(resolved_repo)
    if current_head != expected_commit:
        raise cpu_build_provenance.CpuBuildProvenanceError(
            f"Git commit mismatch: expected {expected_commit}, found {current_head}."
        )
    version = cpu_build_provenance.read_application_version(
        resolved_repo / "src" / "live_subtitles" / "__init__.py"
    )
    provenance = cpu_build_provenance.load_metadata(
        distribution / cpu_build_provenance.METADATA_NAME,
        expected_version=version,
        expected_commit=current_head,
    )
    policy = cpu_package_policy.validate_cpu_distribution(distribution)
    inventory = analyze_distribution(distribution)
    return {**policy, "cpu_build_provenance": provenance, "inventory": inventory}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-commit")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    expected_commit = args.expected_commit or cpu_build_provenance.git_commit(args.repo_root)
    payload = validate_distribution(
        args.distribution.resolve(),
        repo_root=args.repo_root,
        expected_commit=expected_commit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
