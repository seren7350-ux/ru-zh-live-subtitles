from pathlib import Path
import os
import subprocess
import sys

import pytest

from live_subtitles.subtitles import SrtSession


def test_incremental_utf8_bilingual_cues_keep_audio_gaps_and_overlap(tmp_path: Path) -> None:
    session = SrtSession.create(tmp_path / "subtitles")
    assert session.path.is_absolute()
    assert session.append(7, 5.25, 6.75, "Привет\n\nмир", "你好\r\n世界")
    first = session.path.read_bytes()
    assert first.decode("utf-8") == (
        "1\n00:00:05,250 --> 00:00:06,750\nПривет мир\n你好 世界\n\n"
    )
    assert not session.append(7, 0.0, 1.0, "duplicate", "重复")
    assert session.path.read_bytes() == first
    assert session.append(9, 6.5, 7.125, "Второй", "第二句")
    contents = session.path.read_text(encoding="utf-8")
    assert contents.startswith(first.decode("utf-8"))
    assert "2\n00:00:06,500 --> 00:00:07,125\nВторой\n第二句\n\n" in contents


def test_timestamp_rounding_crosses_seconds_minutes_and_hours(tmp_path: Path) -> None:
    session = SrtSession.create(tmp_path)
    session.append(1, 59.9995, 3_599.9995, "Текст", "字幕")
    assert "00:01:00,000 --> 01:00:00,000" in session.path.read_text(encoding="utf-8")


def test_new_session_is_independent_and_never_replaces_previous_file(tmp_path: Path) -> None:
    first = SrtSession.create(tmp_path)
    first.append(1, 0, 1, "Привет", "你好")
    original = first.path.read_bytes()
    second = SrtSession.create(tmp_path)
    assert first.path != second.path
    assert first.path.read_bytes() == original
    second.append(1, 10, 11, "Снова", "再次")
    assert second.path.read_text(encoding="utf-8").startswith("1\n00:00:10,000")


@pytest.mark.parametrize(
    ("start", "end"),
    [(None, 1), (0, None), (-1, 1), (0, float("nan")),
     (float("inf"), 1), (2, 1), (1, 1), (1, 1.0001)],
)
def test_invalid_or_missing_audio_time_does_not_write_a_cue(tmp_path: Path, start, end) -> None:
    session = SrtSession.create(tmp_path)
    with pytest.raises(ValueError, match="SRT"):
        session.append(1, start, end, "Текст", "字幕")
    assert session.path.read_bytes() == b""
    assert session.append(1, 2, 3, "Текст", "字幕")
    assert session.path.read_text(encoding="utf-8").startswith("1\n")


def test_empty_language_does_not_insert_cue_terminator(tmp_path: Path) -> None:
    session = SrtSession.create(tmp_path)
    with pytest.raises(ValueError, match="text"):
        session.append(1, 0, 1, " \n", "\t")
    session.append(1, 0, 1, "Текст", "")
    assert session.path.read_text(encoding="utf-8").endswith("\nТекст\n\n")


def test_partial_write_rolls_back_only_incomplete_cue_and_latches_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = SrtSession.create(tmp_path)
    session.append(1, 0, 1, "Первый", "第一句")
    complete = session.path.read_bytes()
    real_open = Path.open

    class FailingWrite:
        def __init__(self, stream):
            self.stream = stream
            self.writes = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def write(self, data):
            self.writes += 1
            if self.writes == 1:
                return self.stream.write(data[:12])
            raise OSError("synthetic disk failure")

    def patched_open(path, mode="r", *args, **kwargs):
        stream = real_open(path, mode, *args, **kwargs)
        return FailingWrite(stream) if path == session.path and mode == "r+b" else stream

    monkeypatch.setattr(Path, "open", patched_open)
    with pytest.raises(OSError, match="synthetic disk failure"):
        session.append(2, 2, 3, "Второй", "第二句")
    assert session.path.read_bytes() == complete
    with pytest.raises(OSError, match="previous write failure"):
        session.append(3, 4, 5, "Третий", "第三句")


def test_external_file_edit_is_preserved_and_reported(tmp_path: Path) -> None:
    session = SrtSession.create(tmp_path)
    session.append(1, 0, 1, "Первый", "第一句")
    with session.path.open("ab") as stream:
        stream.write(b"external edit\n")
    externally_edited = session.path.read_bytes()
    with pytest.raises(OSError, match="outside"):
        session.append(2, 2, 3, "Второй", "第二句")
    assert session.path.read_bytes() == externally_edited


def test_completed_cue_survives_abrupt_application_exit(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    code = (
        "import os, sys; from pathlib import Path; "
        "from live_subtitles.subtitles import SrtSession; "
        "session=SrtSession.create(Path(sys.argv[1])); "
        "session.append(1, 3.5, 4.75, 'Russian', 'Chinese'); os._exit(17)"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(tmp_path)],
        env=environment, capture_output=True, timeout=10,
    )
    assert result.returncode == 17, result.stderr
    [output] = list(tmp_path.glob("*.srt"))
    assert output.read_text(encoding="utf-8") == (
        "1\n00:00:03,500 --> 00:00:04,750\nRussian\nChinese\n\n"
    )
