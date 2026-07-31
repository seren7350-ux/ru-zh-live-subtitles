from __future__ import annotations

import os
import wave
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from live_subtitles.asr.base import (
    AudioTranscriptionError,
    InvalidAudioFileError,
    ModelLoadError,
    ProviderUnavailableError,
    SpeechRecognizer,
)
from live_subtitles.asr import factory
from live_subtitles.asr import gigaam_multilingual_ctc as backend
from live_subtitles.asr.gigaam_multilingual_ctc import (
    GigaAMMultilingualCtcRecognizer,
)
from live_subtitles.config import (
    DEFAULT_ASR_BACKEND,
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    GIGAAM_MULTILINGUAL_BACKEND,
    LEGACY_GIGAAM_ONNX_BACKEND,
)
from live_subtitles.model_assets import (
    GIGAAM_MULTILINGUAL_MODEL_ID,
    GIGAAM_MULTILINGUAL_REVISION,
    GIGAAM_MULTILINGUAL_VARIANT,
    LEGACY_GIGAAM_SPEC,
    MODEL_SPECS,
)
from live_subtitles.pipeline.offline_file import OfflineAudioTranslationPipeline


def write_wav(
    path: Path,
    *,
    frames: int = 16_000,
    sample_rate: int = 16_000,
    channels: int = 1,
) -> Path:
    values = np.zeros((frames, channels), dtype="<i2")
    if frames:
        values[:, 0] = 4_000
        if channels > 1:
            values[:, 1] = -2_000
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(values.tobytes())
    return path


class FakeModel:
    def __init__(self) -> None:
        self.eval_calls = 0
        self.devices: list[str] = []

    def eval(self) -> "FakeModel":
        self.eval_calls += 1
        return self

    def to(self, device: str) -> "FakeModel":
        self.devices.append(device)
        return self


class FakeAutoModel:
    def __init__(self, model: FakeModel, error: Exception | None = None) -> None:
        self.model = model
        self.error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def from_pretrained(self, path: str, **kwargs: Any) -> FakeModel:
        self.calls.append((path, kwargs))
        if self.error:
            raise self.error
        return self.model


def fake_runtime(auto_model: FakeAutoModel, *, cuda: bool = False) -> Any:
    dynamic = SimpleNamespace(get_imports=lambda _path: ["torch", "pyannote"])
    torch = SimpleNamespace(
        __version__="2.10.0+cpu",
        cuda=SimpleNamespace(is_available=lambda: cuda),
    )
    return backend._Runtime(
        torch=torch,
        torchaudio=SimpleNamespace(__version__="2.10.0+cpu"),
        transformers=SimpleNamespace(__version__="5.14.1", AutoModel=auto_model),
        dynamic_module_utils=dynamic,
    )


def recognizer_with_fakes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    results: list[str] | None = None,
    times: list[float] | None = None,
    load_error: Exception | None = None,
    provider: str = "cpu",
) -> tuple[GigaAMMultilingualCtcRecognizer, FakeAutoModel, list[Any]]:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    model = FakeModel()
    auto_model = FakeAutoModel(model, load_error)
    runtime = fake_runtime(auto_model, cuda=provider == "cuda")
    calls: list[Any] = []
    outputs = iter(results or ["русский текст"])

    def infer(_model: Any, audio: Any, _runtime: Any, device: str) -> str:
        calls.append((audio, device))
        return next(outputs)

    monkeypatch.setattr(backend, "_validate_snapshot", lambda path: path.resolve())
    monkeypatch.setattr(backend, "_official_remote_code_imports", lambda _runtime: nullcontext())
    clock_values = iter(times or [1.0, 1.25, 2.0, 2.5, 3.0, 3.25])
    recognizer = GigaAMMultilingualCtcRecognizer(
        provider=provider,
        snapshot_path=snapshot,
        clock=lambda: next(clock_values),
        runtime_loader=lambda: runtime,
        inference_runner=infer,
    )
    return recognizer, auto_model, calls


def test_backend_satisfies_protocol_and_is_lazy() -> None:
    recognizer = GigaAMMultilingualCtcRecognizer(snapshot_path=Path("unused"))
    assert isinstance(recognizer, SpeechRecognizer)
    assert recognizer.model_name == GIGAAM_MULTILINGUAL_MODEL_ID
    assert recognizer.provider == "cpu"
    assert recognizer.model_load_count == 0
    assert recognizer.last_metrics is None


