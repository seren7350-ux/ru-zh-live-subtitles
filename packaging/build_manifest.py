"""Generate the ignored, machine-local packaging manifest without absolute paths."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_payload(distribution: Path, executable_name: str, mode: str) -> dict[str, object]:
    files = tuple(path for path in distribution.rglob("*") if path.is_file())
    executable = distribution / executable_name
    dependencies = {
        name: importlib.metadata.version(name)
        for name in (
            "numpy",
            "onnx-asr",
            "onnxruntime",
            "sounddevice",
            "torch",
            "transformers",
        )
    }
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "git_commit": commit,
        "python": platform.python_version(),
        "pyinstaller": importlib.metadata.version("PyInstaller"),
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_mode": mode,
        "executable_sha256": sha256_file(executable),
        "dist_size_bytes": sum(path.stat().st_size for path in files),
        "file_count": len(files),
        "dependencies": dependencies,
        "models_bundled": False,
        "signing_status": "unsigned",
        "test_results": {},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution", type=Path)
    parser.add_argument("executable")
    parser.add_argument("--mode", required=True)
    parser.add_argument("--output", type=Path, default=Path("packaging-manifest.json"))
    parser.add_argument(
        "--test-result",
        action="append",
        default=[],
        metavar="NAME=RESULT",
        help="add one concise local validation result without a machine path",
    )
    args = parser.parse_args()
    payload = manifest_payload(args.distribution, args.executable, args.mode)
    for item in args.test_result:
        if "=" not in item:
            parser.error("--test-result must use NAME=RESULT")
        name, result = item.split("=", 1)
        if not name.strip() or not result.strip():
            parser.error("--test-result name and result must be non-empty")
        payload["test_results"][name.strip()] = result.strip()
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
