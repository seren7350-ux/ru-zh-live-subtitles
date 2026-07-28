from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from live_subtitles.model_assets import ModelAssetSpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "offline_model_bundle", PROJECT_ROOT / "packaging" / "model_bundle.py"
)
assert _SPEC and _SPEC.loader
model_bundle = importlib.util.module_from_spec(_SPEC)
sys_modules_name = _SPEC.name
sys.modules[sys_modules_name] = model_bundle
_SPEC.loader.exec_module(model_bundle)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "path": path.as_posix(),
        "size_bytes": len(data),
        "sha256": _sha(data),
    }


def _fake_bundle(tmp_path: Path) -> tuple[Path, tuple[ModelAssetSpec, ...], dict[str, str]]:
    root = tmp_path / "model-assets"
    silero = ModelAssetSpec(
        key="silero-vad",
        model_id="silero-vad/6.2.1",
        cache_name=None,
        revision="6.2.1",
        required_files=("LICENSE", "metadata.json", "silero_vad.onnx"),
        expected_sizes=(("silero_vad.onnx", 6),),
        license_id="MIT",
    )
    gigaam = ModelAssetSpec(
        key="gigaam-v3-e2e-rnnt",
        model_id="istupakov/gigaam-v3-onnx",
        cache_name="models--istupakov--gigaam-v3-onnx",
        revision=model_bundle.GIGAAM_REVISION,
        required_files=("config.json",),
        expected_sizes=(("config.json", 2),),
        license_id="MIT",
    )
    nllb = ModelAssetSpec(
        key="nllb-200-distilled-600m",
        model_id="facebook/nllb-200-distilled-600M",
        cache_name="models--facebook--nllb-200-distilled-600M",
        revision=model_bundle.NLLB_REVISION,
        required_files=("config.json",),
        expected_sizes=(("config.json", 2),),
        license_id="CC-BY-NC-4.0",
    )
    specs = (silero, gigaam, nllb)
    content = {
        "silero-vad/6.2.1/LICENSE": b"MIT",
        "silero-vad/6.2.1/metadata.json": b"{}",
        "silero-vad/6.2.1/silero_vad.onnx": b"silero",
        (
            "hf-home/hub/models--istupakov--gigaam-v3-onnx/refs/main"
        ): model_bundle.GIGAAM_REVISION.encode("ascii"),
        (
            "hf-home/hub/models--istupakov--gigaam-v3-onnx/snapshots/"
            f"{model_bundle.GIGAAM_REVISION}/config.json"
        ): b"{}",
        (
            "hf-home/hub/models--facebook--nllb-200-distilled-600M/refs/main"
        ): model_bundle.NLLB_REVISION.encode("ascii"),
        (
            "hf-home/hub/models--facebook--nllb-200-distilled-600M/snapshots/"
            f"{model_bundle.NLLB_REVISION}/config.json"
        ): b"{}",
    }
    records = {}
    for relative, data in content.items():
        path = root / Path(*relative.split("/"))
        record = _write(path, data)
        record["path"] = relative
        records[relative] = record
    models = []
    for spec in specs:
        expected = set(model_bundle._expected_paths(spec))
        files = [records[path] for path in sorted(expected)]
        models.append(
            {
                "key": spec.key,
                "model_id": spec.model_id,
                "revision": spec.revision,
                "license": spec.license_id,
                "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
                "files": files,
            }
        )
    manifest = {
        "schema_version": 1,
        "models": models,
        "total_size_bytes": sum(len(data) for data in content.values()),
    }
    (root / model_bundle.MANIFEST_NAME).write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root, specs, {"silero-vad/6.2.1/silero_vad.onnx": _sha(b"silero")}


def _validate(root: Path, specs: tuple[ModelAssetSpec, ...], fixed: dict[str, str]):
    return model_bundle.validate_model_bundle(root, specs=specs, fixed_sha256=fixed)


def _manifest(root: Path) -> dict[str, object]:
    return json.loads((root / model_bundle.MANIFEST_NAME).read_text(encoding="utf-8"))


