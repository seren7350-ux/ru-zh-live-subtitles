"""Strict build-time boundary for the independent CPU-only package."""

from __future__ import annotations

import fnmatch
import importlib.metadata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


EXPECTED_TORCH_VERSION = "2.10.0"
FORBIDDEN_CUDA_DLL_PATTERNS = (
    "c10_cuda.dll",
    "torch_cuda.dll",
    "cudart*.dll",
    "cublas*.dll",
    "cudnn*.dll",
    "cufft*.dll",
    "curand*.dll",
    "cusolver*.dll",
    "cusparse*.dll",
    "nvrtc*.dll",
    "nvjitlink*.dll",
    "cupti*.dll",
    "nvperf*.dll",
)
FORBIDDEN_DISTRIBUTIONS = frozenset({"torchvision", "triton"})
FORBIDDEN_MODEL_SUFFIXES = frozenset({".bin", ".pt", ".pth", ".safetensors"})
APPROVED_ONNX_PREFIX = "_internal/onnx_asr/preprocessors/data/"


class CpuPackagePolicyError(RuntimeError):
    """Raised before a non-CPU runtime can enter the CPU package."""


@dataclass(frozen=True)
class CpuRuntimeMetadata:
    runtime_family: str
    torch_version: str
    torch_cuda_version: None
    cuda_available: bool
    selected_translation_device: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_forbidden_cuda_name(name: str) -> bool:
    lowered = name.casefold()
    return any(fnmatch.fnmatch(lowered, pattern) for pattern in FORBIDDEN_CUDA_DLL_PATTERNS)


def forbidden_cuda_libraries(roots: Iterable[Path]) -> tuple[str, ...]:
    """Return relative, path-safe names of forbidden CUDA libraries."""

    findings: set[str] = set()
    for root in roots:
        resolved = root.resolve()
        if not resolved.is_dir():
            continue
        for path in resolved.rglob("*.dll"):
            if _is_forbidden_cuda_name(path.name):
                findings.add(f"{resolved.name}/{path.relative_to(resolved).as_posix()}")
    return tuple(sorted(findings, key=str.casefold))


def forbidden_cuda_entries(entries: Iterable[Any]) -> tuple[str, ...]:
    """Inspect PyInstaller TOC-style entries without trusting source paths."""

    findings = {
        str(entry[0]).replace("\\", "/")
        for entry in entries
        if entry and _is_forbidden_cuda_name(Path(str(entry[0])).name)
    }
    return tuple(sorted(findings, key=str.casefold))


def installed_distribution_names() -> frozenset[str]:
    names = {
        str(distribution.metadata.get("Name", "")).casefold().replace("_", "-")
        for distribution in importlib.metadata.distributions()
    }
    return frozenset(name for name in names if name)


def validate_distribution_names(names: Iterable[str]) -> None:
    normalized = {name.casefold().replace("_", "-") for name in names}
    forbidden = sorted(
        name
        for name in normalized
        if name in FORBIDDEN_DISTRIBUTIONS or name.startswith("nvidia-")
    )
    if forbidden:
        raise CpuPackagePolicyError(
            "Forbidden GPU/test distributions in CPU environment: " + ", ".join(forbidden)
        )


def validate_cpu_torch(torch_module: Any) -> CpuRuntimeMetadata:
    version = str(getattr(torch_module, "__version__", "unknown"))
    base_version, separator, local_version = version.partition("+")
    if base_version != EXPECTED_TORCH_VERSION or (
        separator and local_version.casefold() != "cpu"
    ):
        raise CpuPackagePolicyError(
            f"CPU package requires torch {EXPECTED_TORCH_VERSION} CPU build; found {version}."
        )
    cuda_version = getattr(getattr(torch_module, "version", None), "cuda", None)
    if cuda_version is not None:
        raise CpuPackagePolicyError(
            f"CPU package requires torch.version.cuda=None; found {cuda_version}."
        )
    cuda_available = bool(torch_module.cuda.is_available())
    if cuda_available:
        raise CpuPackagePolicyError("CPU package must report torch.cuda.is_available()=False.")
    return CpuRuntimeMetadata(
        runtime_family="cpu",
        torch_version=version,
        torch_cuda_version=None,
        cuda_available=False,
        selected_translation_device="cpu",
    )


def validate_cpu_environment(torch_module: Any, roots: Iterable[Path]) -> CpuRuntimeMetadata:
    metadata = validate_cpu_torch(torch_module)
    validate_distribution_names(installed_distribution_names())
    forbidden = forbidden_cuda_libraries(roots)
    if forbidden:
        raise CpuPackagePolicyError(
            "Forbidden CUDA libraries in CPU build environment: " + ", ".join(forbidden)
        )
    return metadata


def validate_pyinstaller_entries(entries: Iterable[Any]) -> None:
    forbidden = forbidden_cuda_entries(entries)
    if forbidden:
        raise CpuPackagePolicyError(
            "PyInstaller collected forbidden CUDA libraries: " + ", ".join(forbidden)
        )


def validate_cpu_distribution(root: Path) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise CpuPackagePolicyError(f"CPU distribution does not exist: {resolved}")
    missing = [
        name
        for name in ("ru-zh-subtitles.exe", "ru-zh-subtitles-console.exe")
        if not (resolved / name).is_file()
    ]
    if missing:
        raise CpuPackagePolicyError("CPU distribution is missing: " + ", ".join(missing))
    forbidden = forbidden_cuda_libraries((resolved,))
    if forbidden:
        raise CpuPackagePolicyError(
            "Forbidden CUDA libraries in CPU distribution: " + ", ".join(forbidden)
        )
    torch_cpu = tuple(resolved.rglob("torch_cpu.dll"))
    if not torch_cpu:
        raise CpuPackagePolicyError("CPU distribution has no torch_cpu.dll runtime.")
    model_weights: list[str] = []
    for path in resolved.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(resolved).as_posix()
        suffix = path.suffix.casefold()
        if suffix in FORBIDDEN_MODEL_SUFFIXES or (
            suffix == ".onnx"
            and not relative.casefold().startswith(APPROVED_ONNX_PREFIX.casefold())
        ):
            model_weights.append(relative)
    if model_weights:
        raise CpuPackagePolicyError(
            "CPU distribution contains model weights: "
            + ", ".join(sorted(model_weights, key=str.casefold))
        )
    return {
        "schema_version": 1,
        "runtime_family": "cpu",
        "cuda_library_files": [],
        "cuda_library_bytes": 0,
        "model_weight_files": [],
        "model_weight_bytes": 0,
        "torch_cpu_runtime_present": True,
    }
