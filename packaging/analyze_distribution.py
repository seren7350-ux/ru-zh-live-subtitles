"""Create a path-safe, reproducible size inventory for one onedir build."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


class DistributionAnalysisError(ValueError):
    """Raised when a distribution is invalid or contains forbidden assets."""


MODEL_WEIGHT_SUFFIXES = {
    ".bin",
    ".flac",
    ".mp3",
    ".pt",
    ".pth",
    ".safetensors",
    ".wav",
}

CUDA_DLL_MARKERS = (
    "c10_cuda",
    "cublas",
    "cudart",
    "cuda",
    "cudnn",
    "cufft",
    "curand",
    "cusolver",
    "cusparse",
    "nvjitlink",
    "nvrtc",
    "nvtoolsext",
    "nvtx",
    "torch_cuda",
)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_under(relative: str, *prefixes: str) -> bool:
    lowered = relative.casefold()
    return any(
        lowered == prefix.casefold().rstrip("/")
        or lowered.startswith(prefix.casefold().rstrip("/") + "/")
        for prefix in prefixes
    )


def _sum_matching(files: Iterable[dict[str, Any]], predicate: Any) -> int:
    return sum(int(item["size_bytes"]) for item in files if predicate(item["path"]))


def _is_allowed_preprocessor_onnx(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        "onnx_asr/preprocessors/data" in relative.replace("\\", "/")
        and path.name.startswith("resample_")
        and path.name.endswith("_16.onnx")
    )


def forbidden_assets(files: Iterable[dict[str, Any]]) -> list[str]:
    """Return model/cache/audio assets that must never enter a distribution."""

    rejected: list[str] = []
    for item in files:
        relative = str(item["path"])
        path = PurePosixPath(relative)
        lowered = relative.casefold()
        if path.suffix.casefold() in MODEL_WEIGHT_SUFFIXES:
            rejected.append(relative)
        elif path.suffix.casefold() == ".onnx" and not _is_allowed_preprocessor_onnx(
            relative
        ):
            rejected.append(relative)
        elif any(
            marker in lowered
            for marker in ("models--", "/snapshots/", "/.cache/", "/model_cache/")
        ):
            rejected.append(relative)
    return sorted(set(rejected), key=str.casefold)


def analyze_distribution(root: Path) -> dict[str, Any]:
    """Return a JSON-safe inventory containing relative paths only."""

    root = root.resolve()
    if not root.is_dir():
        raise DistributionAnalysisError(f"Distribution directory does not exist: {root}")

    paths = sorted((path for path in root.rglob("*") if path.is_file()), key=str)
    files = [
        {"path": _relative(path, root), "size_bytes": path.stat().st_size}
        for path in paths
    ]
    rejected = forbidden_assets(files)
    if rejected:
        raise DistributionAnalysisError(
            "Forbidden model/cache/audio assets found: " + ", ".join(rejected)
        )

    extension_sizes: dict[str, int] = defaultdict(int)
    top_level_sizes: dict[str, int] = defaultdict(int)
    for item in files:
        relative = PurePosixPath(str(item["path"]))
        extension = relative.suffix.casefold() or "<none>"
        extension_sizes[extension] += int(item["size_bytes"])
        top_level = relative.parts[0] if len(relative.parts) > 1 else "<root>"
        top_level_sizes[top_level] += int(item["size_bytes"])

    def suffix(relative: str) -> str:
        return PurePosixPath(relative).suffix.casefold()

    def basename(relative: str) -> str:
        return PurePosixPath(relative).name.casefold()

    categories = {
        "torch_total_bytes": _sum_matching(
            files, lambda path: _is_under(path, "_internal/torch", "torch")
        ),
        "torch_lib_bytes": _sum_matching(
            files, lambda path: _is_under(path, "_internal/torch/lib", "torch/lib")
        ),
        "cuda_dll_bytes": _sum_matching(
            files,
            lambda path: suffix(path) == ".dll"
            and _is_under(path, "_internal/torch/lib", "torch/lib")
            and any(marker in basename(path) for marker in CUDA_DLL_MARKERS),
        ),
        "onnxruntime_bytes": _sum_matching(
            files, lambda path: _is_under(path, "_internal/onnxruntime", "onnxruntime")
        ),
        "transformers_bytes": _sum_matching(
            files, lambda path: _is_under(path, "_internal/transformers", "transformers")
        ),
        "tk_tcl_bytes": _sum_matching(
            files,
            lambda path: _is_under(path, "_internal/_tk_data", "_internal/_tcl_data")
            or basename(path) in {"tk86t.dll", "tcl86t.dll"},
        ),
        "numpy_bytes": _sum_matching(
            files,
            lambda path: _is_under(
                path, "_internal/numpy", "_internal/numpy.libs", "numpy", "numpy.libs"
            ),
        ),
        "onnx_asr_bytes": _sum_matching(
            files, lambda path: _is_under(path, "_internal/onnx_asr", "onnx_asr")
        ),
        "sounddevice_portaudio_bytes": _sum_matching(
            files,
            lambda path: _is_under(
                path,
                "_internal/_sounddevice_data",
                "_sounddevice_data",
                "_internal/sounddevice",
            )
            or basename(path).startswith("_sounddevice"),
        ),
        "licenses_bytes": _sum_matching(
            files,
            lambda path: any(
                part.casefold() in {"license", "licenses"}
                for part in PurePosixPath(path).parts
            )
            or basename(path).startswith(("license", "copying")),
        ),
        "readme_notice_bytes": _sum_matching(
            files,
            lambda path: basename(path).startswith(("readme", "notice"))
            or "third_party_notices" in basename(path),
        ),
    }

    largest = sorted(
        files, key=lambda item: (-int(item["size_bytes"]), str(item["path"]).casefold())
    )[:100]
    return {
        "schema_version": 1,
        "distribution_name": root.name,
        "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
        "file_count": len(files),
        "directory_count": sum(1 for path in root.rglob("*") if path.is_dir()),
        "exe_count": sum(suffix(str(item["path"])) == ".exe" for item in files),
        "dll_count": sum(suffix(str(item["path"])) == ".dll" for item in files),
        "pyd_count": sum(suffix(str(item["path"])) == ".pyd" for item in files),
        "python_file_count": sum(
            suffix(str(item["path"])) in {".py", ".pyc"} for item in files
        ),
        "zip_pyz_files": [
            item
            for item in files
            if suffix(str(item["path"])) in {".zip", ".pyz"}
        ],
        "top_level_sizes": dict(sorted(top_level_sizes.items(), key=lambda item: item[0])),
        "extension_sizes": dict(sorted(extension_sizes.items(), key=lambda item: item[0])),
        "categories": categories,
        "largest_files": largest,
        "files": files,
        "forbidden_assets": [],
    }


def write_json(payload: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def print_summary(payload: dict[str, Any]) -> None:
    print(f"Distribution: {payload['distribution_name']}")
    print(f"Total bytes: {payload['total_size_bytes']}")
    print(
        "Files/directories/EXE/DLL/PYD/Python: "
        f"{payload['file_count']}/{payload['directory_count']}/"
        f"{payload['exe_count']}/{payload['dll_count']}/"
        f"{payload['pyd_count']}/{payload['python_file_count']}"
    )
    for name, size in payload["categories"].items():
        print(f"{name}: {size}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()
    try:
        payload = analyze_distribution(args.distribution)
    except DistributionAnalysisError as exc:
        parser.error(str(exc))
    print_summary(payload)
    if args.json_output:
        write_json(payload, args.json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
