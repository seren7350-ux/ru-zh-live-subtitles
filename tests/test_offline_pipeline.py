from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from live_subtitles.asr.gigaam_onnx import AsrError, RecognitionMetrics
from live_subtitles.config import (
    DEFAULT_NLLB_MODEL,
    DEFAULT_TRANSLATION_ENGINE,
    DEFAULT_TRANSLATION_MODEL,
)
from live_subtitles.pipeline.offline_file import (
    OfflineAudioTranslationPipeline,
    PipelineAsrError,
    PipelineTranslationError,
)
from live_subtitles.translation.t5_ru_zh import TranslationError, TranslationMetrics


class FakeRecognizer:
    model_name = "fake-asr"
    provider = "CPUExecutionProvider"

    def __init__(
        self,
        text: str = "Исходный русский текст",
        *,
        duration: float = 2.0,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error
        self.calls: list[Path] = []
        self.last_metrics = RecognitionMetrics(duration, 1.0, 0.5, 0.25)
        self.prepare_calls = 0

    def prepare(self) -> float:
        self.prepare_calls += 1
        return 1.0

    def transcribe_file(self, path: Path) -> str:
        self.calls.append(path)
        if self.error is not None:
            raise self.error
        return self.text


class FakeTranslator:
    engine = "nllb"
    model_name = "fake-nllb"

    def __init__(self, output: str = "中文结果", *, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[str] = []
        self.last_metrics = TranslationMetrics(
            tokenizer_load_seconds=0.25,
            model_load_seconds=1.75,
            total_load_seconds=2.0,
            translation_seconds=0.2,
            input_characters=12,
            output_characters=4,
            device="cuda",
            dtype="float16",
            peak_cuda_memory_bytes=123_456,
            first_call=True,
        )
        self.prepare_calls = 0

    def prepare(self) -> float:
        self.prepare_calls += 1
        return 2.0

    def translate(self, text: str) -> str:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.output


def make_pipeline(
    recognizer: FakeRecognizer,
    translator: FakeTranslator,
    *,
    times: list[float] | None = None,
) -> tuple[OfflineAudioTranslationPipeline, list[dict[str, Any]], list[tuple[Any, ...]]]:
    recognizer_creations: list[dict[str, Any]] = []
    translator_creations: list[tuple[Any, ...]] = []

    def recognizer_factory(**kwargs: Any) -> FakeRecognizer:
        recognizer_creations.append(kwargs)
        return recognizer

    def translator_factory(*args: Any) -> FakeTranslator:
        translator_creations.append(args)
        return translator

    clock_values = iter(times or [10.0, 14.0])
    pipeline = OfflineAudioTranslationPipeline(
        recognizer_factory=recognizer_factory,
        translator_factory=translator_factory,
        clock=lambda: next(clock_values),
    )
    return pipeline, recognizer_creations, translator_creations


def test_default_translation_candidate_is_nllb() -> None:
    assert DEFAULT_TRANSLATION_ENGINE == "nllb"
    assert DEFAULT_TRANSLATION_MODEL == DEFAULT_NLLB_MODEL
    assert DEFAULT_TRANSLATION_MODEL == "facebook/nllb-200-distilled-600M"


def test_pipeline_construction_is_lazy() -> None:
    pipeline, recognizer_creations, translator_creations = make_pipeline(
        FakeRecognizer(), FakeTranslator()
    )
    assert pipeline.translation_engine == "nllb"
    assert recognizer_creations == []
    assert translator_creations == []


def test_pipeline_passes_asr_text_unchanged_and_combines_metrics(tmp_path: Path) -> None:
    recognizer = FakeRecognizer(text="  Точный русский текст  ")
    translator = FakeTranslator()
    pipeline, recognizer_creations, translator_creations = make_pipeline(recognizer, translator)

    result = pipeline.run(tmp_path / "sample.wav")

    assert translator.calls == ["Точный русский текст"]
    assert len(recognizer_creations) == 1
    assert len(translator_creations) == 1
    assert result.russian_text == "Точный русский текст"
    assert result.chinese_text == "中文结果"
    assert result.audio_duration_seconds == 2.0
    assert result.asr_model_load_seconds == 1.0
    assert result.asr_seconds == 0.5
    assert result.translation_model_load_seconds == 2.0
    assert result.translation_seconds == 0.2
    assert result.total_processing_seconds == 4.0
    assert result.end_to_end_rtf == 2.0
    assert result.translation_device == "cuda"
    assert result.peak_cuda_memory_bytes == 123_456


def test_pipeline_reuses_both_model_wrappers(tmp_path: Path) -> None:
    pipeline, recognizer_creations, translator_creations = make_pipeline(
        FakeRecognizer(),
        FakeTranslator(),
        times=[1.0, 2.0, 3.0, 4.0],
    )
    pipeline.run(tmp_path / "first.wav")
    pipeline.run(tmp_path / "second.wav")
    assert len(recognizer_creations) == 1
    assert len(translator_creations) == 1


def test_pipeline_prepare_is_separate_idempotent_and_reuses_wrappers() -> None:
    recognizer = FakeRecognizer()
    translator = FakeTranslator()
    pipeline, recognizer_creations, translator_creations = make_pipeline(
        recognizer,
        translator,
        times=[1.0, 1.4, 2.0],
    )

    first = pipeline.prepare()
    second = pipeline.prepare()

    assert first is second
    assert first.asr_prepare_seconds == pytest.approx(0.4)
    assert first.translation_prepare_seconds == pytest.approx(0.6)
    assert first.total_prepare_seconds == pytest.approx(1.0)
    assert recognizer.prepare_calls == 1
    assert translator.prepare_calls == 1
    assert pipeline.recognizer_creation_count == 1
    assert pipeline.translator_creation_count == 1
    assert len(recognizer_creations) == 1
    assert len(translator_creations) == 1


def test_empty_asr_output_prevents_translation(tmp_path: Path) -> None:
    pipeline, _, translator_creations = make_pipeline(FakeRecognizer("  "), FakeTranslator())
    with pytest.raises(PipelineAsrError, match="empty Russian text"):
        pipeline.run(tmp_path / "sample.wav")
    assert translator_creations == []


def test_asr_failure_identifies_stage(tmp_path: Path) -> None:
    pipeline, _, translator_creations = make_pipeline(
        FakeRecognizer(error=AsrError("decoder failed")), FakeTranslator()
    )
    with pytest.raises(PipelineAsrError, match="ASR stage failed: decoder failed"):
        pipeline.run(tmp_path / "sample.wav")
    assert translator_creations == []


def test_translation_failure_identifies_stage(tmp_path: Path) -> None:
    pipeline, _, _ = make_pipeline(
        FakeRecognizer(), FakeTranslator(error=TranslationError("generation failed"))
    )
    with pytest.raises(PipelineTranslationError, match="Translation stage failed: generation failed"):
        pipeline.run(tmp_path / "sample.wav")


def test_zero_duration_has_no_end_to_end_rtf(tmp_path: Path) -> None:
    pipeline, _, _ = make_pipeline(FakeRecognizer(duration=0.0), FakeTranslator())
    assert pipeline.run(tmp_path / "empty.wav").end_to_end_rtf is None


def test_pipeline_source_has_no_user_absolute_path() -> None:
    source = (Path(__file__).parents[1] / "src" / "live_subtitles" / "pipeline" / "offline_file.py")
    assert "C:\\Users\\seren" not in source.read_text(encoding="utf-8")
