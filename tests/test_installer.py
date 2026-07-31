from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
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
    assert "OutputBaseFilename=ru-zh-live-subtitles-cpu-offline-{#AppVersion}-setup" in source
    assert 'DestDir: "{localappdata}\\ru-zh-live-subtitles\\models"' in source
    assert "uninsneveruninstall" in source
    assert "MinimumFreeBytes = 12884901888" in source
    assert "DiskSliceSize=1900000000" in source
    assert "LZMANumBlockThreads=4" in source
    assert "HF_HUB_CACHE" not in source
    assert "HF_HOME" not in source


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
    ) == "0.2.0"
    source = ISS.read_text(encoding="utf-8")
    assert "AppVersion={#AppVersion}" in source
    assert "VersionInfoVersion={#VersionInfoVersion}" in source


def make_cpu_dist(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "ru-zh-subtitles.exe").write_bytes(b"exe")
    (root / "ru-zh-subtitles-console.exe").write_bytes(b"console")
    (root / "README.md").write_text("readme\n", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.md").write_text("notices\n", encoding="utf-8")
    (root / "MODEL_SETUP.txt").write_text("models\n", encoding="utf-8")
    (root / "MODEL_LICENSES.txt").write_text("licenses\n", encoding="utf-8")
    (root / "CPU_BUILD_METADATA.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "application_version": "0.2.0",
                "git_commit": "a" * 40,
                "runtime_family": "cpu",
                "working_tree_clean": True,
                "build_platform": "windows-x64",
                "spec": "packaging/combined_cpu.spec",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
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
    assert result["file_count"] == 8
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
    (version / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    bundle_metadata = tmp_path / "MODEL_BUNDLE_METADATA.json"
    make_model_bundle_metadata(bundle_metadata)
    monkeypatch.setattr(metadata, "git_commit", lambda _root: "a" * 40)
    with pytest.raises(metadata.ReleaseMetadataError, match="mismatch"):
        metadata.create_metadata(
            repo_root=tmp_path,
            cpu_dist=dist,
            expected_commit="b" * 40,
            inno_version="7.0.2",
            model_bundle_metadata=bundle_metadata,
            full_manifest=False,
        )


def test_build_script_has_strict_safe_atomic_policy() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "Set-StrictMode -Version Latest" in source
    assert "$ErrorActionPreference = 'Stop'" in source
    assert "ExpectedCommit" in source
    assert "ModelAssetsRoot" in source
    assert "model_bundle.py" in source
    assert 'dist\\installer-offline-$version' in source
    assert "ReleaseAssetLimitBytes = 2000000000" in source
    assert "ForceDiskSpanning" in source
    assert "SHA256SUMS.txt" in source
    assert "status --porcelain=v1 --untracked-files=all" in source
    assert "Git working tree is not clean" in source
    assert "validate_cpu_distribution.py" in source
    assert "torch_cpu.dll" not in source  # delegated to the shared CPU policy
    assert "Move-Item -LiteralPath $compiled -Destination $finalSetup" in source
    assert "Remove-ExactCandidateFiles $finalPaths" in source
    assert "setup_published_last = $true" in source
    assert "Get-AuthenticodeSignature" in source
    assert "Pyrsys B\\.V\\." in source
    assert "iscc.log" in source
    assert "inno_warning_count" in source
    assert "Set-Content -LiteralPath $compilerLog -Value $compilerOutput" in source
    assert "Invoke-Expression" not in source
    assert "Set-ExecutionPolicy" not in source
    assert "Start-Process" not in source
    assert "huggingface" not in source.casefold()
    assert "Invoke-WebRequest" not in source
    assert source.index("$bundleMetadata =") < source.index("$iscc = Find-Iscc $IsccPath")


def test_model_bundle_validator_has_no_cache_or_network_fallback() -> None:
    source = (PROJECT_ROOT / "packaging" / "model_bundle.py").read_text(
        encoding="utf-8"
    ).casefold()
    for forbidden in (
        "hf_hub_download",
        "snapshot_download",
        "requests",
        "urllib",
        "user_model_root",
        "default_hf_hub_cache",
    ):
        assert forbidden not in source


def test_cpu_spec_includes_model_setup_but_gpu_spec_is_not_deleted() -> None:
    cpu = (PROJECT_ROOT / "packaging" / "combined_cpu.spec").read_text(encoding="utf-8")
    assert "MODEL_SETUP.txt" in cpu
    assert "MODEL_LICENSES.txt" in cpu
    assert (PROJECT_ROOT / "packaging" / "combined.spec").is_file()


def test_installed_model_license_notice_contains_upstream_terms() -> None:
    notice = (INSTALLER_ROOT / "MODEL_LICENSES.txt").read_text(encoding="utf-8")
    assert "Copyright (c) 2020-present Silero Team" in notice
    assert "Copyright (c) 2024 GigaChat Team" in notice
    assert "Creative Commons Attribution-NonCommercial 4.0 International Public" in notice
    assert "Section 8 -- Interpretation." in notice
    assert "f8d333a098d19b4fd9a8b18f94170487ad3f821d" in notice


def test_inno_uses_provenance_bound_cpu_docs_without_duplicate_sources() -> None:
    source_lines = [
        line.strip() for line in ISS.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("Source:")
    ]
    assert len([line for line in source_lines if "{#CpuDist}\\*" in line]) == 1
    assert len([line for line in source_lines if "RELEASE_METADATA.json" in line]) == 1
    assert len([line for line in source_lines if "MODEL_BUNDLE_METADATA.json" in line]) == 1
    assert len([line for line in source_lines if "{#ModelAssetsRoot}\\*" in line]) == 1
    for document in ("README.md", "THIRD_PARTY_NOTICES.md", "MODEL_SETUP.txt"):
        assert all(document not in line for line in source_lines)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("git_commit", "b" * 40, "commit mismatch"),
        ("application_version", "9.9.9", "version mismatch"),
        ("runtime_family", "gpu", "runtime_family"),
        ("working_tree_clean", False, "working_tree_clean"),
    ],
)
def test_release_inventory_rejects_invalid_cpu_provenance(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    metadata = load_release_metadata()
    dist = make_cpu_dist(tmp_path / "dist")
    path = dist / "CPU_BUILD_METADATA.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(metadata.ReleaseMetadataError, match=message):
        metadata.inspect_cpu_distribution(
            dist,
            expected_version="0.2.0",
            expected_commit="a" * 40,
        )


def test_release_inventory_rejects_missing_cpu_provenance(tmp_path: Path) -> None:
    metadata = load_release_metadata()
    dist = make_cpu_dist(tmp_path / "dist")
    (dist / "CPU_BUILD_METADATA.json").unlink()
    with pytest.raises(metadata.ReleaseMetadataError, match="provenance is missing"):
        metadata.inspect_cpu_distribution(dist)


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _write_cpu_provenance(dist: Path, commit: str) -> None:
    path = dist / "CPU_BUILD_METADATA.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["git_commit"] = commit
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _make_real_git_release_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    repo = tmp_path / "release-repo"
    package = repo / "src" / "live_subtitles"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text(
        "dist/\n**/__pycache__/\n*.py[cod]\n", encoding="utf-8"
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "--local", "user.name", "Installer Test")
    _git(repo, "config", "--local", "user.email", "installer@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    dist = make_cpu_dist(repo / "dist" / "ru-zh-subtitles-cpu")
    _write_cpu_provenance(dist, commit)
    return repo, dist, commit


def test_release_metadata_cross_validates_real_git_repo_and_manifest_docs(
    tmp_path: Path,
) -> None:
    metadata = load_release_metadata()
    repo, dist, commit = _make_real_git_release_repo(tmp_path)
    bundle_metadata = tmp_path / "MODEL_BUNDLE_METADATA.json"
    make_model_bundle_metadata(bundle_metadata)
    payload = metadata.create_metadata(
        repo_root=repo,
        cpu_dist=dist,
        expected_commit=commit,
        inno_version="7.0.2",
        model_bundle_metadata=bundle_metadata,
        full_manifest=True,
    )
    assert payload["git_commit"] == commit
    assert payload["cpu_build_provenance"]["git_commit"] == commit
    manifest = {
        item["path"]: item["sha256"]
        for item in payload["cpu_distribution"]["files"]
    }
    installed = tmp_path / "installed"
    shutil.copytree(dist, installed)
    for document in (
        "README.md",
        "THIRD_PARTY_NOTICES.md",
        "MODEL_SETUP.txt",
        "MODEL_LICENSES.txt",
    ):
        assert metadata.sha256_file(installed / document) == manifest[document]


def make_model_bundle_metadata(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_type": "offline-model-assets",
                "self_contained": True,
                "offline_ready": True,
                "silero_version": "6.2.1",
                "silero_model_sha256": "1" * 64,
                "gigaam_model_id": "ai-sage/GigaAM-Multilingual",
                "gigaam_variant": "large_ctc",
                "gigaam_revision": "3905cd51c3ed4e88c8edf33f3302969ba480a327",
                "nllb_model_id": "facebook/nllb-200-distilled-600M",
                "nllb_revision": "f8d333a098d19b4fd9a8b18f94170487ad3f821d",
                "file_count": 7,
                "total_bytes": 123,
                "manifest_sha256": "2" * 64,
                "licenses": {
                    "silero": "MIT",
                    "gigaam": "MIT",
                    "nllb": "CC-BY-NC-4.0",
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _copy_builder_inputs(repo: Path) -> None:
    installer = repo / "packaging" / "installer"
    installer.mkdir(parents=True)
    for relative in (
        "packaging/cpu_build_provenance.py",
        "packaging/cpu_package_policy.py",
        "packaging/analyze_distribution.py",
        "packaging/validate_cpu_distribution.py",
        "packaging/model_bundle.py",
        "packaging/installer/release_metadata.py",
        "packaging/installer/cpu-only.iss",
        "packaging/installer/README_INSTALL.txt",
        "packaging/installer/MODEL_LICENSES.txt",
    ):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / relative, destination)


def _make_fake_iscc(path: Path) -> None:
    path.write_text(
        "@echo off\n"
        "setlocal EnableDelayedExpansion\n"
        "set \"out=\"\n"
        "set \"base=\"\n"
        "set \"span=\"\n"
        ":loop\n"
        "if \"%~1\"==\"\" goto done\n"
        "set \"arg=%~1\"\n"
        "if /I \"!arg:~0,2!\"==\"/O\" set \"out=!arg:~2!\"\n"
        "if /I \"!arg:~0,2!\"==\"/F\" set \"base=!arg:~2!\"\n"
        "if /I \"!arg:~0,14!\"==\"/DDiskSpanning\" set \"span=1\"\n"
        "shift\n"
        "goto loop\n"
        ":done\n"
        "if not exist \"!out!\" mkdir \"!out!\"\n"
        "> \"!out!\\!base!.exe\" echo fake installer\n"
        "if defined span > \"!out!\\!base!-1.bin\" echo fake slice\n"
        "echo Compiler completed successfully\n"
        "exit /b 0\n",
        encoding="ascii",
    )


def _make_builder_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    repo = tmp_path / "builder-repo"
    package = repo / "src" / "live_subtitles"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    (repo / ".gitignore").write_text(
        "dist/\n**/__pycache__/\n*.py[cod]\n", encoding="utf-8"
    )
    _copy_builder_inputs(repo)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "--local", "user.name", "Builder Test")
    _git(repo, "config", "--local", "user.email", "builder@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    commit = _git(repo, "rev-parse", "HEAD")
    dist = make_cpu_dist(repo / "dist" / "ru-zh-subtitles-cpu")
    _write_cpu_provenance(dist, commit)
    output = repo / "dist" / "installer-offline"
    doctor = tmp_path / "doctor.txt"
    doctor.write_text(
        "Package runtime family: cpu\n"
        "Torch CUDA version: None\n"
        "CUDA available: False\n"
        "Selected translation device: cpu\n",
        encoding="utf-8",
    )
    (tmp_path / "model-assets").mkdir()
    make_model_bundle_metadata(tmp_path / "MODEL_BUNDLE_METADATA.json")
    iscc = tmp_path / "fake-iscc.cmd"
    _make_fake_iscc(iscc)
    return repo, dist, output, doctor, commit


def _quote_powershell(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _windows_powershell_env() -> dict[str, str]:
    """Let Windows PowerShell construct its own module discovery path."""

    return {
        key: value
        for key, value in os.environ.items()
        if key.casefold() != "psmodulepath"
    }


def _run_builder(
    *,
    repo: Path,
    dist: Path,
    output: Path,
    doctor: Path,
    commit: str,
    failure_stage: str = "None",
    force_disk_spanning: bool = False,
    release_asset_limit_bytes: int = 2_000_000_000,
) -> subprocess.CompletedProcess[str]:
    iscc = doctor.parent / "fake-iscc.cmd"
    command = (
        "$builder=[scriptblock]::Create([IO.File]::ReadAllText("
        + _quote_powershell(BUILD_SCRIPT)
        + ")); & $builder"
        + " -RepoRoot " + _quote_powershell(repo)
        + " -CpuDist " + _quote_powershell(dist)
        + " -ModelAssetsRoot " + _quote_powershell(doctor.parent / "model-assets")
        + " -OutputDir " + _quote_powershell(output)
        + " -ExpectedCommit " + _quote_powershell(commit)
        + " -PythonPath " + _quote_powershell(Path(sys.executable))
        + " -IsccPath " + _quote_powershell(iscc)
        + " -TestMode -TestDoctorOutputPath " + _quote_powershell(doctor)
        + " -TestModelBundleMetadataPath " + _quote_powershell(doctor.parent / "MODEL_BUNDLE_METADATA.json")
        + " -TestFailureStage " + _quote_powershell(failure_stage)
        + " -ReleaseAssetLimitBytes " + str(release_asset_limit_bytes)
        + (" -ForceDiskSpanning" if force_disk_spanning else "")
    )
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_windows_powershell_env(),
    )


def _final_builder_paths(output: Path) -> list[Path]:
    return [
        output / "RELEASE_METADATA.json",
        output / "MODEL_BUNDLE_METADATA.json",
        output / "iscc.log",
        output / "build-report.json",
        output / "README_INSTALL.txt",
        output / "SHA256SUMS.txt",
        output / "ru-zh-live-subtitles-cpu-offline-0.2.0-setup.exe",
    ]


def test_builder_windows_powershell_env_drops_inherited_module_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PSModulePath", r"C:\Program Files\PowerShell\7\Modules")

    environment = _windows_powershell_env()

    assert not any(key.casefold() == "psmodulepath" for key in environment)


def test_builder_dirty_tree_removes_old_candidate_before_compiler(tmp_path: Path) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    output.mkdir(parents=True, exist_ok=True)
    finals = _final_builder_paths(output)
    for path in finals:
        path.write_text("old", encoding="utf-8")
    (repo / "untracked.txt").write_text("dirty", encoding="utf-8")

    completed = _run_builder(
        repo=repo, dist=dist, output=output, doctor=doctor, commit=commit
    )
    assert completed.returncode != 0
    assert "Git working tree is not clean" in completed.stderr
    assert str(repo) not in completed.stderr
    assert not any(path.exists() for path in finals)


def test_builder_test_mode_is_rejected_for_repository_with_origin(tmp_path: Path) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    _git(repo, "remote", "add", "origin", "https://example.invalid/formal.git")
    completed = _run_builder(
        repo=repo, dist=dist, output=output, doctor=doctor, commit=commit
    )
    assert completed.returncode != 0
    assert "cannot run in a repository with an origin remote" in completed.stderr
    assert not any(path.exists() for path in _final_builder_paths(output))


def test_builder_rejects_stale_cpu_dist_before_iscc_and_publishes_nothing(
    tmp_path: Path,
) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    _write_cpu_provenance(dist, "b" * 40)
    completed = _run_builder(
        repo=repo, dist=dist, output=output, doctor=doctor, commit=commit
    )
    assert completed.returncode != 0
    assert "commit mismatch" in (completed.stdout + completed.stderr)
    assert not any(path.exists() for path in _final_builder_paths(output))


@pytest.mark.parametrize("failure_stage", ["CpuPolicy", "ModelBundle", "Iscc", "Report"])
def test_builder_is_fail_closed_at_injected_stages(
    tmp_path: Path, failure_stage: str
) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    completed = _run_builder(
        repo=repo,
        dist=dist,
        output=output,
        doctor=doctor,
        commit=commit,
        failure_stage=failure_stage,
    )
    assert completed.returncode != 0
    assert not any(path.exists() for path in _final_builder_paths(output))
    assert not list(output.glob(".build-*"))


def test_builder_success_publishes_all_outputs_with_setup_last(tmp_path: Path) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    completed = _run_builder(
        repo=repo, dist=dist, output=output, doctor=doctor, commit=commit
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    finals = _final_builder_paths(output)
    assert all(path.is_file() for path in finals)
    assert finals[-1].stat().st_mtime_ns > max(path.stat().st_mtime_ns for path in finals[:-1])
    report = json.loads((output / "build-report.json").read_text(encoding="utf-8-sig"))
    assert report["working_tree_change_count"] == 0
    assert report["output_mode"] == "single-file"
    assert report["release_asset_limit_bytes"] == 2_000_000_000
    assert report["model_bundle_bytes"] == 123
    assert report["model_file_count"] == 7
    assert report["model_manifest_sha256"] == "2" * 64
    assert report["setup_published_last"] is True
    assert report["publication_order"][-1].endswith("setup.exe")
    checksums = (output / "SHA256SUMS.txt").read_text(encoding="ascii")
    assert "ru-zh-live-subtitles-cpu-offline-0.2.0-setup.exe" in checksums
    assert not list(output.glob(".build-*"))


def test_builder_supports_unicode_and_space_paths(tmp_path: Path) -> None:
    fixture_root = tmp_path / "俄中 安装器"
    fixture_root.mkdir()
    repo, dist, output, doctor, commit = _make_builder_repo(fixture_root)
    completed = _run_builder(
        repo=repo,
        dist=dist,
        output=output,
        doctor=doctor,
        commit=commit,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert (output / "ru-zh-live-subtitles-cpu-offline-0.2.0-setup.exe").is_file()


def test_builder_uses_native_disk_spanning_before_release_limit(tmp_path: Path) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    completed = _run_builder(
        repo=repo,
        dist=dist,
        output=output,
        doctor=doctor,
        commit=commit,
        release_asset_limit_bytes=100,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((output / "build-report.json").read_text(encoding="utf-8-sig"))
    assert report["output_mode"] == "disk-spanning"
    assert (output / "ru-zh-live-subtitles-cpu-offline-0.2.0-setup-1.bin").is_file()
    assert all(item["size_bytes"] < 100 for item in report["output_files"])


def test_builder_rejects_any_release_asset_at_or_above_limit(tmp_path: Path) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    completed = _run_builder(
        repo=repo,
        dist=dist,
        output=output,
        doctor=doctor,
        commit=commit,
        force_disk_spanning=True,
        release_asset_limit_bytes=5,
    )
    assert completed.returncode != 0
    assert "Release asset size limit exceeded" in completed.stderr
    assert not any(path.exists() for path in _final_builder_paths(output))
    assert not list(output.glob("ru-zh-live-subtitles-cpu-offline-0.2.0-setup-*.bin"))


def test_release_metadata_contains_offline_bundle_flags(tmp_path: Path) -> None:
    metadata = load_release_metadata()
    repo, dist, commit = _make_real_git_release_repo(tmp_path)
    bundle_metadata = make_model_bundle_metadata(tmp_path / "bundle.json")
    payload = metadata.create_metadata(
        repo_root=repo,
        cpu_dist=dist,
        expected_commit=commit,
        inno_version="7.0.2",
        model_bundle_metadata=bundle_metadata,
        full_manifest=False,
    )
    assert payload["self_contained"] is True
    assert payload["offline_ready"] is True
    assert payload["model_bundle"]["self_contained"] is True
    assert payload["model_bundle"]["offline_ready"] is True
    assert payload["model_bundle"]["gigaam_variant"] == "large_ctc"
    assert payload["model_bundle"]["manifest_sha256"] == "2" * 64


@pytest.mark.parametrize("field", ["self_contained", "offline_ready"])
def test_release_metadata_rejects_incomplete_bundle_flags(
    tmp_path: Path, field: str
) -> None:
    metadata = load_release_metadata()
    bundle_metadata = make_model_bundle_metadata(tmp_path / "bundle.json")
    payload = json.loads(bundle_metadata.read_text(encoding="utf-8"))
    payload[field] = False
    bundle_metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(metadata.ReleaseMetadataError, match=field):
        metadata.read_model_bundle_metadata(bundle_metadata)


def test_release_metadata_rejects_model_bundle_absolute_path(tmp_path: Path) -> None:
    metadata = load_release_metadata()
    bundle_metadata = make_model_bundle_metadata(tmp_path / "bundle.json")
    payload = json.loads(bundle_metadata.read_text(encoding="utf-8"))
    payload["staging_path"] = r"C:\Users\someone\models"
    bundle_metadata.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(metadata.ReleaseMetadataError, match="absolute path"):
        metadata.read_model_bundle_metadata(bundle_metadata)


def test_builder_without_model_assets_root_fails_and_removes_stale_setup(
    tmp_path: Path,
) -> None:
    repo, dist, output, doctor, commit = _make_builder_repo(tmp_path)
    output.mkdir(parents=True, exist_ok=True)
    setup = output / "ru-zh-live-subtitles-cpu-offline-0.2.0-setup.exe"
    setup.write_bytes(b"stale")
    command = (
        "$builder=[scriptblock]::Create([IO.File]::ReadAllText("
        + _quote_powershell(BUILD_SCRIPT)
        + ")); & $builder"
        + " -RepoRoot " + _quote_powershell(repo)
        + " -CpuDist " + _quote_powershell(dist)
        + " -OutputDir " + _quote_powershell(output)
        + " -ExpectedCommit " + _quote_powershell(commit)
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_windows_powershell_env(),
    )
    assert completed.returncode != 0
    assert "ModelAssetsRoot is required" in completed.stderr
    assert not setup.exists()
