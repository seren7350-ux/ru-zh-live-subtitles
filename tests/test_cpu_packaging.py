from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGING = PROJECT_ROOT / "packaging"
TOOLKIT = PACKAGING / "clean_machine"
GPU_FILE_SHA256 = {
    "packaging/combined.spec": "5d750f0d6eec186ed5af948f13abc5d36058f6ce942b28f231fd1a6a17d64ee3",
    "packaging/optimization_profile.py": "728bcd8e66a6282a8e879cb03506f4c761910224e239f69d774761e9d7a615e0",
    "packaging/hooks/hook-torch.py": "f4e3eeb1121e774c78646dc3f222ddcf512b5d2be298eae303ca24e788f4b964",
}


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cpu_policy() -> Any:
    return _load(PACKAGING / "cpu_package_policy.py", "cpu_package_policy_test")


@pytest.fixture
def prepare() -> Any:
    return _load(TOOLKIT / "prepare_assets.py", "prepare_assets_cpu_test")


def fake_torch(version: str, cuda_version: str | None, available: bool) -> Any:
    return SimpleNamespace(
        __version__=version,
        version=SimpleNamespace(cuda=cuda_version),
        cuda=SimpleNamespace(is_available=lambda: available),
    )


def test_cpu_torch_metadata_is_explicit(cpu_policy: Any) -> None:
    metadata = cpu_policy.validate_cpu_torch(fake_torch("2.12.1+cpu", None, False))
    assert metadata.as_dict() == {
        "runtime_family": "cpu",
        "torch_version": "2.12.1+cpu",
        "torch_cuda_version": None,
        "cuda_available": False,
        "selected_translation_device": "cpu",
    }


@pytest.mark.parametrize(
    ("version", "cuda_version", "available"),
    [
        ("2.12.1+cu130", "13.0", False),
        ("2.12.1+cpu", None, True),
        ("2.11.0+cpu", None, False),
    ],
)
def test_cpu_torch_rejects_non_cpu_boundary(
    cpu_policy: Any, version: str, cuda_version: str | None, available: bool
) -> None:
    with pytest.raises(cpu_policy.CpuPackagePolicyError):
        cpu_policy.validate_cpu_torch(fake_torch(version, cuda_version, available))


@pytest.mark.parametrize(
    "name",
    [
        "c10_cuda.dll",
        "torch_cuda.dll",
        "cudart64_130.dll",
        "cublas64_13.dll",
        "cudnn64_9.dll",
        "cufft64_12.dll",
        "curand64_10.dll",
        "cusolver64_11.dll",
        "cusparse64_12.dll",
        "nvrtc64_130_0.dll",
        "nvjitlink_130_0.dll",
        "cupti64_2026.1.dll",
        "nvperf_host.dll",
    ],
)
def test_cpu_policy_recognizes_every_forbidden_cuda_library(
    tmp_path: Path, cpu_policy: Any, name: str
) -> None:
    (tmp_path / name).write_bytes(b"dll")
    assert cpu_policy.forbidden_cuda_libraries((tmp_path,))


def test_cpu_distribution_accepts_torch_cpu_and_rejects_cuda(
    tmp_path: Path, cpu_policy: Any
) -> None:
    distribution = tmp_path / "ru-zh-subtitles-cpu"
    torch_lib = distribution / "_internal" / "torch" / "lib"
    torch_lib.mkdir(parents=True)
    (distribution / "ru-zh-subtitles.exe").write_bytes(b"exe")
    (distribution / "ru-zh-subtitles-console.exe").write_bytes(b"exe")
    (torch_lib / "torch_cpu.dll").write_bytes(b"cpu")
    result = cpu_policy.validate_cpu_distribution(distribution)
    assert result["runtime_family"] == "cpu"
    assert result["cuda_library_files"] == []
    (torch_lib / "c10_cuda.dll").write_bytes(b"cuda")
    with pytest.raises(cpu_policy.CpuPackagePolicyError, match="CUDA"):
        cpu_policy.validate_cpu_distribution(distribution)


