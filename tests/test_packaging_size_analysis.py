from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str) -> Any:
    path = PROJECT_ROOT / "packaging" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"ru_zh_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def analysis_module() -> Any:
    return _load("analyze_distribution")


@pytest.fixture
def diff_module() -> Any:
    return _load("diff_distributions")


@pytest.fixture
def pe_module() -> Any:
    return _load("analyze_pe_dependencies")


@pytest.fixture
def profile_module() -> Any:
    return _load("optimization_profile")


@pytest.fixture
def inventory_module() -> Any:
    return _load("build_torch_binary_inventory")


def _small_distribution(root: Path) -> Path:
    (root / "_internal" / "torch" / "lib").mkdir(parents=True)
    (root / "_internal" / "onnx_asr" / "preprocessors" / "data").mkdir(
        parents=True
    )
    (root / "app.exe").write_bytes(b"exe")
    (root / "_internal" / "module.pyd").write_bytes(b"pyd")
    (root / "_internal" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (root / "_internal" / "torch" / "lib" / "c10.dll").write_bytes(b"core")
    (
        root
        / "_internal"
        / "onnx_asr"
        / "preprocessors"
        / "data"
        / "resample_48_16.onnx"
    ).write_bytes(b"preprocessor")
    return root


def test_combined_spec_uses_one_analysis_pyz_and_collect_for_two_exes() -> None:
    source = (PROJECT_ROOT / "packaging" / "combined.spec").read_text(encoding="utf-8")
    compile(source, "combined.spec", "exec")
    assert source.count("Analysis(") == 1
    assert source.count("PYZ(") == 1
    assert source.count("EXE(") == 2
    assert source.count("COLLECT(") == 1
    assert 'name="ru-zh-subtitles-console"' in source
    assert 'name="ru-zh-subtitles"' in source
    assert "console=True" in source
    assert "console=False" in source


def test_combined_spec_collects_shared_dependencies_once() -> None:
    source = (PROJECT_ROOT / "packaging" / "combined.spec").read_text(encoding="utf-8")
    collect_source = source.split("coll = COLLECT(", 1)[1]
    assert collect_source.count("a.binaries") == 1
    assert collect_source.count("a.datas") == 1
    assert "console_exe" in collect_source
    assert "windowed_exe" in collect_source


def test_analyze_distribution_counts_and_uses_relative_paths(
    tmp_path: Path, analysis_module: Any
) -> None:
    root = _small_distribution(tmp_path / "dist")
    result = analysis_module.analyze_distribution(root)
    assert result["file_count"] == 5
    assert result["exe_count"] == 1
    assert result["dll_count"] == 1
    assert result["pyd_count"] == 1
    assert result["python_file_count"] == 1
    assert result["categories"]["torch_total_bytes"] == 4
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert all(not Path(item["path"]).is_absolute() for item in result["files"])


def test_analyze_distribution_rejects_model_weights(
    tmp_path: Path, analysis_module: Any
) -> None:
    root = _small_distribution(tmp_path / "dist")
    (root / "model.safetensors").write_bytes(b"weight")
    with pytest.raises(analysis_module.DistributionAnalysisError, match="safetensors"):
        analysis_module.analyze_distribution(root)


def test_diff_distributions_reports_added_removed_changed_and_reduction(
    diff_module: Any,
) -> None:
    baseline = {
        "distribution_name": "baseline",
        "total_size_bytes": 30,
        "files": [
            {"path": "a.dll", "size_bytes": 20},
            {"path": "removed.dll", "size_bytes": 10},
        ],
    }
    candidate = {
        "distribution_name": "candidate",
        "total_size_bytes": 17,
        "files": [
            {"path": "a.dll", "size_bytes": 15},
            {"path": "added.txt", "size_bytes": 2},
        ],
    }
    result = diff_module.diff_distributions(baseline, candidate)
    assert result["reduction_bytes"] == 13
    assert result["reduction_percent"] == pytest.approx(43.333333)
    assert result["added_files"] == [{"path": "added.txt", "size_bytes": 2}]
    assert result["removed_files"] == [{"path": "removed.dll", "size_bytes": 10}]
    assert result["changed_files"][0]["delta_bytes"] == -5


def test_pe_parser_reads_normal_and_delay_imports(pe_module: Any) -> None:
    fake = SimpleNamespace(
        DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(dll=b"KERNEL32.dll")],
        DIRECTORY_ENTRY_DELAY_IMPORT=[SimpleNamespace(dll=b"cudnn64_9.dll")],
    )
    imports, delayed = pe_module.extract_import_names(fake)
    assert imports == ["KERNEL32.dll"]
    assert delayed == ["cudnn64_9.dll"]


def test_pe_output_rejects_absolute_paths(pe_module: Any) -> None:
    with pytest.raises(ValueError, match="Absolute path"):
        pe_module.reject_absolute_output_path("C:/Users/example/file.dll")
    assert pe_module.reject_absolute_output_path("_internal/torch/lib/c10.dll") == (
        "_internal/torch/lib/c10.dll"
    )


