from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_ROOT = PROJECT_ROOT / "packaging" / "installer"
ISS = INSTALLER_ROOT / "cpu-only.iss"
BUILD_SCRIPT = INSTALLER_ROOT / "build_installer.ps1"


def load_release_metadata():
    path = INSTALLER_ROOT / "release_metadata.py"
    spec = importlib.util.spec_from_file_location("release_metadata", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cpu_is_only_distribution_candidate_and_gpu_remains_internal() -> None:
    metadata = load_release_metadata()
    assert metadata.PUBLIC_DISTRIBUTION == "Windows x64 CPU-only"
    assert metadata.GPU_DISTRIBUTION_STATUS == "internal-development-only"
    assert (PROJECT_ROOT / "packaging" / "combined.spec").is_file()
    assert (PROJECT_ROOT / "packaging" / "optimization_profile.py").is_file()
    assert (PROJECT_ROOT / "packaging" / "hooks" / "hook-torch.py").is_file()


def test_inno_policy_is_per_user_x64_cpu_offline_and_stable() -> None:
    source = ISS.read_text(encoding="utf-8")
    assert "AppId={{8773A11B-6B74-42AF-85AF-CAD43EB946CF}" in source
    assert "PrivilegesRequired=lowest" in source
    assert "DefaultDirName={localappdata}\\Programs\\RuZhLiveSubtitles" in source
    assert "ArchitecturesAllowed=x64compatible" in source
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in source
    assert "live-overlay --translation-device cpu --offline --no-auto-start" in source
    assert "Tasks: desktopicon" in source
    assert "Flags: unchecked" in source
    assert "Program Files" not in source
    assert "HKLM" not in source
    assert "[Registry]" not in source
    assert "[UninstallDelete]" not in source
    assert "combined.spec" not in source
    assert "ru-zh-subtitles-cpu" not in source
    assert "model-assets" not in source


def test_installer_source_has_no_gpu_cuda_download_service_or_startup_policy() -> None:
    source = ISS.read_text(encoding="utf-8").casefold()
    for forbidden in (
        "c10_cuda.dll",
        "torch_cuda.dll",
        "cudart",
        "cublas",
        "cudnn",
        "nvrtc",
        "downloadtemporaryfile",
        "[run]",
        "service",
        "startup",
    ):
        assert forbidden not in source


def test_version_is_read_from_single_python_source() -> None:
    metadata = load_release_metadata()
    assert metadata.read_application_version(
        PROJECT_ROOT / "src" / "live_subtitles" / "__init__.py"
    ) == "0.1.0"
    source = ISS.read_text(encoding="utf-8")
    assert "AppVersion={#AppVersion}" in source
    assert "VersionInfoVersion={#VersionInfoVersion}" in source


def make_cpu_dist(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "ru-zh-subtitles.exe").write_bytes(b"exe")
    (root / "ru-zh-subtitles-console.exe").write_bytes(b"console")
    internal = root / "_internal"
    internal.mkdir()
    (internal / "torch_cpu.dll").write_bytes(b"cpu")
    return root


def test_release_inventory_supports_unicode_space_path_and_rejects_cuda(
    tmp_path: Path,
) -> None:
    metadata = load_release_metadata()
    dist = make_cpu_dist(tmp_path / "俄中 字幕")
    result = metadata.inspect_cpu_distribution(dist, full_manifest=True)
    assert result["cuda_dll_count"] == 0
    assert result["model_weight_count"] == 0
    assert result["file_count"] == 3
    assert result["distribution_name"] == "ru-zh-subtitles-cpu"
    assert "path" not in result
    assert str(dist.resolve()) not in str(result)
    (dist / "_internal" / "cudart64_13.dll").write_bytes(b"cuda")
    with pytest.raises(metadata.ReleaseMetadataError, match="CUDA"):
        metadata.inspect_cpu_distribution(dist)


def test_release_inventory_rejects_missing_torch_cpu_and_model_weights(
    tmp_path: Path,
) -> None:
    metadata = load_release_metadata()
    dist = make_cpu_dist(tmp_path / "dist")
    (dist / "_internal" / "torch_cpu.dll").unlink()
    with pytest.raises(metadata.ReleaseMetadataError, match="torch_cpu"):
        metadata.inspect_cpu_distribution(dist)
    (dist / "_internal" / "torch_cpu.dll").write_bytes(b"cpu")
    (dist / "weights.bin").write_bytes(b"model")
    with pytest.raises(metadata.ReleaseMetadataError, match="model weights"):
        metadata.inspect_cpu_distribution(dist)


def test_release_metadata_rejects_wrong_git_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    metadata = load_release_metadata()
    dist = make_cpu_dist(tmp_path / "dist")
    version = tmp_path / "src" / "live_subtitles"
    version.mkdir(parents=True)
    (version / "__init__.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    monkeypatch.setattr(metadata, "git_commit", lambda _root: "a" * 40)
    with pytest.raises(metadata.ReleaseMetadataError, match="mismatch"):
        metadata.create_metadata(
            repo_root=tmp_path,
            cpu_dist=dist,
            expected_commit="b" * 40,
            inno_version="7.0.2",
            full_manifest=False,
        )


def test_build_script_has_strict_safe_atomic_policy() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "Set-StrictMode -Version Latest" in source
    assert "$ErrorActionPreference = 'Stop'" in source
    assert "ExpectedCommit" in source
    assert "validate_cpu_distribution.py" in source
    assert "torch_cpu.dll" not in source  # delegated to the shared CPU policy
    assert "Move-Item -LiteralPath $compiled -Destination $final -Force" in source
    assert "Get-AuthenticodeSignature" in source
    assert "Pyrsys B\\.V\\." in source
    assert "iscc.log" in source
    assert "inno_warning_count" in source
    assert "Set-Content -LiteralPath $compilerLog -Value $compilerOutput" in source
    assert "Invoke-Expression" not in source
    assert "Set-ExecutionPolicy" not in source
    assert "Start-Process" not in source


def test_cpu_spec_includes_model_setup_but_gpu_spec_is_not_deleted() -> None:
    cpu = (PROJECT_ROOT / "packaging" / "combined_cpu.spec").read_text(encoding="utf-8")
    assert "MODEL_SETUP.txt" in cpu
    assert (PROJECT_ROOT / "packaging" / "combined.spec").is_file()
