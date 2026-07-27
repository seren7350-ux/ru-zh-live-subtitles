"""CLI for local-file experiments and terminal-only live microphone VAD."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from .asr.gigaam_onnx import AsrError, GigaAMOnnxRecognizer
from .audio.recording import AudioDeviceError, RecordingError, list_input_devices, record_wav, select_input_device
from .config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRANSLATION_DEVICE,
    DEFAULT_TRANSLATION_ENGINE,
)
from .diagnostics import collect_diagnostics, format_report
from .pipeline.offline_file import (
    OfflineAudioTranslationPipeline,
    OfflinePipelineError,
)
from .realtime.file_vad import VadFileError, run_vad_file
from .realtime.live_vad import LiveVadError, LiveVadSession
from .realtime.microphone import MicrophoneCaptureError
from .realtime.vad_assets import (
    PACKAGE_VERSION,
    VadAssetError,
    prepare_vad_assets,
    validate_vad_assets,
)
from .realtime.vad_model import SAMPLE_RATE, SileroOnnxVad, VadInferenceError
from .translation.benchmark import load_samples, run_benchmark
from .translation.diagnostics import collect_translation_diagnostics
from .translation.factory import TRANSLATION_ENGINES, create_translator
from .translation.t5_ru_zh import TranslationError


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


def _translate_audio(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    print("Using local caches only when HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 are set.")
    pipeline = OfflineAudioTranslationPipeline(
        asr_model=args.asr_model,
        asr_provider=args.asr_provider,
        translation_engine=args.translation_engine,
        translation_model=args.translation_model,
        device=args.device,
        num_beams=args.num_beams,
        max_new_tokens=args.max_new_tokens,
    )
    result = pipeline.run(path)
    end_to_end_rtf = (
        "n/a (zero-duration audio)"
        if result.end_to_end_rtf is None
        else f"{result.end_to_end_rtf:.3f}"
    )
    print(f"File: {result.audio_path}")
    print(f"Audio duration: {result.audio_duration_seconds:.3f} s")
    print(f"Russian text: {result.russian_text}")
    print(f"Chinese text: {result.chinese_text}")
    print(f"ASR model: {result.asr_model}")
    print(f"ASR provider: {result.asr_provider}")
    print(f"ASR model load time: {result.asr_model_load_seconds:.3f} s")
    print(f"ASR recognition time: {result.asr_seconds:.3f} s")
    print(f"Translation engine: {result.translation_engine}")
    print(f"Translation model: {result.translation_model}")
    print(f"Translation model load time: {result.translation_model_load_seconds:.3f} s")
    print(f"Translation time: {result.translation_seconds:.3f} s")
    print(f"Total processing time: {result.total_processing_seconds:.3f} s")
    print(f"End-to-end RTF: {end_to_end_rtf}")
    print(
        "Actual devices: "
        f"ASR={result.asr_device}; translation={result.translation_device}; "
        f"dtype={result.translation_dtype}"
    )
    print(f"CUDA peak memory: {result.peak_cuda_memory_bytes / (1024 ** 2):.1f} MiB")
    return 0


def _vad_prepare(_: argparse.Namespace) -> int:
    info, downloaded = prepare_vad_assets()
    print(f"Status: {'downloaded and prepared' if downloaded else 'cached and verified'}")
    print(f"Package: {info.package_name} {info.package_version}")
    print(f"Source: {info.source}")
    print(f"Cache: {info.cache_dir}")
    print(f"Model: {info.model_path}")
    print(f"Model size: {info.model_size_bytes} bytes")
    print(f"Model SHA-256: {info.model_sha256}")
    return 0


def _vad_doctor(_: argparse.Namespace) -> int:
    try:
        ort = importlib.import_module("onnxruntime")
    except Exception as exc:
        raise VadInferenceError(f"ONNX Runtime is unavailable: {exc}") from exc
    providers = list(ort.get_available_providers())
    if "CPUExecutionProvider" not in providers:
        raise VadInferenceError(
            f"CPUExecutionProvider is unavailable. Available providers: {providers or 'none'}."
        )
    info = validate_vad_assets()
    model = SileroOnnxVad(model_path=info.model_path)
    model.prepare()
    print(f"ONNX Runtime: {ort.__version__}")
    print(f"Providers: {providers}")
    print("CPUExecutionProvider: OK")
    print(f"Cache: {info.cache_dir}")
    print(f"Model exists: {info.model_path.is_file()}")
    print(f"Model SHA-256: OK ({info.model_sha256})")
    print(f"Model load time: {model.load_seconds:.6f} s")
    print("Inputs:")
    for value in model.inputs:
        print(f"  {value.name}: shape={list(value.shape)}, type={value.type}")
    print("Outputs:")
    for value in model.outputs:
        print(f"  {value.name}: shape={list(value.shape)}, type={value.type}")
    return 0


def _vad_file(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir) if args.output_dir else None
    result = run_vad_file(
        Path(args.path),
        threshold=args.threshold,
        min_silence_ms=args.min_silence_ms,
        max_segment_seconds=args.max_segment_seconds,
        output_dir=output_dir,
    )
    print(f"File: {result.path}")
    print(
        f"WAV: channels={result.channels}, sample_rate={result.sample_rate}, "
        f"sample_width={result.sample_width_bits}-bit, frames={result.frame_count}"
    )
    print(f"VAD model version: {result.model_version}")
    print(f"VAD model path: {result.model_path}")
    print(f"Model load time: {result.model_load_seconds:.6f} s")
    print(f"Audio duration: {result.duration_seconds:.3f} s")
    print(f"Total chunks: {result.total_chunks}")
    print(f"Detected segments: {len(result.segments)}")
    print(f"Ignored short segments: {result.ignored_short_segments}")
    for index, segment in enumerate(result.segments, start=1):
        print(
            f"Segment {index}: start={segment.start_sample / result.sample_rate:.3f} s, "
            f"end={segment.end_sample / result.sample_rate:.3f} s, "
            f"duration={segment.duration_seconds:.3f} s, "
            f"forced_split={'yes' if segment.forced_split else 'no'}"
        )
    print(f"VAD inference total: {result.inference_seconds:.6f} s")
    print(f"Average per chunk: {result.average_chunk_seconds * 1000:.3f} ms")
    print(f"P95 per chunk: {result.p95_chunk_seconds * 1000:.3f} ms")
    if result.output_paths:
        print(f"Saved segments: {len(result.output_paths)}")
        for path in result.output_paths:
            print(f"  {path}")
    else:
        print("Saved segments: none (default)")
    return 0


def _live_vad(args: argparse.Namespace) -> int:
    def show_segment(index: int, segment: object) -> None:
        start_sample = int(getattr(segment, "start_sample"))
        end_sample = int(getattr(segment, "end_sample"))
        forced = bool(getattr(segment, "forced_split"))
        print(f"[Segment {index}]", flush=True)
        print(f"Start: {start_sample / SAMPLE_RATE:.3f} s", flush=True)
        print(f"End: {end_sample / SAMPLE_RATE:.3f} s", flush=True)
        print(f"Duration: {(end_sample - start_sample) / SAMPLE_RATE:.3f} s", flush=True)
        print(f"Samples: {end_sample - start_sample}", flush=True)
        print(f"Forced split: {'yes' if forced else 'no'}", flush=True)

    def show_probability(sequence: int, probability: float) -> None:
        print(f"Chunk {sequence}: speech_probability={probability:.6f}", flush=True)

    session = LiveVadSession(
        device_index=args.device,
        duration=args.duration,
        queue_size=args.audio_queue_size,
        threshold=args.threshold,
        negative_threshold=args.negative_threshold,
        min_silence_ms=args.min_silence_ms,
        speech_pad_ms=args.speech_pad_ms,
        pre_roll_ms=args.pre_roll_ms,
        min_segment_ms=args.min_segment_ms,
        max_segment_seconds=args.max_segment_seconds,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        show_probabilities=args.show_probabilities,
        on_segment=show_segment,
        on_probability=show_probability,
    )
    device = session.prepare()
    assert session.vad.model_path is not None
    duration = f"{args.duration:g} seconds" if args.duration else "until Ctrl+C"
    print(f"Input device: {device.index} ({device.name})")
    print("Capture format: 16000 Hz, mono, float32, 512 samples/block (32 ms)")
    print(
        f"Queue: bounded, {args.audio_queue_size} blocks "
        f"({args.audio_queue_size * 0.032:.2f} s)"
    )
    print(f"VAD: Silero {session.vad.provider}, model version {PACKAGE_VERSION}")
    print(f"VAD model: {session.vad.model_path}")
    print(f"VAD load time: {session.vad.load_seconds:.6f} s")
    print(f"VAD session creations: {session.vad.session_creation_count}")
    print(
        f"Segmentation: threshold={args.threshold:g}, "
        f"negative_threshold={args.negative_threshold:g}, "
        f"min_silence={args.min_silence_ms} ms, "
        f"speech_pad={args.speech_pad_ms} ms, "
        f"pre_roll={args.pre_roll_ms} ms, "
        f"min_segment={args.min_segment_ms} ms, "
        f"max_segment={args.max_segment_seconds:g} s"
    )
    print(f"Duration: {duration}")
    print(f"Segment saving: {Path(args.output_dir).expanduser().resolve() if args.output_dir else 'disabled'}")
    print("Listening... Press Ctrl+C to stop.", flush=True)
    result = session.run()
    metrics = result.metrics
    print("Live VAD summary")
    print(f"  Stop reason: {result.stop_reason}")
    print(f"  Session duration: {metrics.session_seconds:.3f} s")
    print(f"  Captured blocks: {metrics.captured_blocks}")
    print(f"  Processed blocks: {metrics.processed_blocks}")
    print(f"  Queue enqueued blocks: {metrics.enqueued_blocks}")
    print(f"  Queue dequeued blocks: {metrics.dequeued_blocks}")
    print(f"  Processed audio: {metrics.audio_seconds:.3f} s")
    print(f"  Dropped blocks: {metrics.dropped_blocks}")
    print(f"  Sequence gaps: {metrics.sequence_gaps}")
    print(
        f"  Queue high-water mark: {metrics.queue_high_watermark}/"
        f"{metrics.queue_capacity} blocks"
    )
    print(f"  Queue final depth: {metrics.queue_final_depth}")
    print(f"  PortAudio status events: {metrics.portaudio_status_count}")
    for status in metrics.portaudio_status_texts:
        print(f"    {status}")
    print(f"  Detected segments: {metrics.detected_segments}")
    print(f"  Forced segments: {metrics.forced_segments}")
    print(f"  Ignored short segments: {metrics.ignored_short_segments}")
    print(f"  Saved segments: {metrics.saved_segments}")
    print(f"  Save failures: {metrics.save_failures}")
    print(f"  VAD inference total: {metrics.inference_total_seconds:.6f} s")
    print(f"  VAD average/chunk: {metrics.average_chunk_seconds * 1000:.3f} ms")
    print(f"  VAD median/chunk: {metrics.median_chunk_seconds * 1000:.3f} ms")
    print(f"  VAD P95/chunk: {metrics.p95_chunk_seconds * 1000:.3f} ms")
    print(f"  VAD maximum/chunk: {metrics.maximum_chunk_seconds * 1000:.3f} ms")
    print(f"  Queue wait average: {metrics.average_queue_wait_seconds * 1000:.3f} ms")
    print(f"  Queue wait median: {metrics.median_queue_wait_seconds * 1000:.3f} ms")
    print(f"  Queue wait P95: {metrics.p95_queue_wait_seconds * 1000:.3f} ms")
    print(f"  Queue wait maximum: {metrics.maximum_queue_wait_seconds * 1000:.3f} ms")
    print(f"  VAD model load: {metrics.model_load_seconds:.6f} s")
    print(f"  ONNX session creations: {metrics.session_creation_count}")
    print(f"  VAD worker exited: {'yes' if metrics.worker_exited else 'no'}")
    print(f"  Microphone released: {'yes' if metrics.microphone_closed else 'no'}")
    if result.output_directory is not None:
        print(f"  Output session directory: {result.output_directory}")
        for path in result.output_paths:
            print(f"    {path}")
    else:
        print("  Output session directory: none")
    if result.errors:
        for error in result.errors:
            print(f"Error: {error}", file=sys.stderr)
        return 2
    return 0


def _translate_text(args: argparse.Namespace) -> int:
    print("First load may download the translation model; later runs use the local cache.")
    translator = create_translator(
        args.engine,
        args.model,
        args.device,
        args.num_beams,
        args.max_new_tokens,
    )
    translation = translator.translate(args.text)
    metrics = translator.last_metrics
    if metrics is None:
        raise TranslationError("Translation completed without timing metrics.")
    print(f"Russian input: {args.text.strip()}")
    print(f"Chinese output: {translation}")
    print(f"Engine: {translator.engine}")
    print(f"Model: {translator.model_name}")
    print(f"Source language: {translator.source_language}")
    print(f"Target language: {translator.target_language}")
    print(f"Revision: {translator.revision}")
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
    translator = create_translator(
        args.engine,
        args.model,
        args.device,
        args.num_beams,
        args.max_new_tokens,
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
        print(f"  Category: {result.category}")
        print(f"  Required terms: {result.required_term_hits}/{result.required_term_total}")
        if result.missing_required_terms:
            missing = "; ".join(" / ".join(group) for group in result.missing_required_terms)
            print(f"  Missing required terms: {missing}")
        print(f"  First translation: {result.first_translation_seconds:.3f} s")
        print(f"  Subsequent translations: {repeats} s")
        print(f"  Average: {result.average_seconds:.3f} s")
        print(f"  Minimum: {result.minimum_seconds:.3f} s")
        print(f"  Maximum: {result.maximum_seconds:.3f} s")
    print("Benchmark summary")
    print(f"  Engine: {summary.engine}")
    print(f"  Model: {summary.model_name}")
    print(f"  Source language: {summary.source_language}")
    print(f"  Target language: {summary.target_language}")
    print(f"  Revision: {summary.revision}")
    print(f"  Device: {summary.device}")
    print(f"  dtype: {summary.dtype}")
    print(f"  Tokenizer load: {summary.tokenizer_load_seconds:.3f} s")
    print(f"  Model load: {summary.model_load_seconds:.3f} s")
    print(f"  Cold load total: {summary.cold_load_seconds:.3f} s")
    print(f"  Average warm translation: {summary.average_warm_seconds:.3f} s")
    print(f"  Median warm translation: {summary.median_warm_seconds:.3f} s")
    print(f"  P95 warm translation: {summary.p95_warm_seconds:.3f} s")
    print(f"  Source characters per second: {summary.source_characters_per_second:.2f}")
    print(f"  Corpus chrF: {summary.corpus_chrf:.3f}")
    print(f"  Mathematics chrF: {summary.mathematics_chrf:.3f}")
    print(
        f"  Terminology accuracy: {summary.required_term_hits}/{summary.required_term_total} "
        f"({summary.terminology_accuracy:.1%})"
    )
    print(
        "  Mathematics terminology accuracy: "
        f"{summary.mathematics_required_term_hits}/{summary.mathematics_required_term_total} "
        f"({summary.mathematics_terminology_accuracy:.1%})"
    )
    print("  Category results:")
    for category in summary.categories:
        print(
            f"    {category.category}: chrF={category.corpus_chrf:.3f}, "
            f"terms={category.required_term_hits}/{category.required_term_total} "
            f"({category.terminology_accuracy:.1%})"
        )
    errors = ", ".join(str(index) for index in summary.severe_terminology_errors) or "none"
    print(f"  Sentences with terminology errors: {errors}")
    print(f"  CUDA peak memory: {summary.peak_cuda_memory_bytes / (1024 ** 2):.1f} MiB")
    print("  Note: corpus chrF is an automatic reference metric, not a substitute for human quality review.")
    if args.json_output:
        output_path = Path(args.json_output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  JSON result: {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live-subtitles",
        description="Local-file experiments and terminal-only live microphone VAD.",
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

    vad_prepare = subparsers.add_parser(
        "vad-prepare",
        help="download and SHA-verify the official Silero VAD 6.2.1 ONNX asset",
    )
    vad_prepare.set_defaults(handler=_vad_prepare)

    vad_doctor = subparsers.add_parser(
        "vad-doctor",
        help="inspect the cached direct ONNX VAD without network access",
    )
    vad_doctor.set_defaults(handler=_vad_doctor)

    vad_file = subparsers.add_parser(
        "vad-file",
        help="segment one mono PCM16 16 kHz WAV with cached Silero ONNX VAD",
    )
    vad_file.add_argument("path", help="path to a strict mono PCM16 16 kHz WAV")
    vad_file.add_argument("--threshold", type=float, default=0.5)
    vad_file.add_argument("--min-silence-ms", type=int, default=600)
    vad_file.add_argument("--max-segment-seconds", type=float, default=15.0)
    vad_file.add_argument(
        "--output-dir",
        help="optional segment directory (recommended: data/vad-segments); default writes nothing",
    )
    vad_file.set_defaults(handler=_vad_file)

    live_vad = subparsers.add_parser(
        "live-vad",
        help="capture native 16 kHz microphone blocks and segment speech with cached Silero ONNX VAD",
    )
    live_vad.add_argument("--device", type=int, help="input device number; default uses the configured input")
    live_vad.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="seconds to run (0 means until Ctrl+C; maximum 3600)",
    )
    live_vad.add_argument(
        "--audio-queue-size",
        "--queue-size",
        dest="audio_queue_size",
        type=int,
        default=320,
        help="bounded audio queue blocks, 16..2000 (default: 320 = 10.24 seconds)",
    )
    live_vad.add_argument("--threshold", type=float, default=0.5)
    live_vad.add_argument("--negative-threshold", type=float, default=0.35)
    live_vad.add_argument("--min-silence-ms", type=int, default=600)
    live_vad.add_argument("--speech-pad-ms", type=int, default=100)
    live_vad.add_argument("--pre-roll-ms", type=int, default=250)
    live_vad.add_argument("--min-segment-ms", type=int, default=300)
    live_vad.add_argument("--max-segment-seconds", type=float, default=15.0)
    live_vad.add_argument(
        "--output-dir",
        help="optional root for a unique session directory of PCM16 segments; default saves nothing",
    )
    live_vad.add_argument(
        "--show-probabilities",
        action="store_true",
        help="print each VAD probability from the worker thread (diagnostic only)",
    )
    live_vad.set_defaults(handler=_live_vad)

    translate_audio = subparsers.add_parser(
        "translate-audio",
        help="recognize one Russian WAV file and translate the result to Chinese",
    )
    translate_audio.add_argument("path", help="path to a WAV file")
    translate_audio.add_argument(
        "--asr-model",
        default=DEFAULT_ASR_MODEL,
        help=f"onnx-asr model name (default: {DEFAULT_ASR_MODEL})",
    )
    translate_audio.add_argument(
        "--asr-provider",
        default=DEFAULT_PROVIDER,
        help=f"ONNX Runtime provider (default: {DEFAULT_PROVIDER})",
    )
    translate_audio.add_argument(
        "--translation-engine",
        choices=TRANSLATION_ENGINES,
        default=DEFAULT_TRANSLATION_ENGINE,
    )
    translate_audio.add_argument(
        "--translation-model",
        help="model repository override (default: official model for the selected engine)",
    )
    translate_audio.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default=DEFAULT_TRANSLATION_DEVICE,
        help="translation device; auto prefers CUDA and falls back to CPU",
    )
    translate_audio.add_argument("--num-beams", type=int, default=1)
    translate_audio.add_argument("--max-new-tokens", type=int, default=256)
    translate_audio.set_defaults(handler=_translate_audio)

    translation_doctor = subparsers.add_parser(
        "translation-doctor",
        help="check translation dependencies, CUDA, and cache without loading a model",
    )
    translation_doctor.set_defaults(handler=_translation_doctor)

    translate = subparsers.add_parser("translate-text", help="translate one Russian text to Chinese")
    translate.add_argument("text", help="Russian source text")
    translate.add_argument("--engine", choices=TRANSLATION_ENGINES, default=DEFAULT_TRANSLATION_ENGINE)
    translate.add_argument("--model", help="model repository override (default: official model for the engine)")
    translate.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default=DEFAULT_TRANSLATION_DEVICE
    )
    translate.add_argument("--num-beams", type=int, default=1)
    translate.add_argument("--max-new-tokens", type=int, default=256)
    translate.set_defaults(handler=_translate_text)

    benchmark = subparsers.add_parser("benchmark-translation", help="benchmark translation using a UTF-8 JSON corpus")
    benchmark.add_argument("path", help="benchmark JSON path")
    benchmark.add_argument("--engine", choices=TRANSLATION_ENGINES, default=DEFAULT_TRANSLATION_ENGINE)
    benchmark.add_argument("--model", help="model repository override (default: official model for the engine)")
    benchmark.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default=DEFAULT_TRANSLATION_DEVICE
    )
    benchmark.add_argument("--num-beams", type=int, default=1)
    benchmark.add_argument("--max-new-tokens", type=int, default=256)
    benchmark.add_argument("--warmup-runs", type=int, default=1)
    benchmark.add_argument("--repeat", type=int, default=3)
    benchmark.add_argument("--json-output", help="optional JSON result path")
    benchmark.set_defaults(handler=_benchmark_translation)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        AsrError,
        AudioDeviceError,
        RecordingError,
        TranslationError,
        OfflinePipelineError,
        VadAssetError,
        VadInferenceError,
        VadFileError,
        LiveVadError,
        MicrophoneCaptureError,
        ValueError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Error: operation cancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:  # preserve a non-zero result without exposing a traceback to users
        print(f"Unexpected error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
