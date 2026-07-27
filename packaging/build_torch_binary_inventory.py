"""Build a relative-path Torch/CUDA binary evidence inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


def classify_binary(name: str) -> str:
    lowered = name.casefold()
    rules = (
        (("cublaslt",), "cuBLASLt"),
        (("cublas",), "cuBLAS"),
        (("cudnn",), "cuDNN"),
        (("cufft",), "cuFFT"),
        (("curand",), "cuRAND"),
        (("cusolver",), "cuSOLVER"),
        (("cusparse",), "cuSPARSE"),
        (("cudart",), "CUDA runtime"),
        (("nvjitlink",), "nvJitLink"),
        (("nvrtc", "caffe2_nvrtc"), "NVRTC"),
        (("nvtoolsext", "cupti", "nvperf"), "profiling/NVTX"),
        (("tensorpipe", "shm", "uv.dll"), "distributed/TensorPipe"),
        (("c10_cuda", "torch_cuda"), "Torch CUDA core"),
        (("torch_cpu", "libiomp"), "Torch CPU"),
        (("c10", "torch.dll", "torch_python", "torch_global_deps"), "Torch core"),
    )
    for prefixes, category in rules:
        if any(marker in lowered for marker in prefixes):
            return category
    return "unknown"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_inventory(
    distribution: Path,
    loaded_modules: Path,
    direct_imports: Path,
    recursive_closure: Path,
) -> dict[str, Any]:
    root = distribution.resolve()
    torch_lib = root / "_internal" / "torch" / "lib"
    if not torch_lib.is_dir():
        raise ValueError("Torch library directory is missing")

    loaded_payload = _read_json(loaded_modules)
    loaded = {
        str(item["relative_path"]).casefold(): item
        for item in loaded_payload.get("modules", [])
        if item.get("category") == "dist" and item.get("relative_path")
    }
    direct = _read_json(direct_imports)
    closure_payload = _read_json(recursive_closure)
    static_closure = {
        str(path).casefold() for path in closure_payload.get("static_files", [])
    }

    dependents: dict[str, set[str]] = {}
    for source, relationships in direct.items():
        for kind in ("imports", "delay_imports"):
            for relationship in relationships.get(kind, []):
                target = relationship.get("path")
                if target:
                    dependents.setdefault(str(target).casefold(), set()).add(source)

    files: list[dict[str, Any]] = []
    for path in sorted(torch_lib.glob("*.dll"), key=lambda item: item.name.casefold()):
        relative = path.relative_to(root).as_posix()
        observed = loaded.get(relative.casefold())
        category = classify_binary(path.name)
        is_loaded = observed is not None
        in_static_closure = relative.casefold() in static_closure
        evidence = []
        if is_loaded:
            evidence.append("observed in the three-run dynamic union")
        if in_static_closure:
            evidence.append("reachable from the EXE/PYD PE static closure")
        if not evidence:
            evidence.append("not proven removable; dynamic LoadLibrary remains possible")
        files.append(
            {
                "basename": path.name,
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "category": category,
                "actually_loaded": is_loaded,
                "first_loaded_stage": observed.get("first_stage") if observed else None,
                "in_pe_static_closure": in_static_closure,
                "directly_required_by": sorted(
                    dependents.get(relative.casefold(), ()), key=str.casefold
                ),
                "included_in_baseline": True,
                "pruning_candidate": False,
                "pruning_evidence": "; ".join(evidence),
                "risk": "critical" if is_loaded or category == "unknown" else "high",
                "test_result": "retained; no approved binary exclusion",
            }
        )

    return {
        "schema_version": 1,
        "paths_are_distribution_relative": True,
        "dynamic_runs": 3,
        "candidate_policy": (
            "A DLL is not a candidate unless all three runs omit it, PE/static and "
            "source evidence are explainable, and an isolated real CUDA test passes."
        ),
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--loaded-modules", type=Path, required=True)
    parser.add_argument("--direct-imports", type=Path, required=True)
    parser.add_argument("--recursive-closure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_inventory(
        args.distribution,
        args.loaded_modules,
        args.direct_imports,
        args.recursive_closure,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    loaded_count = sum(item["actually_loaded"] for item in payload["files"])
    print(f"Torch DLLs: {len(payload['files'])}; dynamically loaded: {loaded_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