def test_prepare_loads_once_with_fixed_local_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recognizer, auto_model, _ = recognizer_with_fakes(monkeypatch, tmp_path)
    assert recognizer.prepare() == pytest.approx(0.25)
    assert recognizer.prepare() == pytest.approx(0.25)
    assert recognizer.model_load_count == 1
    assert len(auto_model.calls) == 1
    _, kwargs = auto_model.calls[0]
    assert kwargs == {
        "revision": GIGAAM_MULTILINGUAL_REVISION,
        "trust_remote_code": True,
        "local_files_only": True,
    }
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_transcribe_auto_prepares_reuses_model_and_records_metrics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = write_wav(tmp_path / "speech.wav")
    recognizer, auto_model, calls = recognizer_with_fakes(
        monkeypatch,
        tmp_path,
        results=["первый", "второй"],
        times=[1.0, 1.25, 2.0, 2.5, 3.0, 3.25],
    )
    assert recognizer.transcribe_file(audio) == "первый"
    assert recognizer.transcribe_file(audio) == "второй"
    assert len(auto_model.calls) == 1
    assert len(calls) == 2
    assert recognizer.model_load_count == 1
    assert recognizer.last_metrics is not None
    assert recognizer.last_metrics.audio_duration_seconds == 1.0
    assert recognizer.last_metrics.model_load_seconds == pytest.approx(0.25)
    assert recognizer.last_metrics.recognition_seconds == pytest.approx(0.25)
    assert recognizer.last_metrics.rtf == pytest.approx(0.25)


def test_official_model_identity_variant_revision_license_and_files() -> None:
    spec = next(spec for spec in MODEL_SPECS if spec.key == "gigaam-multilingual-large-ctc")
    assert GIGAAM_MULTILINGUAL_MODEL_ID == "ai-sage/GigaAM-Multilingual"
    assert GIGAAM_MULTILINGUAL_VARIANT == "large_ctc"
    assert GIGAAM_MULTILINGUAL_REVISION == "3905cd51c3ed4e88c8edf33f3302969ba480a327"
    assert spec.variant == "large_ctc"
    assert spec.license_id == "MIT"
    assert spec.revision == GIGAAM_MULTILINGUAL_REVISION
    assert spec.required_files == (
        ".gitattributes",
        "README.md",
        "config.json",
        "modeling_gigaam.py",
        "pytorch_model.bin",
    )
    assert dict(spec.expected_sizes)["pytorch_model.bin"] == 2_341_592_643


def test_missing_snapshot_and_model_load_errors_are_mapped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    missing = GigaAMMultilingualCtcRecognizer(snapshot_path=tmp_path / "missing")
    with pytest.raises(ModelLoadError, match="snapshot directory is missing"):
        missing.prepare()

    recognizer, _, _ = recognizer_with_fakes(
        monkeypatch, tmp_path, load_error=RuntimeError("bad weights")
    )
    with pytest.raises(ModelLoadError, match="bad weights"):
        recognizer.prepare()


def test_audio_validation_and_inference_error_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recognizer, _, _ = recognizer_with_fakes(monkeypatch, tmp_path)
    with pytest.raises(InvalidAudioFileError, match="does not exist"):
        recognizer.transcribe_file(tmp_path / "missing.wav")
    text = tmp_path / "audio.txt"
    text.write_text("x", encoding="utf-8")
    with pytest.raises(InvalidAudioFileError, match="Only .wav"):
        recognizer.transcribe_file(text)

    audio = write_wav(tmp_path / "speech.wav")
    recognizer._inference_runner = lambda *_args: (_ for _ in ()).throw(RuntimeError("decode"))
    with pytest.raises(AudioTranscriptionError, match="decode"):
        recognizer.transcribe_file(audio)


def test_empty_audio_warns_and_never_divides_by_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = write_wav(tmp_path / "empty.wav", frames=0)
    recognizer, _, calls = recognizer_with_fakes(monkeypatch, tmp_path)
    with pytest.warns(RuntimeWarning, match="empty transcription"):
        assert recognizer.transcribe_file(audio) == ""
    assert calls == []
    assert recognizer.last_metrics is not None
    assert recognizer.last_metrics.audio_duration_seconds == 0
    assert recognizer.last_metrics.rtf is None


def test_too_long_audio_is_rejected_before_model_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = write_wav(tmp_path / "long.wav", frames=26 * 16_000)
    recognizer, auto_model, _ = recognizer_with_fakes(monkeypatch, tmp_path)
    with pytest.raises(AudioTranscriptionError, match="at most 25 seconds"):
        recognizer.transcribe_file(audio)
    assert auto_model.calls == []


