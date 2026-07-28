from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from live_subtitles import cli, model_assets
from live_subtitles.model_assets import ModelAssetSpec


def compact_specs() -> tuple[ModelAssetSpec, ...]:
    return (
        ModelAssetSpec(
            "silero-vad",
            "silero-vad/6.2.1",
            None,
            "6.2.1",
            ("LICENSE", "metadata.json", "silero_vad.onnx"),
            (("silero_vad.onnx", 1),),
            "MIT",
        ),
        ModelAssetSpec(
            "gigaam",
            model_assets.GIGAAM_MODEL_ID,
            "models--istupakov--gigaam-v3-onnx",
            model_assets.GIGAAM_REVISION,
            ("config.json", "model.onnx"),
            (("config.json", 1), ("model.onnx", 1)),
            "MIT",
        ),
        ModelAssetSpec(
            "nllb",
            model_assets.NLLB_MODEL_ID,
            "models--facebook--nllb-200-distilled-600M",
            model_assets.NLLB_REVISION,
            ("config.json", "pytorch_model.bin"),
            (("config.json", 1), ("pytorch_model.bin", 1)),
            "CC-BY-NC-4.0",
        ),
    )


def make_ready_tree(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    models = root / "models"
    silero = models / "silero-vad" / "6.2.1"
    silero.mkdir(parents=True)
    for name in ("LICENSE", "metadata.json", "silero_vad.onnx"):
        (silero / name).write_bytes(b"x")
    vad_assets = importlib.import_module("live_subtitles.realtime.vad_assets")
    monkeypatch.setattr(vad_assets, "validate_vad_assets", lambda _path: object())

    hub = models / "hf-home" / "hub"
    for spec in compact_specs()[1:]:
        repository = hub / str(spec.cache_name)
        (repository / "refs").mkdir(parents=True)
        (repository / "refs" / "main").write_bytes(spec.revision.encode("ascii"))
        snapshot = repository / "snapshots" / spec.revision
        snapshot.mkdir(parents=True)
        for name in spec.required_files:
            (snapshot / name).write_bytes(b"x")
    monkeypatch.setattr(model_assets, "MODEL_SPECS", compact_specs())
    return models, hub


def test_pinned_model_ids_and_revisions_are_canonical() -> None:
    assert model_assets.GIGAAM_MODEL_ID == "istupakov/gigaam-v3-onnx"
    assert model_assets.GIGAAM_REVISION == "322c3b29492673eb7d0b434bfa9dfb8653e34d02"
    assert model_assets.NLLB_MODEL_ID == "facebook/nllb-200-distilled-600M"
    assert model_assets.NLLB_REVISION == "f8d333a098d19b4fd9a8b18f94170487ad3f821d"


def test_hf_cache_priority_preserves_explicit_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache = tmp_path / "explicit-cache"
    home = tmp_path / "explicit-home"
    monkeypatch.setenv("HF_HUB_CACHE", str(cache))
    monkeypatch.setenv("HF_HOME", str(home))
    assert model_assets.hugging_face_cache_candidates() == (cache,)
    monkeypatch.delenv("HF_HUB_CACHE")
    assert model_assets.hugging_face_cache_candidates() == (home / "hub",)


def test_managed_cache_precedes_existing_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.setattr(model_assets, "default_hf_hub_cache", lambda: tmp_path / "default")
    assert model_assets.hugging_face_cache_candidates(tmp_path / "models") == (
        tmp_path / "models" / "hf-home" / "hub",
        tmp_path / "default",
    )


def test_quick_check_accepts_complete_pinned_assets_without_loading_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    models, hub = make_ready_tree(tmp_path, monkeypatch)
    report = model_assets.quick_check_model_assets(
        model_root=models, hf_cache_roots=(hub,)
    )
    assert report.ready
    assert all(status.ready for status in report.statuses)


@pytest.mark.parametrize("payload", [b"a" * 40 + b"\r\n", b"F" * 40, b"0" * 40])
def test_quick_check_rejects_ref_newlines_case_or_wrong_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: bytes
) -> None:
    models, hub = make_ready_tree(tmp_path, monkeypatch)
    ref = hub / "models--istupakov--gigaam-v3-onnx" / "refs" / "main"
    ref.write_bytes(payload)
    report = model_assets.quick_check_model_assets(
        model_root=models, hf_cache_roots=(hub,)
    )
    gigaam = next(status for status in report.statuses if status.key == "gigaam")
    assert not gigaam.ready
    assert gigaam.problems


def test_missing_or_empty_file_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    models, hub = make_ready_tree(tmp_path, monkeypatch)
    model = (
        hub
        / "models--facebook--nllb-200-distilled-600M"
        / "snapshots"
        / model_assets.NLLB_REVISION
        / "pytorch_model.bin"
    )
    model.write_bytes(b"")
    report = model_assets.quick_check_model_assets(
        model_root=models, hf_cache_roots=(hub,)
    )
    assert not report.ready
    assert "empty" in " ".join(report.statuses[-1].problems)


def test_offline_environment_is_process_local_and_respects_explicit_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    explicit = tmp_path / "explicit"
    monkeypatch.setenv("HF_HOME", str(explicit))
    model_assets.configure_offline_environment()
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_HOME"] == str(explicit)


def test_model_doctor_reports_nonzero_without_importing_model_runtimes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = model_assets.ModelAssetsReport(
        tmp_path / "models",
        tmp_path / "hub",
        (
            model_assets.ModelAssetStatus(
                "nllb",
                model_assets.NLLB_MODEL_ID,
                model_assets.NLLB_REVISION,
                False,
                tmp_path / "missing",
                tmp_path / "hub",
                ("pytorch_model.bin",),
            ),
        ),
    )
    monkeypatch.setattr(cli, "quick_check_model_assets", lambda: report)
    assert cli.main(["model-doctor"]) == 2
    output = capsys.readouterr().out
    assert "Offline readiness: NOT READY" in output
    source = Path(model_assets.__file__).read_text(encoding="utf-8")
    assert "import torch" not in source
    assert "import transformers" not in source
    assert "import onnxruntime" not in source
