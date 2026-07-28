from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.translation import diagnostics


def test_translation_doctor_does_not_load_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    load_calls: list[object] = []
    fake_torch = SimpleNamespace(
        __version__="2.test",
        version=SimpleNamespace(cuda="13.0"),
        cuda=SimpleNamespace(
            is_available=lambda: True,
            get_device_name=lambda _: "Fake GPU",
        ),
    )
    fake_transformers = SimpleNamespace(
        __version__="5.test",
        AutoModelForSeq2SeqLM=SimpleNamespace(
            from_pretrained=lambda *args, **kwargs: load_calls.append((args, kwargs))
        ),
    )
    modules = {"torch": fake_torch, "transformers": fake_transformers}
    monkeypatch.setattr(diagnostics.importlib, "import_module", lambda name: modules[name])
    monkeypatch.setattr(diagnostics, "hugging_face_model_cache_dir", lambda _: tmp_path / "not-cached")
    monkeypatch.setattr(diagnostics, "is_frozen", lambda: True)

    report = diagnostics.collect_translation_diagnostics()
    names = {check.name: check for check in report.checks}
    assert names["CUDA available"].status == "OK"
    assert names["CUDA device"].detail == "Fake GPU"
    assert names["Package runtime family"].detail == "gpu"
    assert names["Torch CUDA version"].detail == "13.0"
    assert names["Selected translation device"].detail == "cuda"
    assert names["Frozen state"].detail == "True"
    assert names["Default translation candidate"].detail == (
        "nllb: facebook/nllb-200-distilled-600M"
    )
    assert names["Model cache"].status == "WARN"
    assert load_calls == []


def test_cpu_frozen_runtime_metadata_selects_cpu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_torch = SimpleNamespace(
        __version__="2.12.1+cpu",
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(
            is_available=lambda: False,
            get_device_name=lambda _: pytest.fail("CPU runtime queried a CUDA device"),
        ),
    )
    fake_transformers = SimpleNamespace(__version__="5.test")
    modules = {"torch": fake_torch, "transformers": fake_transformers}
    monkeypatch.setattr(diagnostics.importlib, "import_module", lambda name: modules[name])
    monkeypatch.setattr(diagnostics, "is_frozen", lambda: True)
    monkeypatch.setattr(
        diagnostics,
        "hugging_face_model_cache_dir",
        lambda _: tmp_path / "cached-model",
    )

    report = diagnostics.collect_translation_diagnostics()
    names = {check.name: check for check in report.checks}
    assert names["Package runtime family"].detail == "cpu"
    assert names["Torch CUDA version"].detail == "None"
    assert names["CUDA available"].detail == "False"
    assert names["Selected translation device"].detail == "cpu"
    assert names["Frozen state"].detail == "True"
