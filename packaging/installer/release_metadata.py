"""Create deterministic metadata and an optional SHA manifest for a CPU onedir."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

CPU_RUNTIME_FAMILY = "cpu"
PUBLIC_DISTRIBUTION = "Windows x64 CPU-only"
GPU_DISTRIBUTION_STATUS = "internal-development-only"
APPLICATION_EXES = ("ru-zh-subtitles.exe", "ru-zh-subtitles-console.exe")
FORBIDDEN_MODEL_SUFFIXES = {".bin", ".pt", ".pth", ".safetensors"}
APPROVED_ONNX_PREFIX = "_internal/onnx_asr/preprocessors/data/"


class ReleaseMetadataError(RuntimeError):
    """Raised when the CPU distribution violates installer policy."""


def read_application_version(version_source: Path) -> str:
    tree = ast.parse(version_source.read_text(encoding="utf-8"), filename=str(version_source))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__":
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str) and value:
                        return value
    raise ReleaseMetadataError(f"Unable to read __version__ from {version_source}.")


def git_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def inspect_cpu_distribution(root: Path, *, full_manifest: bool = False) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ReleaseMetadataError(f"CPU distribution does not exist: {resolved}")
    missing_exes = [name for name in APPLICATION_EXES if not (resolved / name).is_file()]
    if missing_exes:
        raise ReleaseMetadataError("CPU distribution is missing: " + ", ".join(missing_exes))

    records: list[dict[str, object]] = []
    total_bytes = 0
    dll_count = 0
    cuda_dlls: list[str] = []
    model_weights: list[str] = []
    torch_cpu_present = False
    for path in sorted(
        (candidate for candidate in resolved.rglob("*") if candidate.is_file()),
        key=lambda item: item.as_posix().casefold(),
    ):
        relative = path.relative_to(resolved).as_posix()
        size = path.stat().st_size
        total_bytes += size
        suffix = path.suffix.casefold()
        lowered_name = path.name.casefold()
        if suffix == ".dll":
            dll_count += 1
            if lowered_name == "torch_cpu.dll":
                torch_cpu_present = True
            if any(
                token in lowered_name
                for token in (
                    "c10_cuda",
                    "torch_cuda",
                    "cudart",
                    "cublas",
                    "cudnn",
                    "cufft",
                    "curand",
                    "cusolver",
                    "cusparse",
                    "nvrtc",
                    "nvjitlink",
                    "cupti",
                    "nvperf",
                )
            ):
                cuda_dlls.append(relative)
        if suffix in FORBIDDEN_MODEL_SUFFIXES or (
            suffix == ".onnx" and not relative.casefold().startswith(APPROVED_ONNX_PREFIX)
        ):
            model_weights.append(relative)
        if full_manifest:
            records.append(
                {"path": relative, "size_bytes": size, "sha256": sha256_file(path)}
            )

    if not torch_cpu_present:
        raise ReleaseMetadataError("CPU distribution has no torch_cpu.dll.")
    if cuda_dlls:
        raise ReleaseMetadataError("CPU distribution contains CUDA DLLs: " + ", ".join(cuda_dlls))
    if model_weights:
        raise ReleaseMetadataError(
            "CPU distribution contains model weights: " + ", ".join(model_weights)
        )
    return {
        # Keep distributable metadata independent of the developer's checkout.
        "distribution_name": "ru-zh-subtitles-cpu",
        "total_bytes": total_bytes,
        "file_count": len(records) if full_manifest else sum(1 for _ in resolved.rglob("*") if _.is_file()),
        "dll_count": dll_count,
        "cuda_dll_count": 0,
        "cuda_dlls": [],
        "model_weight_count": 0,
        "model_weights": [],
        "torch_cpu_dll_present": True,
        "application_exes": list(APPLICATION_EXES),
        "files": records,
    }


def create_metadata(
    *,
    repo_root: Path,
    cpu_dist: Path,
    expected_commit: str,
    inno_version: str,
    full_manifest: bool,
) -> dict[str, object]:
    version = read_application_version(repo_root / "src" / "live_subtitles" / "__init__.py")
    commit = git_commit(repo_root)
    if commit != expected_commit:
        raise ReleaseMetadataError(
            f"Git commit mismatch: expected {expected_commit}, found {commit}."
        )
    return {
        "schema_version": 1,
        "application_name": "Russian–Chinese Live Subtitles",
        "application_version": version,
        "version_info_version": f"{version}.0",
        "git_commit": commit,
        "distribution_candidate": PUBLIC_DISTRIBUTION,
        "runtime_family": CPU_RUNTIME_FAMILY,
        "gpu_distribution_status": GPU_DISTRIBUTION_STATUS,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "inno_setup_version": inno_version,
        "cpu_distribution": inspect_cpu_distribution(cpu_dist, full_manifest=full_manifest),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--cpu-dist", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--inno-version", default="unknown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full-manifest", action="store_true")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args(argv)
    if args.version_only:
        print(read_application_version(args.repo_root / "src" / "live_subtitles" / "__init__.py"))
        return 0
    if args.cpu_dist is None or args.expected_commit is None:
        parser.error("--cpu-dist and --expected-commit are required unless --version-only is used")
    payload = create_metadata(
        repo_root=args.repo_root.resolve(),
        cpu_dist=args.cpu_dist.resolve(),
        expected_commit=args.expected_commit,
        inno_version=args.inno_version,
        full_manifest=args.full_manifest,
    )
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