def _rewrite_manifest(root: Path, payload: dict[str, object]) -> None:
    (root / model_bundle.MANIFEST_NAME).write_text(json.dumps(payload), encoding="utf-8")


def test_valid_bundle_creates_path_free_metadata(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    result = _validate(root, specs, fixed)
    rendered = json.dumps(result.metadata)
    assert result.metadata["file_count"] == 7
    assert result.metadata["bundle_type"] == "offline-model-assets"
    assert str(tmp_path) not in rendered
    assert model_bundle.GIGAAM_REVISION in rendered
    assert model_bundle.NLLB_REVISION in rendered


@pytest.mark.parametrize("suffix", [b"\r\n", b"\n"])
def test_revision_ref_rejects_newline(tmp_path: Path, suffix: bytes) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    ref = root / "hf-home/hub/models--istupakov--gigaam-v3-onnx/refs/main"
    ref.write_bytes(model_bundle.GIGAAM_REVISION.encode("ascii") + suffix)
    with pytest.raises(model_bundle.ModelBundleError, match="Size mismatch|40 bytes"):
        _validate(root, specs, fixed)


def test_revision_ref_rejects_wrong_revision_even_with_updated_manifest(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    relative = "hf-home/hub/models--istupakov--gigaam-v3-onnx/refs/main"
    ref = root / Path(*relative.split("/"))
    ref.write_bytes(b"0" * 40)
    manifest = _manifest(root)
    for model in manifest["models"]:
        for record in model["files"]:
            if record["path"] == relative:
                record["sha256"] = _sha(b"0" * 40)
    _rewrite_manifest(root, manifest)
    with pytest.raises(model_bundle.ModelBundleError, match="pinned revision"):
        _validate(root, specs, fixed)


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    (root / "silero-vad/6.2.1/LICENSE").unlink()
    with pytest.raises(model_bundle.ModelBundleError, match="Bundle file set mismatch"):
        _validate(root, specs, fixed)


def test_wrong_file_size_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    (root / "silero-vad/6.2.1/silero_vad.onnx").write_bytes(b"short")
    with pytest.raises(model_bundle.ModelBundleError, match="Size mismatch"):
        _validate(root, specs, fixed)


def test_wrong_file_sha_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    path = root / "silero-vad/6.2.1/LICENSE"
    path.write_bytes(b"BAD")
    with pytest.raises(model_bundle.ModelBundleError, match="SHA-256 mismatch"):
        _validate(root, specs, fixed)


def test_pinned_silero_sha_is_rejected_even_if_manifest_matches(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    relative = "silero-vad/6.2.1/silero_vad.onnx"
    path = root / Path(*relative.split("/"))
    path.write_bytes(b"broken")
    manifest = _manifest(root)
    for model in manifest["models"]:
        for record in model["files"]:
            if record["path"] == relative:
                record["sha256"] = _sha(b"broken")
    _rewrite_manifest(root, manifest)
    with pytest.raises(model_bundle.ModelBundleError, match="Pinned SHA-256"):
        _validate(root, specs, fixed)


def test_extra_model_weight_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    (root / "extra.bin").write_bytes(b"weight")
    with pytest.raises(model_bundle.ModelBundleError, match="extra.bin"):
        _validate(root, specs, fixed)


def test_unsafe_absolute_manifest_path_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["models"][0]["files"][0]["path"] = "C:/secret/model.bin"
    _rewrite_manifest(root, manifest)
    with pytest.raises(model_bundle.ModelBundleError, match="unsafe"):
        _validate(root, specs, fixed)


def test_manifest_identity_and_total_are_validated(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    manifest = _manifest(root)
    manifest["models"][2]["revision"] = "0" * 40
    _rewrite_manifest(root, manifest)
    with pytest.raises(model_bundle.ModelBundleError, match="revision mismatch"):
        _validate(root, specs, fixed)


def test_invalid_manifest_json_is_rejected(tmp_path: Path) -> None:
    root, specs, fixed = _fake_bundle(tmp_path)
    (root / model_bundle.MANIFEST_NAME).write_text("{", encoding="utf-8")
    with pytest.raises(model_bundle.ModelBundleError, match="cannot be read"):
        _validate(root, specs, fixed)