def test_profile_locks_torch_and_cuda_versions(profile_module: Any) -> None:
    profile_module.validate_runtime_versions("2.12.1+cu130", "13.0")
    with pytest.raises(RuntimeError, match="Torch version mismatch"):
        profile_module.validate_runtime_versions("2.13.0", "13.0")
    with pytest.raises(RuntimeError, match="CUDA version mismatch"):
        profile_module.validate_runtime_versions("2.12.1+cu130", "12.8")


def test_unknown_large_torch_dll_requires_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_module: Any
) -> None:
    unknown = tmp_path / "mystery_accelerator.dll"
    unknown.write_bytes(b"large")
    monkeypatch.setattr(profile_module, "LARGE_DLL_THRESHOLD_BYTES", 1)
    with pytest.raises(RuntimeError, match="Unknown large Torch DLL"):
        profile_module.validate_profile(
            "baseline",
            torch_version="2.12.1+cu130",
            cuda_version="13.0",
            torch_dlls=[unknown],
        )


def test_baseline_excludes_no_binary(profile_module: Any) -> None:
    assert profile_module.excluded_binary_names("baseline") == frozenset()


def test_optimized_profile_contains_only_approved_exclusions(profile_module: Any) -> None:
    excluded = profile_module.excluded_binary_names("optimized")
    assert excluded <= profile_module.EXCLUSION_REASONS.keys()


def test_optimized_data_filter_only_removes_approved_dist_info(
    profile_module: Any,
) -> None:
    datas = [
        ("torch-1.0.dist-info/RECORD", "source", "DATA"),
        ("torch-1.0.dist-info/METADATA", "source", "DATA"),
        ("ordinary/RECORD", "source", "DATA"),
        ("torch-1.0.dist-info/LICENSE", "source", "DATA"),
    ]
    assert profile_module.filter_collected_datas("baseline", datas) == datas
    retained = profile_module.filter_collected_datas("optimized", datas)
    assert ("torch-1.0.dist-info/RECORD", "source", "DATA") not in retained
    assert ("ordinary/RECORD", "source", "DATA") in retained
    assert ("torch-1.0.dist-info/METADATA", "source", "DATA") in retained
    assert ("torch-1.0.dist-info/LICENSE", "source", "DATA") in retained


def test_torch_inventory_classification_is_explicit(inventory_module: Any) -> None:
    assert inventory_module.classify_binary("cublasLt64_13.dll") == "cuBLASLt"
    assert inventory_module.classify_binary("cudnn_ops64_9.dll") == "cuDNN"
    assert inventory_module.classify_binary("nvperf_host.dll") == "profiling/NVTX"
    assert inventory_module.classify_binary("unrecognized.dll") == "unknown"


def test_capture_script_records_only_relative_dist_paths() -> None:
    source = (PROJECT_ROOT / "packaging" / "capture_loaded_modules.ps1").read_text(
        encoding="utf-8"
    )
    assert "relative_path" in source
    assert "category = if ($isDist)" in source
    assert "FileName =" not in source
    assert "-Module" in source
    assert "Start-Sleep -Milliseconds $IntervalMs" in source
    assert "UTF8Encoding]::new($false)" in source
    assert "A process can exit" in source


def test_torch_collection_mode_defaults_to_source_compatible_mode() -> None:
    source = (PROJECT_ROOT / "packaging" / "hooks" / "hook-torch.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("RU_ZH_TORCH_COLLECTION_MODE", "pyz+py")' in source
    assert '{"pyz", "pyz+py"}' in source


def test_combined_profile_is_explicit_and_baseline_by_default() -> None:
    source = (PROJECT_ROOT / "packaging" / "combined.spec").read_text(encoding="utf-8")
    assert 'os.environ.get("RU_ZH_PACKAGE_PROFILE", "baseline")' in source
    assert "validate_profile(" in source
    assert "filter_collected_datas(" in source


def test_baseline_template_has_no_absolute_path() -> None:
    payload = json.loads(
        (PROJECT_ROOT / "packaging" / "baseline-template.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["machine_paths_included"] is False
    assert "C:\\" not in json.dumps(payload)


def test_existing_freeze_support_and_model_cache_guards_remain() -> None:
    entry = (PROJECT_ROOT / "packaging" / "entrypoint.py").read_text(encoding="utf-8")
    paths = (PROJECT_ROOT / "src" / "live_subtitles" / "runtime_paths.py").read_text(
        encoding="utf-8"
    )
    assert "multiprocessing.freeze_support()" in entry
    assert "_MEIPASS" in paths
    for source_path in (PROJECT_ROOT / "src").rglob("*.py"):
        if source_path.name != "runtime_paths.py":
            assert "_MEIPASS" not in source_path.read_text(encoding="utf-8")
