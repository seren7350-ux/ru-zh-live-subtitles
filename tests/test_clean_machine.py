from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = PROJECT_ROOT / "packaging" / "clean_machine"
VALID_REVISION = "0123456789abcdef0123456789abcdef01234567"


def _windows_powershell_env(
    source: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Let Windows PowerShell rebuild its own module discovery path.

    GitHub Actions runs steps in PowerShell 7. A nested ``powershell.exe`` must
    not inherit PowerShell 7 module locations because an incompatible module
    can shadow the Windows PowerShell 5.1 module that provides Get-FileHash.
    """

    inherited = os.environ if source is None else source
    return {
        key: value
        for key, value in inherited.items()
        if key.casefold() != "psmodulepath"
    }


def _load(name: str) -> Any:
    path = TOOLKIT / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"clean_machine_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def prepare() -> Any:
    return _load("prepare_assets")


@pytest.fixture
def generator() -> Any:
    return _load("generate_sandbox_config")


def _template_root() -> ET.Element:
    return ET.fromstring((TOOLKIT / "sandbox-template.wsb").read_text(encoding="utf-8"))


def _mapping(root: ET.Element, sandbox_folder: str) -> ET.Element:
    return next(
        node
        for node in root.findall("./MappedFolders/MappedFolder")
        if node.findtext("SandboxFolder") == sandbox_folder
    )


def _folders(tmp_path: Path) -> dict[str, Path]:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    package = repo / "data" / "stage" / "package"
    scripts = repo / "data" / "stage" / "scripts"
    model = repo / "data" / "stage" / "model-assets"
    results = repo / "data" / "stage" / "results" / "run"
    for path in (repo, home, package, scripts, model, results):
        path.mkdir(parents=True, exist_ok=True)
    return {
        "repo": repo,
        "home": home,
        "package": package,
        "scripts": scripts,
        "model": model,
        "results": results,
    }


def test_sandbox_template_is_valid_xml() -> None:
    assert _template_root().tag == "Configuration"


def test_template_disables_networking() -> None:
    assert _template_root().findtext("Networking") == "Disable"


def test_template_enables_audio_input() -> None:
    assert _template_root().findtext("AudioInput") == "Enable"


def test_template_maps_package_read_only() -> None:
    mapping = _mapping(_template_root(), "PACKAGE_SANDBOX_FOLDER")
    assert mapping.findtext("ReadOnly") == "true"


def test_template_maps_model_assets_read_only() -> None:
    mapping = _mapping(_template_root(), "MODEL_SANDBOX_FOLDER")
    assert mapping.findtext("ReadOnly") == "true"


def test_template_only_maps_results_writable() -> None:
    root = _template_root()
    writable = [
        node.findtext("SandboxFolder")
        for node in root.findall("./MappedFolders/MappedFolder")
        if node.findtext("ReadOnly") == "false"
    ]
    assert writable == ["RESULTS_SANDBOX_FOLDER"]


def test_template_does_not_map_user_root() -> None:
    source = (TOOLKIT / "sandbox-template.wsb").read_text(encoding="utf-8")
    assert "Users\\" not in source


def test_template_does_not_map_repository() -> None:
    source = (TOOLKIT / "sandbox-template.wsb").read_text(encoding="utf-8")
    assert "ru-zh-live-subtitles" not in source


def test_template_does_not_map_virtual_environments() -> None:
    source = (TOOLKIT / "sandbox-template.wsb").read_text(encoding="utf-8")
    assert ".venv" not in source


def test_committed_template_has_no_machine_absolute_path() -> None:
    source = (TOOLKIT / "sandbox-template.wsb").read_text(encoding="utf-8")
    assert "C:\\" not in source
    assert str(PROJECT_ROOT) not in source


def test_generator_rejects_nonexistent_host_folder(
    tmp_path: Path, generator: Any
) -> None:
    folders = _folders(tmp_path)
    with pytest.raises(generator.SandboxConfigError, match="does not exist"):
        generator.validate_host_folder(
            tmp_path / "missing",
            role="package",
            repo_root=folders["repo"],
            user_home=folders["home"],
        )


def test_generator_rejects_nonempty_results_directory(
    tmp_path: Path, generator: Any
) -> None:
    folders = _folders(tmp_path)
    (folders["results"] / "old.json").write_text("{}", encoding="utf-8")
    with pytest.raises(generator.SandboxConfigError, match="must be empty"):
        generator.validate_host_folder(
            folders["results"],
            role="results",
            repo_root=folders["repo"],
            user_home=folders["home"],
        )


def test_generator_creates_unique_empty_results_subdirectory(
    tmp_path: Path, generator: Any
) -> None:
    root = tmp_path / "results"
    root.mkdir()
    first = generator.create_unique_results_directory(root, "package-only")
    second = generator.create_unique_results_directory(root, "package-only")
    assert first != second
    assert not any(first.iterdir()) and not any(second.iterdir())


def test_package_only_config_does_not_map_models(
    tmp_path: Path, generator: Any
) -> None:
    folders = _folders(tmp_path)
    xml = generator.build_sandbox_xml(
        package=folders["package"],
        scripts=folders["scripts"],
        results=folders["results"],
        memory_mb=8192,
    )
    assert "ModelAssets" not in xml
    assert "package_only_startup.ps1" in xml


def test_offline_config_maps_models_read_only(
    tmp_path: Path, generator: Any
) -> None:
    folders = _folders(tmp_path)
    xml = generator.build_sandbox_xml(
        package=folders["package"],
        scripts=folders["scripts"],
        results=folders["results"],
        memory_mb=8192,
        model_assets=folders["model"],
    )
    root = ET.fromstring(xml)
    mapping = _mapping(root, r"C:\Validation\ModelAssets")
    assert mapping.findtext("ReadOnly") == "true"
    assert "offline_cache_startup.ps1" in xml


def test_generator_rejects_repo_root_mapping(tmp_path: Path, generator: Any) -> None:
    folders = _folders(tmp_path)
    with pytest.raises(generator.SandboxConfigError, match="broad"):
        generator.validate_host_folder(
            folders["repo"],
            role="package",
            repo_root=folders["repo"],
            user_home=folders["home"],
        )


def test_generator_rejects_virtual_environment_mapping(
    tmp_path: Path, generator: Any
) -> None:
    folders = _folders(tmp_path)
    venv = folders["repo"] / ".venv" / "cache"
    venv.mkdir(parents=True)
    with pytest.raises(generator.SandboxConfigError, match="venv"):
        generator.validate_host_folder(
            venv,
            role="model",
            repo_root=folders["repo"],
            user_home=folders["home"],
        )


def test_memory_table_is_conservative(generator: Any) -> None:
    assert generator.sandbox_memory_mb(32_000_000_000) == 16384
    assert generator.sandbox_memory_mb(24_000_000_000) == 12288
    assert generator.sandbox_memory_mb(16_000_000_000) == 8192
    assert generator.sandbox_memory_mb(15_999_999_999) == 4096


def _fake_model_caches(tmp_path: Path, prepare: Any) -> tuple[Path, Path]:
    hub = tmp_path / "hub"
    silero = tmp_path / "silero"
    for spec in prepare.MODEL_SPECS:
        if spec.cache_name is None:
            source = silero
        else:
            cache = hub / spec.cache_name
            (cache / "refs").mkdir(parents=True, exist_ok=True)
            (cache / "refs" / "main").write_text(spec.revision + "\n", encoding="utf-8")
            source = cache / "snapshots" / spec.revision
        source.mkdir(parents=True, exist_ok=True)
        for name in spec.required_files:
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f"safe-{spec.key}-{name}".encode())
    return hub, silero


def test_revision_ref_encoder_returns_exact_ascii_bytes(prepare: Any) -> None:
    encoded = prepare.encode_huggingface_revision_ref(VALID_REVISION)
    assert encoded == VALID_REVISION.encode("ascii")
    assert len(encoded) == 40
    assert not encoded.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
    assert all(byte in b"0123456789abcdef" for byte in encoded)
    for forbidden in (b"\r", b"\n", b" ", b"\t", b"\x00"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        b"0" * 40,
        "0" * 39,
        "0" * 41,
        "A" * 40,
        " " + ("0" * 40),
        ("0" * 40) + " ",
        "\n" + ("0" * 40),
        ("0" * 40) + "\n",
        ("0" * 40) + "\r\n",
        ("0" * 39) + "é",
        ("0" * 39) + "\t",
        ("0" * 39) + "\x00",
    ],
)
def test_revision_ref_encoder_rejects_noncanonical_input(
    prepare: Any, invalid: object
) -> None:
    with pytest.raises(prepare.AssetPreparationError, match="revision"):
        prepare.encode_huggingface_revision_ref(invalid)


def test_source_revision_ref_records_bom_and_terminal_newline(
    tmp_path: Path, prepare: Any
) -> None:
    ref = tmp_path / "main"
    ref.write_bytes(b"\xef\xbb\xbf" + VALID_REVISION.encode("ascii") + b"\r\n")
    result = prepare.read_source_revision_ref(ref)
    assert result.revision == VALID_REVISION
    assert result.raw_size_bytes == 45
    assert result.has_utf8_bom is True
    assert result.has_cr is True
    assert result.has_lf is True
    assert result.terminal_newline == "crlf"


@pytest.mark.parametrize(
    "raw",
    [
        ("0" * 39).encode("ascii"),
        ("0" * 41).encode("ascii"),
        b" " + (b"0" * 40),
        (b"0" * 40) + b" ",
        b"\n" + (b"0" * 40),
        (b"0" * 39) + b"\t",
        (b"0" * 39) + b"\x00",
        b"\xff\xfe" + (b"0\x00" * 40),
        (b"0" * 39) + b"\xff",
    ],
)
def test_source_revision_ref_rejects_unsupported_bytes(
    tmp_path: Path, prepare: Any, raw: bytes
) -> None:
    ref = tmp_path / "main"
    ref.write_bytes(raw)
    with pytest.raises(prepare.AssetPreparationError):
        prepare.read_source_revision_ref(ref)


def test_model_manifest_contains_only_relative_paths(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    manifest = prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=tmp_path / "staged",
        user_home=tmp_path / "home",
    )
    paths = [file["path"] for model in manifest["models"] for file in model["files"]]
    assert paths and all(not Path(path).is_absolute() for path in paths)


def test_model_manifest_sha256_matches_staged_file(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    destination = tmp_path / "staged"
    manifest = prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=destination,
        user_home=tmp_path / "home",
    )
    record = manifest["models"][0]["files"][0]
    actual = hashlib.sha256((destination / record["path"]).read_bytes()).hexdigest()
    assert record["sha256"] == actual


def test_hugging_face_refs_are_covered_by_model_manifest(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    manifest = prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=tmp_path / "staged",
        user_home=tmp_path / "home",
    )
    paths = {file["path"] for model in manifest["models"] for file in model["files"]}
    assert any(path.endswith("models--ai-sage--GigaAM-Multilingual/refs/main") for path in paths)
    assert any(path.endswith("models--facebook--nllb-200-distilled-600M/refs/main") for path in paths)


def test_staged_hugging_face_refs_are_exact_and_manifested(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    destination = tmp_path / "staged"
    manifest = prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=destination,
        user_home=tmp_path / "home",
    )
    hf_models = [model for model in manifest["models"] if model["model_id"] != "silero-vad/6.2.1"]
    assert {model["model_id"] for model in hf_models} == {
        "ai-sage/GigaAM-Multilingual",
        "facebook/nllb-200-distilled-600M",
    }
    for model in hf_models:
        ref_record = next(record for record in model["files"] if record["path"].endswith("/refs/main"))
        ref = destination / ref_record["path"]
        raw = ref.read_bytes()
        assert raw == model["revision"].encode("ascii")
        assert len(raw) == ref_record["size_bytes"] == 40
        assert hashlib.sha256(raw).hexdigest() == ref_record["sha256"]
        assert not raw.startswith((b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"))
        assert b"\r" not in raw and b"\n" not in raw
        assert model["source_revision_ref"]["has_lf"] is True
        assert model["source_revision_ref"]["staged_size_bytes"] == 40


def test_staged_revision_refs_are_deterministic(tmp_path: Path, prepare: Any) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    first = tmp_path / "first"
    second = tmp_path / "second"
    prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=first,
        user_home=tmp_path / "home",
    )
    prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=second,
        user_home=tmp_path / "home",
    )
    for spec in prepare.MODEL_SPECS:
        if spec.cache_name is None:
            continue
        relative = Path("hf-home") / "hub" / spec.cache_name / "refs" / "main"
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_staged_cache_resolves_pinned_revision_without_network(
    tmp_path: Path, prepare: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from huggingface_hub import try_to_load_from_cache

    hub, silero = _fake_model_caches(tmp_path, prepare)
    destination = tmp_path / "staged"
    prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=destination,
        user_home=tmp_path / "home",
    )
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")

    def fail_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden in cache-layout tests")

    monkeypatch.setattr("socket.create_connection", fail_network)
    for spec in prepare.MODEL_SPECS:
        if spec.cache_name is None:
            continue
        resolved = try_to_load_from_cache(
            spec.model_id,
            spec.required_files[0],
            cache_dir=destination / "hf-home" / "hub",
            revision="main",
        )
        assert resolved is not None
        assert Path(resolved).is_file()
        assert spec.revision in Path(resolved).parts


def test_model_staging_rejects_extra_cache_file(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    (silero / "unapproved.pt").write_bytes(b"extra")
    with pytest.raises(prepare.AssetPreparationError, match="Unapproved files"):
        prepare.stage_models(
            hf_hub=hub,
            silero_cache=silero,
            destination=tmp_path / "staged",
            user_home=tmp_path / "home",
        )


def test_model_staging_rejects_token_content(tmp_path: Path, prepare: Any) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    (silero / "metadata.json").write_text(
        '{"token":"' + "hf_" + ("a" * 26) + '"}', encoding="utf-8"
    )
    with pytest.raises(prepare.AssetPreparationError, match="authentication token"):
        prepare.stage_models(
            hf_hub=hub,
            silero_cache=silero,
            destination=tmp_path / "staged",
            user_home=tmp_path / "home",
        )


def test_model_staging_rejects_bearer_authorization(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    (silero / "metadata.json").write_text(
        '{"header":"' + "Authorization: " + "Bearer " + "abcdefghijklmnop" + '"}',
        encoding="utf-8",
    )
    with pytest.raises(prepare.AssetPreparationError, match="authentication token"):
        prepare.stage_models(
            hf_hub=hub,
            silero_cache=silero,
            destination=tmp_path / "staged",
            user_home=tmp_path / "home",
        )


def test_model_staging_rejects_credentials_file(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    (silero / "credentials").write_text("secret", encoding="utf-8")
    with pytest.raises(prepare.AssetPreparationError, match="Unapproved files"):
        prepare.stage_models(
            hf_hub=hub,
            silero_cache=silero,
            destination=tmp_path / "staged",
            user_home=tmp_path / "home",
        )


def test_model_staging_has_exact_approved_model_ids(
    tmp_path: Path, prepare: Any
) -> None:
    hub, silero = _fake_model_caches(tmp_path, prepare)
    manifest = prepare.stage_models(
        hf_hub=hub,
        silero_cache=silero,
        destination=tmp_path / "staged",
        user_home=tmp_path / "home",
    )
    assert {model["model_id"] for model in manifest["models"]} == {
        "silero-vad/6.2.1",
        "ai-sage/GigaAM-Multilingual",
        "facebook/nllb-200-distilled-600M",
    }
    assert all(model["local_test_only"] for model in manifest["models"])
    assert all(not model["model_weights_bundled_in_application"] for model in manifest["models"])


def test_package_analysis_rejects_audio(tmp_path: Path, prepare: Any) -> None:
    package = tmp_path / "package"
    package.mkdir()
    for name in prepare.PACKAGE_EXES:
        (package / name).write_bytes(b"exe")
    (package / "private.wav").write_bytes(b"audio")
    with pytest.raises(prepare.AssetPreparationError, match="model/audio"):
        prepare.analyze_package(
            package, repo_root=tmp_path / "repo", user_home=tmp_path / "home"
        )


def test_package_analysis_rejects_embedded_user_path(
    tmp_path: Path, prepare: Any
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    for name in prepare.PACKAGE_EXES:
        (package / name).write_bytes(b"exe")
    user_home = tmp_path / "home"
    (package / "payload.txt").write_text(str(user_home / "private.txt"), encoding="utf-8")
    with pytest.raises(prepare.AssetPreparationError, match="host absolute path"):
        prepare.analyze_package(
            package, repo_root=tmp_path / "repo", user_home=user_home
        )


def test_package_analysis_allows_hf_substring_inside_wheel_record_hash(
    tmp_path: Path, prepare: Any
) -> None:
    package = tmp_path / "package"
    package.mkdir()
    for name in prepare.PACKAGE_EXES:
        (package / name).write_bytes(b"exe")
    (package / "RECORD").write_text(
        "module.py,sha256=gk3Hf_scyju0LM54eW7tYytddqFCPMCWrR_Ml1VlEFc,1\n",
        encoding="ascii",
    )

    analysis = prepare.analyze_package(
        package, repo_root=tmp_path / "repo", user_home=tmp_path / "home"
    )

    assert analysis["file_count"] == 3


def test_staged_file_verification_rejects_corruption(
    tmp_path: Path, prepare: Any
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    payload = staged / "payload.bin"
    payload.write_bytes(b"expected")
    records = [
        {
            "path": "payload.bin",
            "size_bytes": payload.stat().st_size,
            "sha256": prepare.sha256_file(payload),
        }
    ]
    payload.write_bytes(b"corrupt!")

    with pytest.raises(prepare.AssetPreparationError, match="SHA-256"):
        prepare.verify_staged_files(staged, records)


def test_staged_file_verification_rejects_unexpected_file(
    tmp_path: Path, prepare: Any
) -> None:
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "unexpected.bin").write_bytes(b"data")

    with pytest.raises(prepare.AssetPreparationError, match="file set"):
        prepare.verify_staged_files(staged, [])


def test_optional_test_wav_gets_relative_sha_manifest(
    tmp_path: Path, prepare: Any
) -> None:
    wav = tmp_path / "fixed.wav"
    import wave

    with wave.open(str(wav), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16_000)
        wav_file.writeframes(b"\x00\x00" * 160)
    payload = wav.read_bytes()
    destination = tmp_path / "scripts"
    prepare.stage_scripts(TOOLKIT, destination, test_wav=wav)
    manifest = json.loads(
        (destination / "test-audio-manifest.json").read_text(encoding="utf-8")
    )
    record = manifest["files"][0]
    assert record["path"] == "test-audio/sample.wav"
    assert not Path(record["path"]).is_absolute()
    assert record["sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["must_not_commit"] and manifest["must_not_upload"]


def test_optional_test_audio_rejects_non_wav(tmp_path: Path, prepare: Any) -> None:
    audio = tmp_path / "private.mp3"
    audio.write_bytes(b"audio")
    with pytest.raises(prepare.AssetPreparationError, match="existing WAV"):
        prepare.stage_scripts(TOOLKIT, tmp_path / "scripts", test_wav=audio)


def test_offline_script_sets_both_offline_variables() -> None:
    source = (TOOLKIT / "offline_cache_startup.ps1").read_text(encoding="utf-8")
    assert "$env:HF_HUB_OFFLINE = '1'" in source
    assert "$env:TRANSFORMERS_OFFLINE = '1'" in source


def test_offline_script_delimits_escaped_regex_variable() -> None:
    source = (TOOLKIT / "offline_cache_startup.ps1").read_text(encoding="utf-8")
    assert "${escaped}:" in source
    assert "$escaped:" not in source


def test_windows_powershell_env_removes_inherited_module_paths() -> None:
    cleaned = _windows_powershell_env(
        {
            "Path": "C:\\Windows\\System32",
            "PSModulePath": "C:\\Program Files\\PowerShell\\7\\Modules",
            "psmodulepath": "C:\\other-core-modules",
            "HF_HUB_OFFLINE": "1",
        }
    )

    assert cleaned == {
        "Path": "C:\\Windows\\System32",
        "HF_HUB_OFFLINE": "1",
    }


def test_asset_manifest_handles_one_file_under_strict_mode(tmp_path: Path) -> None:
    payload = b"single manifest record"
    asset = tmp_path / "sample.wav"
    asset.write_bytes(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": asset.name,
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = (
        "Set-StrictMode -Version Latest; "
        f". {quote(TOOLKIT / 'collect_results.ps1')}; "
        f"$result = Test-AssetManifest -Root {quote(tmp_path)} "
        f"-ManifestPath {quote(manifest)}; "
        "$result | ConvertTo-Json -Compress"
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_windows_powershell_env(),
    )
    result = json.loads(completed.stdout)
    assert completed.stderr.strip() == "", completed.stderr
    assert result["valid"] is True, result
    assert result["checked_files"] == 1
    assert result["failure_count"] == 0


def test_validation_command_preserves_spaced_arguments_and_exit_code(
    tmp_path: Path,
) -> None:
    probe_dir = tmp_path / "probe with spaces"
    probe_dir.mkdir()
    probe = probe_dir / "exit probe.ps1"
    probe.write_text(
        "param([string]$Value)\nWrite-Output $Value\nexit 7\n",
        encoding="utf-8",
    )
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = (
        "Set-StrictMode -Version Latest; "
        f". {quote(TOOLKIT / 'collect_results.ps1')}; "
        "$powershell = Join-Path $PSHOME 'powershell.exe'; "
        "$result = Invoke-ValidationCommand -Name 'probe' -FilePath $powershell "
        f"-Arguments @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', "
        f"'Bypass', '-File', {quote(probe)}, 'value with spaces'); "
        "$result | ConvertTo-Json -Compress"
    )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        check=True,
        capture_output=True,
        text=True,
        env=_windows_powershell_env(),
    )
    result = json.loads(completed.stdout)
    assert result["exit_code"] == 7
    assert result["timed_out"] is False
    assert "value with spaces" in result["output"]


def test_result_collection_redacts_tokens_paths_emails_and_captions() -> None:
    source = (TOOLKIT / "collect_results.ps1").read_text(encoding="utf-8")
    assert "<redacted-token>" in source
    assert "<redacted-path>" in source
    assert "<redacted-email>" in source
    assert "<redacted-caption>" in source


def test_startup_checks_absence_of_system_python_and_git() -> None:
    for script_name in ("package_only_startup.ps1", "offline_cache_startup.ps1"):
        source = (TOOLKIT / script_name).read_text(encoding="utf-8")
        for executable in ("python.exe", "py.exe", "pip.exe", "git.exe"):
            assert executable in source
        assert "Get-Command -Name $name -CommandType Application" in source
        assert "-ErrorAction SilentlyContinue" in source
        assert "where.exe" not in source


def test_package_startup_scans_with_defender_only_when_available() -> None:
    source = (TOOLKIT / "package_only_startup.ps1").read_text(encoding="utf-8")
    assert "MpCmdRun.exe" in source
    assert "defender-package-scan" in source
    assert "Set-MpPreference" not in source
    assert "Add-MpPreference" not in source


def test_cuda_status_is_based_on_actual_runtime_output_not_vgpu() -> None:
    source = (TOOLKIT / "offline_cache_startup.ps1").read_text(encoding="utf-8")
    assert "CUDA available" in source
    assert "actual_cuda_available" in source
    assert "VGpu" not in source and "vGPU" not in source


def test_cpu_and_cuda_result_states_remain_distinct() -> None:
    source = (TOOLKIT / "offline_cache_startup.ps1").read_text(encoding="utf-8")
    assert "$result.runtime.selected_translation_device" in source
    assert "$result.runtime.cuda_available -eq 'True'" in source
    assert "$result.runtime.torch_cuda_version -eq 'None'" in source
    assert "$result.runtime.selected_translation_device -eq 'cpu'" in source
    assert "ExpectedRuntimeFamily -eq 'cpu'" in source


def test_result_schema_is_valid_json_and_never_requires_caption_text() -> None:
    schema = json.loads((TOOLKIT / "result-schema.json").read_text(encoding="utf-8"))
    assert schema["properties"]["phase"]["enum"] == ["package-only", "offline-cache"]
    serialized = json.dumps(schema).casefold()
    assert "russian_text" not in serialized and "chinese_text" not in serialized
