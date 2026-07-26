from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.translation.benchmark import (
    BenchmarkError,
    TranslationSample,
    load_samples,
    percentile,
    run_benchmark,
)
from live_subtitles.translation.t5_ru_zh import TranslationMetrics


class FakeTranslator:
    def __init__(self) -> None:
        self.latencies = iter([0.9, 0.5, 0.4, 0.6, 0.8, 0.4, 0.3, 0.5])
        self.last_metrics: TranslationMetrics | None = None

    def translate(self, text: str) -> str:
        latency = next(self.latencies)
        self.last_metrics = TranslationMetrics(
            tokenizer_load_seconds=1.0,
            model_load_seconds=2.0,
            total_load_seconds=3.0,
            translation_seconds=latency,
            input_characters=len(text),
            output_characters=2,
            device="cuda",
            dtype="float16",
            peak_cuda_memory_bytes=100,
            first_call=False,
        )
        return f"译{text[-1]}"


def test_benchmark_statistics_are_correct() -> None:
    samples = [
        TranslationSample("abcd", "参考1"),
        TranslationSample("uvwxyz", "参考2"),
    ]
    summary = run_benchmark(
        FakeTranslator(),  # type: ignore[arg-type]
        samples,
        warmup_runs=1,
        repeat=2,
        chrf_scorer=lambda hypotheses, references: SimpleNamespace(score=42.5),
    )
    assert summary.cold_load_seconds == 3.0
    assert summary.average_warm_seconds == pytest.approx(0.45)
    assert summary.median_warm_seconds == pytest.approx(0.45)
    assert summary.p95_warm_seconds == pytest.approx(0.585)
    assert summary.source_characters_per_second == pytest.approx(20 / 1.8)
    assert summary.corpus_chrf == 42.5
    assert summary.device == "cuda"
    assert summary.dtype == "float16"
    assert len(summary.samples) == 2


def test_percentile_interpolates() -> None:
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == pytest.approx(2.5)


def test_load_samples_rejects_corrupt_json(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("not-json", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="Unable to read benchmark JSON"):
        load_samples(broken)


def test_loads_utf8_benchmark_data() -> None:
    path = Path(__file__).parents[1] / "benchmarks" / "translation_samples.json"
    samples = load_samples(path)
    assert len(samples) == 12
    assert samples[0].source.startswith("Здравствуйте")
    assert samples[0].reference.startswith("您好")
