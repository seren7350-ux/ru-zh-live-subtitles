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
    terminology_hits,
)
from live_subtitles.translation.t5_ru_zh import TranslationMetrics


class FakeTranslator:
    engine = "fake"
    model_name = "fake/model"
    source_language = "ru"
    target_language = "zh"
    revision = "abc123"

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
        TranslationSample("abcd", "参考1", "mathematics", (("译d",),)),
        TranslationSample("uvwxyz", "参考2", "software", (("不存在",),)),
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
    assert summary.required_term_hits == 1
    assert summary.required_term_total == 2
    assert summary.terminology_accuracy == pytest.approx(0.5)
    assert summary.mathematics_terminology_accuracy == pytest.approx(1.0)
    assert summary.severe_terminology_errors == (2,)
    assert {category.category for category in summary.categories} == {"mathematics", "software"}


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
    assert len(samples) >= 30
    assert {sample.category for sample in samples} == {
        "functional_analysis",
        "general_lecture",
        "mathematics",
        "software",
    }
    assert any(("线性算子",) in sample.required_terms for sample in samples)


def test_required_terms_accept_alternatives_and_remove_only_whitespace() -> None:
    hits, total, missing = terminology_hits(
        "这是 巴拿赫 空间中的线性运营商。",
        (("巴拿赫空间",), ("线性算子", "线性算符")),
    )
    assert (hits, total) == (1, 2)
    assert missing == (("线性算子", "线性算符"),)
