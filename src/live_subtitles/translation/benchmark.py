"""Reusable translation benchmark loading, terminology, and statistics."""

from __future__ import annotations

import json
import math
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .t5_ru_zh import TranslationError

MATHEMATICS_CATEGORIES = frozenset({"mathematics", "functional_analysis"})


class BenchmarkError(TranslationError):
    """Raised when benchmark data or settings are invalid."""


@dataclass(frozen=True)
class TranslationSample:
    source: str
    reference: str
    category: str = "uncategorized"
    required_terms: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class SampleBenchmark:
    source: str
    reference: str
    category: str
    required_terms: tuple[tuple[str, ...], ...]
    translation: str
    first_translation_seconds: float
    subsequent_translation_seconds: tuple[float, ...]
    required_term_hits: int
    required_term_total: int
    missing_required_terms: tuple[tuple[str, ...], ...]

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
class CategoryBenchmark:
    category: str
    sample_count: int
    corpus_chrf: float
    required_term_hits: int
    required_term_total: int
    terminology_accuracy: float


@dataclass(frozen=True)
class BenchmarkSummary:
    samples: tuple[SampleBenchmark, ...]
    engine: str
    model_name: str
    source_language: str
    target_language: str
    revision: str
    tokenizer_load_seconds: float
    model_load_seconds: float
    cold_load_seconds: float
    average_warm_seconds: float
    median_warm_seconds: float
    p95_warm_seconds: float
    source_characters_per_second: float
    corpus_chrf: float
    mathematics_chrf: float
    required_term_hits: int
    required_term_total: int
    terminology_accuracy: float
    mathematics_required_term_hits: int
    mathematics_required_term_total: int
    mathematics_terminology_accuracy: float
    categories: tuple[CategoryBenchmark, ...]
    severe_terminology_errors: tuple[int, ...]
    peak_cuda_memory_bytes: int
    device: str
    dtype: str


def _parse_required_terms(value: object, index: int) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BenchmarkError(f"Benchmark item {index} required_terms must be a list.")
    groups: list[tuple[str, ...]] = []
    for group_index, group in enumerate(value, start=1):
        if not isinstance(group, list) or not group:
            raise BenchmarkError(
                f"Benchmark item {index} required_terms group {group_index} must be a non-empty list."
            )
        phrases: list[str] = []
        for phrase in group:
            if not isinstance(phrase, str) or not phrase.strip():
                raise BenchmarkError(
                    f"Benchmark item {index} required_terms group {group_index} contains invalid text."
                )
            phrases.append(phrase.strip())
        groups.append(tuple(phrases))
    return tuple(groups)


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
        category = item.get("category")
        if not isinstance(source, str) or not source.strip():
            raise BenchmarkError(f"Benchmark item {index} has no valid source text.")
        if not isinstance(reference, str) or not reference.strip():
            raise BenchmarkError(f"Benchmark item {index} has no valid reference text.")
        if not isinstance(category, str) or not category.strip():
            raise BenchmarkError(f"Benchmark item {index} has no valid category.")
        samples.append(
            TranslationSample(
                source.strip(),
                reference.strip(),
                category.strip(),
                _parse_required_terms(item.get("required_terms"), index),
            )
        )
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


def _normalize_term_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def terminology_hits(
    translation: str,
    required_terms: Sequence[Sequence[str]],
) -> tuple[int, int, tuple[tuple[str, ...], ...]]:
    """Count exact allowed phrases after removing whitespace only."""

    normalized_translation = _normalize_term_text(translation)
    missing: list[tuple[str, ...]] = []
    hits = 0
    for group in required_terms:
        normalized_group = tuple(_normalize_term_text(term) for term in group)
        if any(term in normalized_translation for term in normalized_group):
            hits += 1
        else:
            missing.append(tuple(group))
    return hits, len(required_terms), tuple(missing)


def _accuracy(hits: int, total: int) -> float:
    return hits / total if total else 0.0


