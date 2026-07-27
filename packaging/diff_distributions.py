"""Compare two distribution inventories produced by analyze_distribution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _file_map(payload: dict[str, Any]) -> dict[str, int]:
    return {str(item["path"]): int(item["size_bytes"]) for item in payload["files"]}


def diff_distributions(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    baseline_files = _file_map(baseline)
    candidate_files = _file_map(candidate)
    added_names = sorted(candidate_files.keys() - baseline_files.keys(), key=str.casefold)
    removed_names = sorted(baseline_files.keys() - candidate_files.keys(), key=str.casefold)
    shared = baseline_files.keys() & candidate_files.keys()
    changed_names = sorted(
        (name for name in shared if baseline_files[name] != candidate_files[name]),
        key=str.casefold,
    )
    added = [{"path": name, "size_bytes": candidate_files[name]} for name in added_names]
    removed = [{"path": name, "size_bytes": baseline_files[name]} for name in removed_names]
    changed = [
        {
            "path": name,
            "baseline_bytes": baseline_files[name],
            "candidate_bytes": candidate_files[name],
            "delta_bytes": candidate_files[name] - baseline_files[name],
        }
        for name in changed_names
    ]
    baseline_size = int(baseline["total_size_bytes"])
    candidate_size = int(candidate["total_size_bytes"])
    reduction = baseline_size - candidate_size
    reductions = [
        {"path": item["path"], "reduced_bytes": item["size_bytes"]} for item in removed
    ] + [
        {"path": item["path"], "reduced_bytes": -item["delta_bytes"]}
        for item in changed
        if item["delta_bytes"] < 0
    ]
    additions = [
        {"path": item["path"], "added_bytes": item["size_bytes"]} for item in added
    ] + [
        {"path": item["path"], "added_bytes": item["delta_bytes"]}
        for item in changed
        if item["delta_bytes"] > 0
    ]
    return {
        "schema_version": 1,
        "baseline_name": baseline.get("distribution_name", "baseline"),
        "candidate_name": candidate.get("distribution_name", "candidate"),
        "baseline_size_bytes": baseline_size,
        "candidate_size_bytes": candidate_size,
        "reduction_bytes": reduction,
        "reduction_percent": (reduction / baseline_size * 100.0) if baseline_size else 0.0,
        "added_files": added,
        "removed_files": removed,
        "changed_files": changed,
        "major_reductions": sorted(
            reductions, key=lambda item: (-item["reduced_bytes"], item["path"].casefold())
        )[:100],
        "major_additions": sorted(
            additions, key=lambda item: (-item["added_bytes"], item["path"].casefold())
        )[:100],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    result = diff_distributions(baseline, candidate)
    print(f"Baseline bytes: {result['baseline_size_bytes']}")
    print(f"Candidate bytes: {result['candidate_size_bytes']}")
    print(f"Reduction bytes: {result['reduction_bytes']}")
    print(f"Reduction percent: {result['reduction_percent']:.6f}")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
