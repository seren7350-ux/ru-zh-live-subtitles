"""Version-locked safety policy for experimental Torch/CUDA package pruning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

EXPECTED_TORCH_VERSION = "2.12.1+cu130"
EXPECTED_CUDA_VERSION = "13.0"
LARGE_DLL_THRESHOLD_BYTES = 20 * 1024 * 1024

RETAINED_BINARY_PATTERNS = (
    "c10.dll",
    "c10_cuda.dll",
    "cublas64_*.dll",
    "cublaslt64_*.dll",
    "cudart64_*.dll",
    "torch_cpu.dll",
    "torch_cuda.dll",
    "torch_python.dll",
)

# Baseline is intentionally complete. Optimized exclusions remain empty until
# an evidence ID, isolated experiment, and real NLLB CUDA validation approve one.
BASELINE_EXCLUDED_BINARY_NAMES: frozenset[str] = frozenset()
OPTIMIZED_EXCLUDED_BINARY_NAMES: frozenset[str] = frozenset()
EXCLUSION_REASONS: dict[str, str] = {}

# Experiment 1 removes only installer bookkeeping from copied distribution
# metadata. METADATA, entry points, licenses, notices, and SBOMs are retained.
OPTIMIZED_EXCLUDED_DATA_BASENAMES = frozenset(
    {
        "DELVEWHEEL",
        "INSTALLER",
        "RECORD",
        "REQUESTED",
        "WHEEL",
        "direct_url.json",
        "top_level.txt",
    }
)
DATA_EXCLUSION_REASONS = {
    "DELVEWHEEL": "PKG-SIZE-E1: wheel repair bookkeeping, not runtime metadata",
    "INSTALLER": "PKG-SIZE-E1: installer provenance, not runtime metadata",
    "RECORD": "PKG-SIZE-E1: installed-file inventory, not used by frozen imports",
    "REQUESTED": "PKG-SIZE-E1: installer request marker, not runtime metadata",
    "WHEEL": "PKG-SIZE-E1: wheel build metadata, not runtime metadata",
    "direct_url.json": "PKG-SIZE-E1: local installation provenance",
    "top_level.txt": "PKG-SIZE-E1: setuptools installer hint",
}

KNOWN_TORCH_DLL_PREFIXES = (
    "asmjit",
    "c10",
    "caffe2",
    "clog",
    "cpuinfo",
    "cublas",
    "cudart",
    "cuda",
    "cudnn",
    "cufft",
    "cupti",
    "curand",
    "cusolver",
    "cusparse",
    "fbgemm",
    "libiomp",
    "nvjitlink",
    "nvperf",
    "nvrtc",
    "nvtoolsext",
    "shm",
    "torch",
    "uv",
)


@dataclass(frozen=True)
class ProfileValidation:
    profile: str
    excluded_binary_names: frozenset[str]


def excluded_binary_names(profile: str) -> frozenset[str]:
    if profile == "baseline":
        return BASELINE_EXCLUDED_BINARY_NAMES
    if profile == "optimized":
        return OPTIMIZED_EXCLUDED_BINARY_NAMES
    raise ValueError(f"Unknown packaging optimization profile: {profile}")


def excluded_data_basenames(profile: str) -> frozenset[str]:
    if profile == "baseline":
        return frozenset()
    if profile == "optimized":
        return OPTIMIZED_EXCLUDED_DATA_BASENAMES
    raise ValueError(f"Unknown packaging optimization profile: {profile}")


def filter_collected_datas(profile: str, datas: Iterable[Any]) -> list[Any]:
    """Filter approved dist-info bookkeeping while retaining runtime metadata."""

    excluded = excluded_data_basenames(profile)
    if not excluded:
        return list(datas)
    retained = []
    for entry in datas:
        destination = str(entry[0]).replace("\\", "/")
        basename = destination.rsplit("/", 1)[-1]
        is_dist_info = ".dist-info/" in destination.casefold()
        if is_dist_info and basename in excluded:
            continue
        retained.append(entry)
    return retained


def validate_runtime_versions(torch_version: str, cuda_version: str) -> None:
    if torch_version != EXPECTED_TORCH_VERSION:
        raise RuntimeError(
            f"Torch version mismatch: expected {EXPECTED_TORCH_VERSION}, got {torch_version}"
        )
    if cuda_version != EXPECTED_CUDA_VERSION:
        raise RuntimeError(
            f"CUDA version mismatch: expected {EXPECTED_CUDA_VERSION}, got {cuda_version}"
        )


def unknown_large_dlls(paths: Iterable[Path]) -> list[str]:
    unknown: list[str] = []
    for path in paths:
        name = path.name.casefold()
        if path.stat().st_size < LARGE_DLL_THRESHOLD_BYTES:
            continue
        if not any(name.startswith(prefix) for prefix in KNOWN_TORCH_DLL_PREFIXES):
            unknown.append(path.name)
    return sorted(unknown, key=str.casefold)


def validate_profile(
    profile: str,
    *,
    torch_version: str,
    cuda_version: str,
    torch_dlls: Iterable[Path],
) -> ProfileValidation:
    validate_runtime_versions(torch_version, cuda_version)
    dlls = tuple(torch_dlls)
    unknown = unknown_large_dlls(dlls)
    if unknown:
        raise RuntimeError("Unknown large Torch DLLs require review: " + ", ".join(unknown))
    available = {path.name.casefold() for path in dlls}
    excluded = excluded_binary_names(profile)
    missing = sorted(name for name in excluded if name.casefold() not in available)
    if missing:
        raise RuntimeError("Approved exclusions are not present: " + ", ".join(missing))
    unexplained = sorted(name for name in excluded if name not in EXCLUSION_REASONS)
    if unexplained:
        raise RuntimeError("Approved exclusions lack evidence: " + ", ".join(unexplained))
    missing_data_reasons = sorted(
        name
        for name in excluded_data_basenames(profile)
        if name not in DATA_EXCLUSION_REASONS
    )
    if missing_data_reasons:
        raise RuntimeError(
            "Approved data exclusions lack evidence: " + ", ".join(missing_data_reasons)
        )
    return ProfileValidation(profile=profile, excluded_binary_names=excluded)
