from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from zipfile import ZipFile

import pytest


def load_split_builder():
    path = Path(__file__).resolve().parents[1] / "packaging" / "installer" / "build_split_installer.py"
    spec = spec_from_file_location("split_installer", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_update_uses_existing_runtime_parts_without_copying_them(tmp_path, monkeypatch):
    builder = load_split_builder()
    runtime_zip = tmp_path / "runtime.zip"
    with ZipFile(runtime_zip, "w") as archive:
        archive.writestr("_internal/runtime.dll", b"retained")
        archive.writestr("models/model.dat", b"existing model")
    dll = tmp_path / "runtime.dll"
    dll.write_bytes(b"retained")
    app_zip = tmp_path / "app.zip"
    app_zip.write_bytes(b"app")
    staging = tmp_path / "staging"
    staging.mkdir()
    expected_parts = 2
    monkeypatch.setattr(builder, "RELEASE_ASSET_LIMIT", (runtime_zip.stat().st_size + 1) // 2 + 1)

    def compile_setup(command, *, check):
        assert check
        assert f"/DRuntimePartCount={expected_parts}" in command
        assert f"/DRuntimeZipSha256={builder.sha256_file(runtime_zip)}" in command
        assert "models/model.dat" in (staging / "runtime-files.txt").read_text(encoding="utf-8-sig")
        (staging / "setup.exe").write_bytes(b"setup")

    monkeypatch.setattr(builder.subprocess, "run", compile_setup)
    output = tmp_path / "out"
    builder.build_attachments(
        app_zip, runtime_zip, staging, output, tmp_path / "ISCC.exe", "0.4.2",
        reusable_files={"_internal/runtime.dll": dll},
    )
    assert sorted(path.name for path in output.iterdir()) == ["app.zip", "setup.exe"]

    dll.write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match the CPU build"):
        builder.write_runtime_manifest(runtime_zip, staging / "runtime-files.txt", {"_internal/runtime.dll": dll})
