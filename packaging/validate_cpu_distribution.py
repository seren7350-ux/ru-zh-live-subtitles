"""Validate and inventory an already-built CPU-only onedir."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cpu_package_policy
from analyze_distribution import analyze_distribution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    policy = cpu_package_policy.validate_cpu_distribution(args.distribution)
    inventory = analyze_distribution(args.distribution)
    payload = {**policy, "inventory": inventory}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
