"""Create deterministic metadata and an optional SHA manifest for a CPU onedir."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath

PACKAGING_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGING_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGING_ROOT))

import cpu_build_provenance

CPU_RUNTIME_FAMILY = "cpu"
PUBLIC_DISTRIBUTION = "Windows x64 CPU-only"
GPU_DISTRIBUTION_STATUS = "internal-development-only"
GIGAAM_MODEL_ID = "ai-sage/GigaAM-Multilingual"
GIGAAM_VARIANT = "large_ctc"
GIGAAM_REVISION = "3905cd51c3ed4e88c8edf33f3302969ba480a327"
NLLB_REVISION = "f8d333a098d19b4fd9a8b18f94170487ad3f821d"
APPLICATION_EXES = ("ru-zh-subtitles.exe", "ru-zh-subtitles-console.exe")
FORBIDDEN_MODEL_SUFFIXES = {".bin", ".pt", ".pth", ".safetensors"}
APPROVED_ONNX_PREFIX = "_internal/onnx_asr/preprocessors/data/"


class ReleaseMetadataError(RuntimeError):
    """Raised when the CPU distribution violates installer policy."""


def read_application_version(version_source: Path) -> str:
    try:
        return cpu_build_provenance.read_application_version(version_source)
    except cpu_build_provenance.CpuBuildProvenanceError as exc:
        raise ReleaseMetadataError(str(exc)) from exc


def git_commit(repo_root: Path) -> str:
    try:
        return cpu_build_provenance.git_commit(repo_root)
    except cpu_build_provenance.CpuBuildProvenanceError as exc:
        raise ReleaseMetadataError(str(exc)) from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def read_model_bundle_metadata(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseMetadataError(f"Model bundle metadata cannot be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseMetadataError("Model bundle metadata must be a JSON object.")
    required = {
        "schema_version": 1,
        "bundle_type": "offline-model-assets",
        "self_contained": True,
        "offline_ready": True,
        "gigaam_model_id": GIGAAM_MODEL_ID,
        "gigaam_variant": GIGAAM_VARIANT,
        "gigaam_revision": GIGAAM_REVISION,
        "nllb_revision": NLLB_REVISION,
    }
    for field, expected in required.items():
        if payload.get(field) != expected:
            raise ReleaseMetadataError(
                f"Model bundle metadata {field} must be {expected!r}."
            )
    for field in ("manifest_sha256", "gigaam_revision", "nllb_revision"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            raise ReleaseMetadataError(f"Model bundle metadata is missing {field}.")
    if re.fullmatch(r"[0-9a-f]{64}", str(payload["manifest_sha256"])) is None:
        raise ReleaseMetadataError("Model bundle metadata has invalid manifest_sha256.")
    for field in ("gigaam_revision", "nllb_revision"):
        if re.fullmatch(r"[0-9a-f]{40}", str(payload[field])) is None:
            raise ReleaseMetadataError(f"Model bundle metadata has invalid {field}.")
    for field in ("file_count", "total_bytes"):
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ReleaseMetadataError(f"Model bundle metadata has invalid {field}.")

    def contains_absolute_path(value: object) -> bool:
        if isinstance(value, dict):
            return any(contains_absolute_path(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_absolute_path(item) for item in value)
        if isinstance(value, str):
            return (
                PureWindowsPath(value).is_absolute()
                or PurePosixPath(value).is_absolute()
            )
        return False

    if contains_absolute_path(payload):
        raise ReleaseMetadataError("Model bundle metadata contains an absolute path.")
    return payload


def inspect_cpu_distribution(
    root: Path,
    *,
    expected_version: str | None = None,
    expected_commit: str | None = None,
    full_manifest: bool = False,
) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ReleaseMetadataError(f"CPU distribution does not exist: {resolved}")
    missing_exes = [name for name in APPLICATION_EXES if not (resolved / name).is_file()]
    if missing_exes:
        raise ReleaseMetadataError("CPU distribution is missing: " + ", ".join(missing_exes))
    try:
        provenance = cpu_build_provenance.load_metadata(
            resolved / cpu_build_provenance.METADATA_NAME,
            expected_version=expected_version,
            expected_commit=expected_commit,
        )
    except cpu_build_provenance.CpuBuildProvenanceError as exc:
        raise ReleaseMetadataError(str(exc)) from exc

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
        "cpu_build_provenance": provenance,
        "files": records,
    }


def create_metadata(
    *,
    repo_root: Path,
    cpu_dist: Path,
    expected_commit: str,
    inno_version: str,
    model_bundle_metadata: Path,
    full_manifest: bool,
) -> dict[str, object]:
    version = read_application_version(repo_root / "src" / "live_subtitles" / "__init__.py")
    commit = git_commit(repo_root)
    if commit != expected_commit:
        raise ReleaseMetadataError(
            f"Git commit mismatch: expected {expected_commit}, found {commit}."
        )
    try:
        cpu_build_provenance.ensure_clean_worktree(repo_root)
    except cpu_build_provenance.CpuBuildProvenanceError as exc:
        raise ReleaseMetadataError(str(exc)) from exc
    distribution = inspect_cpu_distribution(
        cpu_dist,
        expected_version=version,
        expected_commit=commit,
        full_manifest=full_manifest,
    )
    model_bundle = read_model_bundle_metadata(model_bundle_metadata)
    return {
        "schema_version": 2,
        "application_name": "Russian–Chinese Live Subtitles",
        "application_version": version,
        "version_info_version": f"{version}.0",
        "git_commit": commit,
        "distribution_candidate": PUBLIC_DISTRIBUTION,
        "runtime_family": CPU_RUNTIME_FAMILY,
        "gpu_distribution_status": GPU_DISTRIBUTION_STATUS,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "inno_setup_version": inno_version,
        "self_contained": True,
        "offline_ready": True,
        "model_bundle": model_bundle,
        "cpu_build_provenance": distribution["cpu_build_provenance"],
        "cpu_distribution": distribution,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--cpu-dist", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--inno-version", default="unknown")
    parser.add_argument("--model-bundle-metadata", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--full-manifest", action="store_true")
    parser.add_argument("--version-only", action="store_true")
    args = parser.parse_args(argv)
    if args.version_only:
        print(read_application_version(args.repo_root / "src" / "live_subtitles" / "__init__.py"))
        return 0
    if (
        args.cpu_dist is None
        or args.expected_commit is None
        or args.model_bundle_metadata is None
    ):
        parser.error(
            "--cpu-dist, --expected-commit and --model-bundle-metadata are required "
            "unless --version-only is used"
        )
    payload = create_metadata(
        repo_root=args.repo_root.resolve(),
        cpu_dist=args.cpu_dist.resolve(),
        expected_commit=args.expected_commit,
        inno_version=args.inno_version,
        model_bundle_metadata=args.model_bundle_metadata.resolve(),
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