def test_pcm_reader_downmixes_stereo_without_corrupting_characters(tmp_path: Path) -> None:
    audio = write_wav(tmp_path / "stereo.wav", frames=8_000, sample_rate=8_000, channels=2)
    loaded = backend._read_pcm_wav(audio)
    assert loaded.sample_rate == 8_000
    assert loaded.duration_seconds == 1.0
    assert loaded.samples.shape == (8_000,)
    assert loaded.samples[0] == pytest.approx((4_000 - 2_000) / 2 / 32768)


def test_official_runner_resamples_to_16k_and_does_not_decode_twice() -> None:
    torch = pytest.importorskip("torch")
    resample_calls: list[tuple[int, int]] = []

    def resample(waveform: Any, source: int, target: int) -> Any:
        resample_calls.append((source, target))
        return torch.zeros((1, 16_000), dtype=torch.float32)

    class Inner:
        def forward(self, waveform: Any, length: Any) -> tuple[Any, Any]:
            assert waveform.shape == (1, 16_000)
            assert int(length.item()) == 16_000
            return torch.zeros((1, 2, 3)), torch.tensor([2])

        def _decode(self, *_args: Any) -> list[tuple[str, None]]:
            # This text already reflects official blank removal/repeat collapse.
            return [("баллон ё қазақ english", None)]

    runtime = backend._Runtime(
        torch=torch,
        torchaudio=SimpleNamespace(functional=SimpleNamespace(resample=resample)),
        transformers=None,
        dynamic_module_utils=None,
    )
    model = SimpleNamespace(model=Inner())
    audio = backend._WaveAudio(np.zeros(8_000, dtype=np.float32), 8_000, 1.0)
    assert backend._run_official_inference(model, audio, runtime, "cpu") == (
        "баллон ё қазақ english"
    )
    assert resample_calls == [(8_000, 16_000)]


def test_provider_is_cpu_only_and_never_silently_falls_back() -> None:
    with pytest.raises(ProviderUnavailableError, match="only 'cpu'"):
        GigaAMMultilingualCtcRecognizer(provider="DirectML")
    with pytest.raises(ProviderUnavailableError, match="only 'cpu'"):
        GigaAMMultilingualCtcRecognizer(provider="cuda")


def test_pipeline_passes_backend_to_an_agnostic_factory() -> None:
    seen: list[dict[str, Any]] = []

    def make(**kwargs: Any) -> Any:
        seen.append(kwargs)
        return SimpleNamespace(
            model_name="fake",
            provider="cpu",
            model_load_count=0,
            last_metrics=None,
            model_load_seconds=0.0,
            prepare=lambda: 0.0,
            transcribe_file=lambda _path: "текст",
        )

    pipeline = OfflineAudioTranslationPipeline(recognizer_factory=make)
    _ = pipeline.recognizer
    assert seen == [
        {
            "backend": GIGAAM_MULTILINGUAL_BACKEND,
            "model_name": None,
            "provider": "cpu",
        }
    ]


def test_default_and_legacy_backend_selection_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DEFAULT_ASR_BACKEND == GIGAAM_MULTILINGUAL_BACKEND
    assert DEFAULT_ASR_MODEL == GIGAAM_MULTILINGUAL_MODEL_ID
    assert DEFAULT_PROVIDER == "cpu"
    assert not LEGACY_GIGAAM_SPEC.required

    created: list[dict[str, Any]] = []
    monkeypatch.setattr(
        factory,
        "GigaAMOnnxRecognizer",
        lambda **kwargs: created.append(kwargs) or SimpleNamespace(),
    )
    factory.create_recognizer(backend=LEGACY_GIGAAM_ONNX_BACKEND, provider="cpu")
    assert created == [
        {
            "model_name": "gigaam-v3-e2e-rnnt",
            "provider": "CPUExecutionProvider",
        }
    ]
    with pytest.raises(ModelLoadError, match="Unknown ASR backend"):
        factory.create_recognizer(backend="unknown")


def test_gui_worker_and_pipeline_do_not_import_concrete_rnnt_backend() -> None:
    root = Path(__file__).parents[1] / "src" / "live_subtitles"
    for relative in (
        Path("pipeline/offline_file.py"),
        Path("gui/process_controller.py"),
        Path("realtime/live_subtitles.py"),
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "GigaAMOnnxRecognizer" not in source
        assert "gigaam_onnx" not in source


def test_repository_source_contains_no_model_weights_or_user_path() -> None:
    project = Path(__file__).parents[1]
    tracked_roots = (project / "src", project / "tests", project / "docs")
    forbidden = {".bin", ".pt", ".pth", ".onnx"}
    assert not [
        path
        for root in tracked_roots
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in forbidden
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (project / "src").rglob("*.py")
    )
    assert "C:\\Users\\seren" not in source
