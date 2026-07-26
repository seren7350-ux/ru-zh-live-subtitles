"""Reusable translation benchmark loading and statistics."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .t5_ru_zh import T5RuZhTranslator, TranslationError


class BenchmarkError(TranslationError):
    """Raised when benchmark data or settings are invalid."""


@dataclass(frozen=True)
class TranslationSample:
    source: str
    reference: str


@dataclass(frozen=True)
class SampleBenchmark:
    source: str
    reference: str
    translation: str
    first_translation_seconds: float
    subsequent_translation_seconds: tuple[float, ...]

    @property
    def average_seconds(self) -> float:
        values = self.subsequent_translation_seconds or (self.first_translation_seconds,)
        return statistics.fmean(values)

    @property
    def minimum_seconds(self) -> float:
        values = self.subsequent_translation_seconds or (self.first_translation_seconds,)
        return min(values)

    @property
    def maximum_seconds(self) -> float:
        values = self.subsequent_translation_seconds or (self.first_translation_seconds,)
        return max(values)


@dataclass(frozen=True)
class BenchmarkSummary:
    samples: tuple[SampleBenchmark, ...]
    cold_load_seconds: float
    average_warm_seconds: float
    median_warm_seconds: float
    p95_warm_seconds: float
    source_characters_per_second: float
    corpus_chrf: float
    peak_cuda_memory_bytes: int
    device: str
    dtype: str


def load_samples(path: Path) -> list[TranslationSample]:
    resolved = path.expanduser().resolve()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"Unable to read benchmark JSON {resolved}: {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise BenchmarkError("Benchmark JSON must be a non-empty list.")
    samples: list[TranslationSample] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BenchmarkError(f"Benchmark item {index} must be an object.")
        source = item.get("source")
        reference = item.get("reference")
        if not isinstance(source, str) or not source.strip():
            raise BenchmarkError(f"Benchmark item {index} has no valid source text.")
        if not isinstance(reference, str) or not reference.strip():
            raise BenchmarkError(f"Benchmark item {index} has no valid reference text.")
        samples.append(TranslationSample(source.strip(), reference.strip()))
    return samples


def percentile(values: Sequence[float], percentile_value: float) -> float:
    if not values:
        raise BenchmarkError("Cannot calculate a percentile from no values.")
    if not 0 <= percentile_value <= 100:
        raise BenchmarkError("Percentile must be between 0 and 100.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_benchmark(
    translator: T5RuZhTranslator,
    samples: Sequence[TranslationSample],
    *,
    warmup_runs: int,
    repeat: int,
    chrf_scorer: Callable[[list[str], list[list[str]]], object] | None = None,
) -> BenchmarkSummary:
    if not samples:
        raise BenchmarkError("At least one benchmark sample is required.")
    if warmup_runs < 0:
        raise BenchmarkError("warmup_runs must be at least 0.")
    if repeat <= 0:
        raise BenchmarkError("repeat must be greater than 0.")

    results: list[SampleBenchmark] = []
    warm_latencies: list[float] = []
    peak_memory = 0
    cold_load_seconds = 0.0
    device = "unknown"
    dtype = "unknown"

    for sample_index, sample in enumerate(samples):
        translation = translator.translate(sample.source)
        metrics = translator.last_metrics
        if metrics is None:
            raise BenchmarkError("Translator did not provide metrics.")
        if sample_index == 0:
            cold_load_seconds = metrics.total_load_seconds
        first_seconds = metrics.translation_seconds
        peak_memory = max(peak_memory, metrics.peak_cuda_memory_bytes)
        device = metrics.device
        dtype = metrics.dtype

        for _ in range(warmup_runs):
            translator.translate(sample.source)

        measured: list[float] = []
        for _ in range(repeat):
            translator.translate(sample.source)
            repeated_metrics = translator.last_metrics
            if repeated_metrics is None:
                raise BenchmarkError("Translator did not provide repeat metrics.")
            measured.append(repeated_metrics.translation_seconds)
            peak_memory = max(peak_memory, repeated_metrics.peak_cuda_memory_bytes)
        warm_latencies.extend(measured)
        results.append(
            SampleBenchmark(
                source=sample.source,
                reference=sample.reference,
                translation=translation,
                first_translation_seconds=first_seconds,
                subsequent_translation_seconds=tuple(measured),
            )
        )

    if chrf_scorer is None:
        from sacrebleu import corpus_chrf

        chrf_scorer = corpus_chrf
    score = chrf_scorer(
        [result.translation for result in results],
        [[result.reference for result in results]],
    )
    chrf_value = float(getattr(score, "score", score))
    total_measured_characters = sum(len(sample.source) for sample in samples) * repeat
    total_warm_seconds = sum(warm_latencies)
    return BenchmarkSummary(
        samples=tuple(results),
        cold_load_seconds=cold_load_seconds,
        average_warm_seconds=statistics.fmean(warm_latencies),
        median_warm_seconds=statistics.median(warm_latencies),
        p95_warm_seconds=percentile(warm_latencies, 95),
        source_characters_per_second=(total_measured_characters / total_warm_seconds if total_warm_seconds > 0 else 0.0),
        corpus_chrf=chrf_value,
        peak_cuda_memory_bytes=peak_memory,
        device=device,
        dtype=dtype,
    )