def test_prepare_assets_cpu_manifest_and_cuda_rejection(
    tmp_path: Path, prepare: Any
) -> None:
    package = tmp_path / "candidate"
    torch_lib = package / "_internal" / "torch" / "lib"
    torch_lib.mkdir(parents=True)
    for name in prepare.PACKAGE_EXES:
        (package / name).write_bytes(b"exe")
    (torch_lib / "torch_cpu.dll").write_bytes(b"cpu")
    analysis = prepare.analyze_package(
        package,
        repo_root=tmp_path / "repo",
        user_home=tmp_path / "home",
        runtime_family="cpu",
    )
    assert analysis["package_runtime_family"] == "cpu"
    assert analysis["torch_cpu_runtime_present"] is True
    assert analysis["cuda_library_files"] == []
    (torch_lib / "torch_cuda.dll").write_bytes(b"cuda")
    with pytest.raises(prepare.AssetPreparationError, match="CUDA"):
        prepare.analyze_package(
            package,
            repo_root=tmp_path / "repo",
            user_home=tmp_path / "home",
            runtime_family="cpu",
        )


def test_cpu_spec_has_shared_two_exe_onedir_and_no_gpu_profile() -> None:
    path = PACKAGING / "combined_cpu.spec"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    call_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert call_names.count("Analysis") == 1
    assert call_names.count("PYZ") == 1
    assert call_names.count("EXE") == 2
    assert call_names.count("COLLECT") == 1
    assert 'name="ru-zh-subtitles-cpu"' in source
    assert 'name="ru-zh-subtitles-console"' in source
    assert 'name="ru-zh-subtitles"' in source
    assert "console=True" in source and "console=False" in source
    assert "packaging\" / \"entrypoint.py" in source
    assert "optimization_profile" not in source
    assert "validate_cpu_environment" in source
    assert "validate_pyinstaller_entries" in source
    assert "validate_cpu_distribution" in source
    assert "cpu_build_provenance.write_metadata" in source
    assert "CPU_BUILD_METADATA.json" in source
    assert 'project_root / "build" / "cpu-provenance"' in source
    assert "WORKPATH" not in source
    assert "onefile" not in source.casefold()


def test_cpu_provenance_is_collected_only_by_cpu_spec() -> None:
    cpu = (PACKAGING / "combined_cpu.spec").read_text(encoding="utf-8")
    gpu = (PACKAGING / "combined.spec").read_text(encoding="utf-8")
    assert "cpu_build_provenance" in cpu
    assert "cpu_build_metadata" in cpu
    assert "cpu_build_provenance" not in gpu
    assert "CPU_BUILD_METADATA.json" not in gpu


def test_gpu_packaging_files_are_byte_identical_to_main() -> None:
    for relative, expected in GPU_FILE_SHA256.items():
        actual = hashlib.sha256((PROJECT_ROOT / relative).read_bytes()).hexdigest()
        assert actual == expected


def test_cpu_dependency_files_pin_cpu_torch_and_exclude_gpu_packages() -> None:
    requirements = (PACKAGING / "requirements-cpu.txt").read_text(encoding="utf-8")
    constraints = (PACKAGING / "constraints-cpu.txt").read_text(encoding="utf-8")
    assert "torch==2.12.1+cpu" in constraints
    serialized = (requirements + "\n" + constraints).casefold()
    for forbidden in ("torchvision", "torchaudio", "triton", "nvidia-"):
        assert forbidden not in serialized
    assert "cu130" not in serialized and "cu126" not in serialized


def test_offline_script_can_enforce_cpu_runtime_boundary() -> None:
    source = (TOOLKIT / "offline_cache_startup.ps1").read_text(encoding="utf-8")
    for marker in (
        "ExpectedRuntimeFamily",
        "Package runtime family",
        "Torch CUDA version",
        "Selected translation device",
        "boundary_valid",
    ):
        assert marker in source
    assert "Package runtime boundary validation failed" in source


def test_failure_evidence_schema_is_relative_and_local_only() -> None:
    schema = json.loads(
        (TOOLKIT / "failure-evidence-schema.json").read_text(encoding="utf-8")
    )
    required = set(schema["required"])
    assert {"must_not_commit", "must_not_upload", "files"} <= required
    serialized = json.dumps(schema)
    assert "C:\\\\Users\\\\" not in serialized


def test_raw_failure_evidence_is_not_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "data/clean-machine-validation"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.splitlines()
    assert tracked == []
