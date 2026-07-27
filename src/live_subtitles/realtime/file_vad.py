"""Run direct Silero ONNX VAD over one strict PCM16/16 kHz mono WAV file."""

from __future__ import annotations

import math
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

from ..audio.wav_io import write_pcm16_mono_wav
from .segmenter import AudioSegment, VadSegmenter
from .vad_assets import PACKAGE_VERSION
from .vad_model import CHUNK_SAMPLES, SAMPLE_RATE, SileroOnnxVad


class VadFileError(RuntimeError):
    """Raised when a file cannot be validated or segmented."""


@dataclass(frozen=True)
class VadFileResult:
    path: Path
    channels: int
    sample_rate: int
    sample_width_bits: int
    frame_count: int
    duration_seconds: float
    model_version: str
    model_path: Path
    model_load_seconds: float
    total_chunks: int
    segments: tuple[AudioSegment, ...]
    ignored_short_segments: int
    inference_seconds: float
    average_chunk_seconds: float
    p95_chunk_seconds: float
    output_paths: tuple[Path, ...]


def percentile(values: Sequence[float], value: float) -> float:
    if not values:
        raise VadFileError("Cannot calculate a percentile from no values.")
    if not 0.0 <= value <= 100.0:
        raise VadFileError("Percentile must be between zero and 100.")
    ordered = sorted(values)
    position = (len(ordered) - 1) * value / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _read_pcm16_mono_16k(path: Path) -> tuple[Path, np.ndarray]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise VadFileError(f"WAV file does not exist or is not a regular file: {resolved}")
    if resolved.suffix.lower() != ".wav":
        raise VadFileError(f"Only .wav files are supported: {resolved}")
    try:
        with wave.open(str(resolved), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            compression = wav_file.getcomptype()
            frames = wav_file.getnframes()
            raw = wav_file.readframes(frames)
    except (OSError, EOFError, wave.Error) as exc:
        raise VadFileError(f"Unable to read WAV file {resolved}: {exc}") from exc
    if channels != 1:
        raise VadFileError(f"VAD file input must be mono; found {channels} channels.")
    if sample_width != 2 or compression != "NONE":
        raise VadFileError("VAD file input must be uncompressed PCM16 WAV.")
    if sample_rate != SAMPLE_RATE:
        raise VadFileError(
            f"VAD file input must use {SAMPLE_RATE} Hz; found {sample_rate} Hz."
        )
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size != frames:
        raise VadFileError("WAV frame count does not match the PCM payload.")
    return resolved, samples


def _write_segment(path: Path, samples: np.ndarray) -> None:
    try:
        write_pcm16_mono_wav(path, samples, sample_rate=SAMPLE_RATE)
    except (OSError, ValueError, wave.Error) as exc:
        raise VadFileError(f"Unable to save VAD segment {path}: {exc}") from exc


def run_vad_file(
    path: Path,
    *,
    model: SileroOnnxVad | None = None,
    threshold: float = 0.5,
    min_silence_ms: int = 600,
    max_segment_seconds: float = 15.0,
    output_dir: Path | None = None,
    clock: Callable[[], float] = time.perf_counter,
) -> VadFileResult:
    """Segment one local WAV; model preparation never downloads assets."""

    resolved, samples = _read_pcm16_mono_16k(path)
    vad = model or SileroOnnxVad()
    vad.prepare()
    vad.reset()
    segmenter = VadSegmenter(
        threshold=threshold,
        min_silence_ms=min_silence_ms,
        max_segment_seconds=max_segment_seconds,
    )
    segments: list[AudioSegment] = []
    timings: list[float] = []
    total_chunks = math.ceil(samples.size / CHUNK_SAMPLES) if samples.size else 0
    for offset in range(0, samples.size, CHUNK_SAMPLES):
        valid = min(CHUNK_SAMPLES, samples.size - offset)
        chunk = np.zeros(CHUNK_SAMPLES, dtype=np.float32)
        chunk[:valid] = samples[offset : offset + valid]
        started = clock()
        probability = vad.speech_probability(chunk)
        timings.append(clock() - started)
        segments.extend(
            segmenter.process(
                chunk,
                probability,
                offset / SAMPLE_RATE,
                valid_samples=valid,
            )
        )
    segments.extend(segmenter.flush())

    output_paths: list[Path] = []
    if output_dir is not None:
        resolved_output = output_dir.expanduser().resolve()
        resolved_output.mkdir(parents=True, exist_ok=True)
        for index, segment in enumerate(segments, start=1):
            output_path = resolved_output / f"segment-{index:03d}.wav"
            _write_segment(output_path, segment.samples)
            output_paths.append(output_path)

    inference_seconds = sum(timings)
    average = inference_seconds / len(timings) if timings else 0.0
    p95 = percentile(timings, 95) if timings else 0.0
    if vad.model_path is None:
        raise VadFileError("VAD model prepared without exposing its path.")
    return VadFileResult(
        path=resolved,
        channels=1,
        sample_rate=SAMPLE_RATE,
        sample_width_bits=16,
        frame_count=samples.size,
        duration_seconds=samples.size / SAMPLE_RATE,
        model_version=PACKAGE_VERSION,
        model_path=vad.model_path,
        model_load_seconds=vad.load_seconds,
        total_chunks=total_chunks,
        segments=tuple(segments),
        ignored_short_segments=segmenter.ignored_short_segments,
        inference_seconds=inference_seconds,
        average_chunk_seconds=average,
        p95_chunk_seconds=p95,
        output_paths=tuple(output_paths),
    )
