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
        "translation-doctor",
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
