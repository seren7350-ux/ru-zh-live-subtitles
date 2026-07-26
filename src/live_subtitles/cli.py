"""argparse command-line interface for the ASR spike."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .asr.gigaam_onnx import AsrError, GigaAMOnnxRecognizer
from .audio.recording import AudioDeviceError, RecordingError, list_input_devices, record_wav, select_input_device
from .config import DEFAULT_ASR_MODEL, DEFAULT_PROVIDER
from .diagnostics import collect_diagnostics, format_report


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="live-subtitles",
        description="Short Russian WAV recording and GigaAM ONNX transcription spike.",
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (AsrError, AudioDeviceError, RecordingError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Error: operation cancelled by user.", file=sys.stderr)
        return 130
    except Exception as exc:  # preserve a non-zero result without exposing a traceback to users
        print(f"Unexpected error ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
