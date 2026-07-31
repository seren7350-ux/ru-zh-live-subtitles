from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from live_subtitles import cli
from live_subtitles.diagnostics import Check, DiagnosticReport


def test_python_module_help_starts() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "live_subtitles", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "doctor" in result.stdout
    assert "transcribe-file" in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "doctor",
        "devices",
        "record",
        "transcribe-file",
        "vad-prepare",
        "vad-doctor",
        "vad-file",
        "live-vad",
        "live-terminal",
        "translate-audio",
        "translation-doctor",
        "model-doctor",
        "translate-text",
        "benchmark-translation",
    ],
)
def test_subcommand_help(command: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main([command, "--help"])
    assert exc_info.value.code == 0


def test_doctor_command_starts(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    report = DiagnosticReport((Check("OK", "test", "ready"),))
    monkeypatch.setattr(cli, "collect_diagnostics", lambda: report)
    assert cli.main(["doctor"]) == 0
    output = capsys.readouterr().out
    assert "[OK] test: ready" in output
    assert "FAIL=0" in output


def test_devices_handles_empty_list(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "list_input_devices", lambda: [])
    assert cli.main(["devices"]) != 0
    assert "No audio input devices" in capsys.readouterr().err


def test_devices_preserves_unicode_names(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from live_subtitles.audio.recording import AudioDevice

    monkeypatch.setattr(
        cli,
        "list_input_devices",
        lambda: [AudioDevice(3, "麦克风 Микрофон ♫", 2, 48_000.0, True)],
    )
    assert cli.main(["devices"]) == 0
    assert "麦克风 Микрофон ♫" in capsys.readouterr().out


def test_missing_wav_returns_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing.wav"
    assert cli.main(["transcribe-file", str(missing)]) != 0
    assert "does not exist" in capsys.readouterr().err


def test_non_wav_returns_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    text_file = tmp_path / "audio.txt"
    text_file.write_text("not audio", encoding="utf-8")
    assert cli.main(["transcribe-file", str(text_file)]) != 0
    assert "Only .wav files" in capsys.readouterr().err


def test_translation_cli_error_has_no_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["translate-text", "   "]) != 0
    captured = capsys.readouterr()
    assert "whitespace-only" in captured.err
    assert "Traceback" not in captured.err


def test_broken_benchmark_json_returns_nonzero(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{broken", encoding="utf-8")
    assert cli.main(["benchmark-translation", str(broken)]) != 0
    captured = capsys.readouterr()
    assert "Unable to read benchmark JSON" in captured.err
    assert "Traceback" not in captured.err


def test_translate_audio_defaults_to_nllb_and_reports_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from live_subtitles.pipeline.offline_file import OfflineTranslationResult

    captured_kwargs: dict[str, object] = {}

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        @staticmethod
        def run(path: Path) -> OfflineTranslationResult:
            return OfflineTranslationResult(
                audio_path=path,
                russian_text="Русский текст",
                chinese_text="中文文本",
                asr_model="gigaam-v3-e2e-rnnt",
                asr_provider="CPUExecutionProvider",
                translation_engine="nllb",
                translation_model="facebook/nllb-200-distilled-600M",
                audio_duration_seconds=2.0,
                asr_model_load_seconds=1.0,
                asr_seconds=0.5,
                translation_model_load_seconds=3.0,
                translation_seconds=0.25,
                total_processing_seconds=4.75,
                end_to_end_rtf=2.375,
                asr_device="CPUExecutionProvider",
                translation_device="cuda",
                translation_dtype="float16",
                peak_cuda_memory_bytes=1024 * 1024,
            )

    monkeypatch.setattr(cli, "OfflineAudioTranslationPipeline", FakePipeline)
    wav = tmp_path / "sample.wav"
    assert cli.main(["translate-audio", str(wav)]) == 0
    assert captured_kwargs["translation_engine"] == "nllb"
    assert captured_kwargs["translation_model"] is None
    assert captured_kwargs["device"] == "cpu"
    output = capsys.readouterr().out
    assert "Russian text: Русский текст" in output
    assert "Chinese text: 中文文本" in output
    assert "End-to-end RTF: 2.375" in output
    assert "translation=cuda" in output


@pytest.mark.parametrize("engine", ["t5", "m2m100"])
def test_translate_audio_accepts_compatibility_engine_override(
    engine: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured_kwargs: dict[str, object] = {}

    class FailingAfterCapturePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured_kwargs.update(kwargs)

        @staticmethod
        def run(path: Path) -> object:
            raise ValueError(f"stopped after parsing {path.name}")

    monkeypatch.setattr(cli, "OfflineAudioTranslationPipeline", FailingAfterCapturePipeline)
    result = cli.main(
        [
            "translate-audio",
            "sample.wav",
            "--translation-engine",
            engine,
            "--translation-model",
            "example/model",
            "--device",
            "cpu",
            "--num-beams",
            "3",
            "--max-new-tokens",
            "80",
        ]
    )
    assert result != 0
    assert captured_kwargs == {
        "asr_backend": "gigaam_multilingual_large_ctc",
        "asr_model": None,
        "asr_provider": "cpu",
        "translation_engine": engine,
        "translation_model": "example/model",
        "device": "cpu",
        "num_beams": 3,
        "max_new_tokens": 80,
    }
    assert "Traceback" not in capsys.readouterr().err
