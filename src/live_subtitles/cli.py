"""argparse command-line interface for ASR and independent translation spikes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .asr.gigaam_onnx import AsrError, GigaAMOnnxRecognizer
from .audio.recording import AudioDeviceError, RecordingError, list_input_devices, record_wav, select_input_device
from .config import DEFAULT_ASR_MODEL, DEFAULT_PROVIDER, DEFAULT_TRANSLATION_MODEL
from .diagnostics import collect_diagnostics, format_report
from .translation.benchmark import load_samples, run_benchmark
from .translation.diagnostics import collect_translation_diagnostics
from .translation.t5_ru_zh import T5RuZhTranslator, TranslationError


def _doctor(_: argparse.Namespace) -> int:
    report = collect_diagnostics()
    print(format_report(report))
    return report.exit_code


def _devices(_: argparse.Namespace) -> int:
    devices = list_input_devices()
    if not devices:
        raise AudioDeviceError("No audio input devices are available.")
    print("ID  Default  Inputs  Sample rate  Name")
    for device in devices:
        marker = "yes" if device.is_default else "no"
        print(
            f"{device.index:<3} {marker:<8} {device.max_input_channels:<7} "
            f"{device.default_sample_rate:<12.0f} {device.name}"
        )
    return 0


def _record(args: argparse.Namespace) -> int:
    selected = select_input_device(args.device)
    print(
        f"Recording {args.seconds:g} seconds from device {selected.index} "
        f"({selected.name}) at {args.sample_rate} Hz..."
    )
    result = record_wav(
        Path(args.output),
        seconds=args.seconds,
        sample_rate=args.sample_rate,
        device_index=selected.index,
    )
    print(f"Saved WAV: {result.path}")
    print(f"Frames: {result.frames}")
    print(f"File size: {result.size_bytes} bytes")
    return 0


def _transcribe_file(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    print("First load may download the model from the internet; later runs use the local cache.")
    print(f"File: {path}")
    print(f"Model: {args.model}")
    print(f"Provider: {args.provider}")
    recognizer = GigaAMOnnxRecognizer(model_name=args.model, provider=args.provider)
    text = recognizer.transcribe_file(path)
    metrics = recognizer.last_metrics
    if metrics is None:
        raise AsrError("Recognition completed without timing metrics.")
    rtf = "n/a (zero-duration audio)" if metrics.rtf is None else f"{metrics.rtf:.3f}"
    print(f"Audio duration: {metrics.audio_duration_seconds:.3f} s")
    print(f"Model load time: {metrics.model_load_seconds:.3f} s")
    print(f"Recognition time: {metrics.recognition_seconds:.3f} s")
    print(f"RTF: {rtf}")
    print(f"Russian text: {text}")
    return 0


def _translation_doctor(_: argparse.Namespace) -> int:
    report = collect_translation_diagnostics()
    print(format_report(report))
    return report.exit_code


def _translate_text(args: argparse.Namespace) -> int:
    print("First load may download the translation model; later runs use the local cache.")
    translator = T5RuZhTranslator(
        model_name=args.model,
        device=args.device,
        num_beams=args.num_beams,
        max_new_tokens=args.max_new_tokens,
    )
    translation = translator.translate(args.text)
    metrics = translator.last_metrics
    if metrics is None:
        raise TranslationError("Translation completed without timing metrics.")
    print(f"Russian input: {args.text.strip()}")
    print(f"Chinese output: {translation}")
    print(f"Model: {translator.model_name}")
    print(f"Actual device: {metrics.device}")
    print(f"dtype: {metrics.dtype}")
    print(f"Tokenizer load time: {metrics.tokenizer_load_seconds:.3f} s")
    print(f"Model load time: {metrics.model_load_seconds:.3f} s")
    print(f"Total load time: {metrics.total_load_seconds:.3f} s")
    print(f"Translation time: {metrics.translation_seconds:.3f} s")
    print(f"CUDA peak memory: {metrics.peak_cuda_memory_bytes / (1024 ** 2):.1f} MiB")
    return 0


def _benchmark_translation(args: argparse.Namespace) -> int:
    samples = load_samples(Path(args.path))
    translator = T5RuZhTranslator(
        model_name=args.model,
        device=args.device,
        num_beams=args.num_beams,
        max_new_tokens=args.max_new_tokens,
    )
    summary = run_benchmark(
        translator,
        samples,
        warmup_runs=args.warmup_runs,
        repeat=args.repeat,
    )
    for index, result in enumerate(summary.samples, start=1):
        repeats = ", ".join(f"{value:.3f}" for value in result.subsequent_translation_seconds)
        print(f"Sample {index}")
        print(f"  Russian: {result.source}")
        print(f"  Chinese reference: {result.reference}")
        print(f"  Translation: {result.translation}")
        print(f"  First translation: {result.first_translation_seconds:.3f} s")
        print(f"  Subsequent translations: {repeats} s")
        print(f"  Average: {result.average_seconds:.3f} s")
        print(f"  Minimum: {result.minimum_seconds:.3f} s")
        print(f"  Maximum: {result.maximum_seconds:.3f} s")
    print("Benchmark summary")
    print(f"  Device: {summary.device}")
    print(f"  dtype: {summary.dtype}")
    print(f"  Cold load total: {summary.cold_load_seconds:.3f} s")
    print(f"  Average warm translation: {summary.average_warm_seconds:.3f} s")
    print(f"  Median warm translation: {summary.median_warm_seconds:.3f} s")
    print(f"  P95 warm translation: {summary.p95_warm_seconds:.3f} s")
    print(f"  Source characters per second: {summary.source_characters_per_second:.2f}")
    print(f"  Corpus chrF: {summary.corpus_chrf:.3f}")
    print(f"  CUDA peak memory: {summary.peak_cuda_memory_bytes / (1024 ** 2):.1f} MiB")
    print("  Note: corpus chrF is an automatic reference metric, not a substitute for human quality review.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live-subtitles",
        description="Short Russian WAV ASR and independent offline Russian-to-Chinese translation spikes.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="report local runtime readiness without loading a model")
    doctor.set_defaults(handler=_doctor)

    devices = subparsers.add_parser("devices", help="list audio input devices")
    devices.set_defaults(handler=_devices)

    record = subparsers.add_parser("record", help="record a short mono PCM16 WAV file")
    record.add_argument("--seconds", type=float, default=8.0, help="recording duration, greater than 0 and at most 30")
    record.add_argument("--output", default="data/sample.wav", help="output WAV path (default: data/sample.wav)")
    record.add_argument("--device", type=int, help="input device number from the devices command")
    record.add_argument("--sample-rate", type=int, default=16_000, help="sample rate in Hz (default: 16000)")
    record.set_defaults(handler=_record)

    transcribe = subparsers.add_parser("transcribe-file", help="recognize Russian speech from one local WAV file")
    transcribe.add_argument("path", help="path to a WAV file")
    transcribe.add_argument("--model", default=DEFAULT_ASR_MODEL, help=f"onnx-asr model name (default: {DEFAULT_ASR_MODEL})")
    transcribe.add_argument("--provider", default=DEFAULT_PROVIDER, help=f"ONNX Runtime provider (supported baseline: {DEFAULT_PROVIDER})")
    transcribe.set_defaults(handler=_transcribe_file)

    translation_doctor = subparsers.add_parser(
        "translation-doctor",
        help="check translation dependencies, CUDA, and cache without loading a model",
    )
    translation_doctor.set_defaults(handler=_translation_doctor)

    translate = subparsers.add_parser("translate-text", help="translate one Russian text to Chinese")
    translate.add_argument("text", help="Russian source text")
    translate.add_argument("--model", default=DEFAULT_TRANSLATION_MODEL, help=f"translation model (default: {DEFAULT_TRANSLATION_MODEL})")
    translate.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    translate.add_argument("--num-beams", type=int, default=1)
    translate.add_argument("--max-new-tokens", type=int, default=256)
    translate.set_defaults(handler=_translate_text)

    benchmark = subparsers.add_parser("benchmark-translation", help="benchmark translation using a UTF-8 JSON corpus")
    benchmark.add_argument("path", help="benchmark JSON path")
    benchmark.add_argument("--model", default=DEFAULT_TRANSLATION_MODEL, help=f"translation model (default: {DEFAULT_TRANSLATION_MODEL})")
    benchmark.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    benchmark.add_argument("--num-beams", type=int, default=1)
    benchmark.add_argument("--max-new-tokens", type=int, default=256)
    benchmark.add_argument("--warmup-runs", type=int, default=1)
    benchmark.add_argument("--repeat", type=int, default=3)
    benchmark.set_defaults(handler=_benchmark_translation)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AsrError, AudioDeviceError, RecordingError, TranslationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Error: operation cancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:  # preserve a non-zero result without exposing a traceback to users
        print(f"Unexpected error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
