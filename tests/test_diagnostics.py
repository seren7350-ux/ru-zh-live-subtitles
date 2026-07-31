from __future__ import annotations

from types import SimpleNamespace

import pytest

from live_subtitles import diagnostics


class FakeSoundDevice:
    __version__ = "test"
    default = SimpleNamespace(device=(-1, -1))

    @staticmethod
    def query_devices() -> list[dict[str, object]]:
        return []


def test_doctor_survives_missing_onnxruntime_and_never_loads_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_calls: list[object] = []
    fake_modules = {
        "numpy": SimpleNamespace(__version__="2.test"),
        "sounddevice": FakeSoundDevice(),
        "torch": SimpleNamespace(__version__="2.10.test"),
        "torchaudio": SimpleNamespace(__version__="2.10.test"),
        "transformers": SimpleNamespace(__version__="5.test"),
        "hydra": SimpleNamespace(__version__="1.3.test"),
        "omegaconf": SimpleNamespace(__version__="2.3.test"),
        "onnx_asr": SimpleNamespace(
            __version__="0.12.0",
            load_model=lambda *args, **kwargs: load_calls.append((args, kwargs)),
        ),
    }

    def fake_import(name: str):
        if name == "onnxruntime":
            raise ImportError("simulated missing runtime")
        return fake_modules[name]

    monkeypatch.setattr(diagnostics.importlib, "import_module", fake_import)
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)

    report = diagnostics.collect_diagnostics()
    rendered = diagnostics.format_report(report)

    assert "[FAIL] onnxruntime: not importable" in rendered
    assert "Summary:" in rendered
    assert report.exit_code == 1
    assert load_calls == []


def test_doctor_reports_cpu_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_modules = {
        "numpy": SimpleNamespace(__version__="2.test"),
        "sounddevice": FakeSoundDevice(),
        "torch": SimpleNamespace(__version__="2.10.test"),
        "torchaudio": SimpleNamespace(__version__="2.10.test"),
        "transformers": SimpleNamespace(__version__="5.test"),
        "hydra": SimpleNamespace(__version__="1.3.test"),
        "omegaconf": SimpleNamespace(__version__="2.3.test"),
        "onnx_asr": SimpleNamespace(__version__="0.12.0"),
        "onnxruntime": SimpleNamespace(
            __version__="test",
            get_available_providers=lambda: ["CPUExecutionProvider"],
        ),
    }
    monkeypatch.setattr(diagnostics.importlib, "import_module", lambda name: fake_modules[name])
    monkeypatch.setattr(diagnostics.shutil, "which", lambda _: None)

    report = diagnostics.collect_diagnostics()
    cpu_check = next(check for check in report.checks if check.name == "CPUExecutionProvider")
    cuda_check = next(check for check in report.checks if check.name == "CUDAExecutionProvider")
    assert cpu_check.status == "OK"
    assert cuda_check.status == "WARN"