def _chrf(
    results: Sequence[SampleBenchmark],
    scorer: Callable[[list[str], list[list[str]]], object],
) -> float:
    if not results:
        return 0.0
    score = scorer(
        [result.translation for result in results],
        [[result.reference for result in results]],
    )
    return float(getattr(score, "score", score))


def run_benchmark(
    translator: Any,
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
    tokenizer_load_seconds = 0.0
    model_load_seconds = 0.0
    cold_load_seconds = 0.0
    device = "unknown"
    dtype = "unknown"

    for sample_index, sample in enumerate(samples):
        translation = translator.translate(sample.source)
        metrics = translator.last_metrics
        if metrics is None:
            raise BenchmarkError("Translator did not provide metrics.")
        if sample_index == 0:
            tokenizer_load_seconds = metrics.tokenizer_load_seconds
            model_load_seconds = metrics.model_load_seconds
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
        hits, total, missing = terminology_hits(translation, sample.required_terms)
        results.append(
            SampleBenchmark(
                source=sample.source,
                reference=sample.reference,
                category=sample.category,
                required_terms=sample.required_terms,
                translation=translation,
                first_translation_seconds=first_seconds,
                subsequent_translation_seconds=tuple(measured),
                required_term_hits=hits,
                required_term_total=total,
                missing_required_terms=missing,
            )
        )

    if chrf_scorer is None:
        from sacrebleu import corpus_chrf

        chrf_scorer = corpus_chrf

    required_hits = sum(result.required_term_hits for result in results)
    required_total = sum(result.required_term_total for result in results)
    math_results = [result for result in results if result.category in MATHEMATICS_CATEGORIES]
    math_hits = sum(result.required_term_hits for result in math_results)
    math_total = sum(result.required_term_total for result in math_results)

    categories: list[CategoryBenchmark] = []
    for category in sorted({result.category for result in results}):
        category_results = [result for result in results if result.category == category]
        category_hits = sum(result.required_term_hits for result in category_results)
        category_total = sum(result.required_term_total for result in category_results)
        categories.append(
            CategoryBenchmark(
                category=category,
                sample_count=len(category_results),
                corpus_chrf=_chrf(category_results, chrf_scorer),
                required_term_hits=category_hits,
                required_term_total=category_total,
                terminology_accuracy=_accuracy(category_hits, category_total),
            )
        )

    total_measured_characters = sum(len(sample.source) for sample in samples) * repeat
    total_warm_seconds = sum(warm_latencies)
    return BenchmarkSummary(
        samples=tuple(results),
        engine=str(getattr(translator, "engine", "unknown")),
        model_name=str(getattr(translator, "model_name", "unknown")),
        source_language=str(getattr(translator, "source_language", "unknown")),
        target_language=str(getattr(translator, "target_language", "unknown")),
        revision=str(getattr(translator, "revision", "unknown")),
        tokenizer_load_seconds=tokenizer_load_seconds,
        model_load_seconds=model_load_seconds,
        cold_load_seconds=cold_load_seconds,
        average_warm_seconds=statistics.fmean(warm_latencies),
        median_warm_seconds=statistics.median(warm_latencies),
        p95_warm_seconds=percentile(warm_latencies, 95),
        source_characters_per_second=(total_measured_characters / total_warm_seconds if total_warm_seconds > 0 else 0.0),
        corpus_chrf=_chrf(results, chrf_scorer),
        mathematics_chrf=_chrf(math_results, chrf_scorer),
        required_term_hits=required_hits,
        required_term_total=required_total,
        terminology_accuracy=_accuracy(required_hits, required_total),
        mathematics_required_term_hits=math_hits,
        mathematics_required_term_total=math_total,
        mathematics_terminology_accuracy=_accuracy(math_hits, math_total),
        categories=tuple(categories),
        severe_terminology_errors=tuple(
            index for index, result in enumerate(results, start=1) if result.missing_required_terms
        ),
        peak_cuda_memory_bytes=peak_memory,
        device=device,
        dtype=dtype,
    )
