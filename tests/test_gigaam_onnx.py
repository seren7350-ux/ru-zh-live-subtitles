from __future__ import annotations

import importlib
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.asr import gigaam_onnx
from live_subtitles.asr.gigaam_onnx import (
    GigaAMOnnxRecognizer,
    InvalidAudioFileError,
    ProviderUnavailableError,
)


def write_wav(path: Path, *, frames: int = 16_000, sample_rate: int = 16_000) -> Path:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)
    return path


class FakeModel:
    def __init__(self, results: list[str] | None = None) -> None:
        self.results = results or ["Здравствуйте."]
        self.paths: list[Path] = []

    def recognize(self, path: Path) -> str:
        self.paths.append(path)
        return self.results[min(len(self.paths) - 1, len(self.results) - 1)]


def install_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    providers: list[str] | None = None,
    results: list[str] | None = None,
) -> tuple[FakeModel, list[tuple[str, list[str]]]]:
    model = FakeModel(results)
    load_calls: list[tuple[str, list[str]]] = []
    fake_ort = SimpleNamespace(get_available_providers=lambda: providers or ["CPUExecutionProvider"])

    def load_model(name: str, *, providers: list[str]):
        load_calls.append((name, providers))
        return model

    fake_asr = SimpleNamespace(load_model=load_model)
    real_import = importlib.import_module

    def fake_import(name: str):
        if name == "onnxruntime":
            return fake_ort
        if name == "onnx_asr":
            return fake_asr
        return real_import(name)

    monkeypatch.setattr(gigaam_onnx.importlib, "import_module", fake_import)
    return model, load_calls


def test_import_does_not_load_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(gigaam_onnx.importlib, "import_module", lambda name: calls.append(name))
    GigaAMOnnxRecognizer()
    assert calls == []


def test_model_load_is_deferred_and_happens_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "speech.wav")
    model, load_calls = install_fake_runtime(monkeypatch, results=["one", "two"])
    times = iter([1.0, 1.4, 2.0, 2.2, 3.0, 3.1])
    recognizer = GigaAMOnnxRecognizer(clock=lambda: next(times))

    assert load_calls == []
    assert recognizer.transcribe_file(audio) == "one"
    assert recognizer.transcribe_file(audio) == "two"
    assert load_calls == [("gigaam-v3-e2e-rnnt", ["CPUExecutionProvider"])]
    assert model.paths == [audio.resolve(), audio.resolve()]
    assert recognizer.last_metrics is not None
    assert recognizer.last_metrics.model_load_seconds == pytest.approx(0.4)


def test_unavailable_provider_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "speech.wav")
    _, load_calls = install_fake_runtime(monkeypatch, providers=["CPUExecutionProvider"])
    recognizer = GigaAMOnnxRecognizer(provider="CUDAExecutionProvider")
    with pytest.raises(ProviderUnavailableError, match="Available providers: CPUExecutionProvider"):
        recognizer.transcribe_file(audio)
    assert load_calls == []


def test_empty_audio_has_no_division_by_zero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "empty.wav", frames=0)
    install_fake_runtime(monkeypatch, results=[""])
    times = iter([1.0, 1.1, 2.0, 2.1])
    recognizer = GigaAMOnnxRecognizer(clock=lambda: next(times))
    with pytest.warns(RuntimeWarning, match="empty transcription"):
        assert recognizer.transcribe_file(audio) == ""
    assert recognizer.last_metrics is not None
    assert recognizer.last_metrics.audio_duration_seconds == 0
    assert recognizer.last_metrics.rtf is None


def test_missing_audio_is_rejected_before_model_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, load_calls = install_fake_runtime(monkeypatch)
    with pytest.raises(InvalidAudioFileError, match="does not exist"):
        GigaAMOnnxRecognizer().transcribe_file(tmp_path / "missing.wav")
    assert load_calls == []


def test_non_wav_is_rejected_before_model_load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, load_calls = install_fake_runtime(monkeypatch)
    text_path = tmp_path / "speech.mp3"
    text_path.write_bytes(b"not an mp3")
    with pytest.raises(InvalidAudioFileError, match="Only .wav"):
        GigaAMOnnxRecognizer().transcribe_file(text_path)
    assert load_calls == []


def test_source_does_not_contain_user_absolute_path() -> None:
    source_root = Path(__file__).parents[1] / "src"
    sources = "\n".join(path.read_text(encoding="utf-8") for path in source_root.rglob("*.py"))
    assert "C:\\Users\\seren" not in sources
