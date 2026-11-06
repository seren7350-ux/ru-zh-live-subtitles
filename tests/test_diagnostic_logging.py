from __future__ import annotations

import logging
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles import diagnostic_logging, frozen_entry


@pytest.fixture
def isolated_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    logger = logging.getLogger(diagnostic_logging.LOGGER_NAME)
    original_handlers = tuple(logger.handlers)
    original_level, original_propagate = logger.level, logger.propagate
    for handler in original_handlers:
        logger.removeHandler(handler)
    destination = tmp_path / "logs"
    monkeypatch.setattr(diagnostic_logging, "log_directory", lambda: destination)
    try:
        yield destination
    finally:
        for handler in tuple(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def _raise_chained_failure(token: str, caption: str) -> None:
    unrelated_local = "private local value that must never appear"
    try:
        raise OSError(f"Cannot read {Path.home() / 'private-model'}: {token}")
    except OSError as exc:
        raise RuntimeError(f"engine failed on input {caption!r}") from exc


def test_exception_chain_is_persisted_and_fully_redacted(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "private-token-without-recognizable-prefix"
    caption = "Секретная строка\n字幕\\quoted 'text'"
    monkeypatch.setenv("HF_TOKEN", token)
    logger = diagnostic_logging.configure_diagnostic_logging(session_id="session-42")
    try:
        _raise_chained_failure(token, caption)
    except RuntimeError:
        logger.exception("Engine failure", extra={"sensitive_text": (caption,)})
    content = (isolated_logs / diagnostic_logging.LOG_FILENAME).read_text(encoding="utf-8")
    assert "Traceback (most recent call last):\n" in content
    assert "OSError:" in content and "RuntimeError:" in content
    assert "direct cause" in content and "_raise_chained_failure" in content
    assert str(Path.home()) not in content and token not in content
    assert caption not in content and repr(caption)[1:-1] not in content
    assert "<redacted-path>" in content and "<redacted-token>" in content
    assert "<redacted-caption>" in content
    assert "private local value that must never appear" not in content
    assert f"pid={os.getpid()}" in content
    assert "thread=MainThread session=session-42" in content


def test_source_gui_startup_failure_is_logged_before_tk_initializes(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from live_subtitles import cli
    from live_subtitles.gui import app, single_instance

    def fail_controller(_config):
        raise OSError("synthetic controller startup failure")

    monkeypatch.setattr(app, "LiveProcessOverlayController", fail_controller)
    monkeypatch.setattr(
        single_instance, "acquire_instance",
        lambda **_: SimpleNamespace(primary=True, close=lambda: None),
    )
    assert cli.main(["live-overlay", "--no-auto-start"]) == 1
    content = (isolated_logs / "application.log").read_text(encoding="utf-8")
    assert "Traceback" in content
    assert "OSError: synthetic controller startup failure" in content


def test_cached_exception_text_cannot_bypass_redaction(isolated_logs: Path) -> None:
    logger = diagnostic_logging.configure_diagnostic_logging()
    try:
        raise ValueError("Bearer abcdefghijk")
    except ValueError:
        record = logger.makeRecord(
            logger.name, logging.ERROR, __file__, 1, "failure", (), sys.exc_info()
        )
    record.exc_text = "unsafe cached exception text"
    logger.handle(record)
    content = (isolated_logs / diagnostic_logging.LOG_FILENAME).read_text(encoding="utf-8")
    assert "Bearer <redacted-token>" in content
    assert "abcdefghijk" not in content
    assert "unsafe cached exception text" not in content
    assert record.exc_text == "unsafe cached exception text"


def test_escaped_paths_and_tokens_are_redacted(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "private-token'\\quoted"
    monkeypatch.setenv("HF_TOKEN", token)
    logger = diagnostic_logging.configure_diagnostic_logging()
    roots = (str(Path.home()), Path.home().as_posix())
    for root in roots:
        logger.error("path=%r token=%r", root + "/private-model", token)
        logger.error("path=%s token=%s", json.dumps(root), json.dumps(token))
    content = (isolated_logs / "application.log").read_text(encoding="utf-8")
    for root in roots:
        assert root not in content and repr(root)[1:-1] not in content
    assert token not in content and repr(token)[1:-1] not in content
    assert "<redacted-path>" in content and "<redacted-token>" in content


def test_reconfiguration_keeps_one_handler_and_separates_destinations(isolated_logs: Path) -> None:
    logger = diagnostic_logging.configure_diagnostic_logging(session_id="first")
    logger.info("parent record")
    diagnostic_logging.configure_diagnostic_logging(session_id="second")
    logger.info("next session record")
    assert sum(bool(getattr(h, "_ru_zh_handler", False)) for h in logger.handlers) == 1
    diagnostic_logging.configure_diagnostic_logging(filename="worker-123.log", session_id="worker")
    logger.info("worker record")
    assert sum(bool(getattr(h, "_ru_zh_handler", False)) for h in logger.handlers) == 1
    parent_content = (isolated_logs / "application.log").read_text(encoding="utf-8")
    worker_content = (isolated_logs / "worker-123.log").read_text(encoding="utf-8")
    assert "session=first parent record" in parent_content
    assert "session=second next session record" in parent_content
    assert "worker record" not in parent_content
    assert "session=worker worker record" in worker_content


@pytest.mark.parametrize("filename", ["", "..", "../outside.log", r"..\outside.log", "x:stream"])
def test_log_destination_cannot_escape_log_directory(isolated_logs: Path, filename: str) -> None:
    with pytest.raises(ValueError, match="plain filename"):
        diagnostic_logging.configure_diagnostic_logging(filename=filename)
    assert not isolated_logs.exists()


def test_file_logging_rotates_with_existing_retention_limit(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(diagnostic_logging, "MAX_LOG_BYTES", 300)
    logger = diagnostic_logging.configure_diagnostic_logging()
    for index in range(12):
        logger.info("bounded diagnostic record %d %s", index, "x" * 100)
    assert sorted(path.name for path in isolated_logs.iterdir()) == [
        "application.log", "application.log.1", "application.log.2"
    ]
    assert "record 11" in (isolated_logs / "application.log").read_text(encoding="utf-8")


def test_windowed_launcher_records_failure_when_stderr_is_a_sink(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from live_subtitles import cli

    def fail(_arguments):
        raise RuntimeError("synthetic launcher failure")

    monkeypatch.setattr(cli, "main", fail)
    monkeypatch.setenv("RU_ZH_LAUNCH_MODE", "windowed")
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(RuntimeError, match="synthetic launcher failure"):
        frozen_entry.run_frozen([])
    content = (isolated_logs / "application.log").read_text(encoding="utf-8")
    assert "Unhandled launcher failure" in content
    assert "Traceback" in content and "RuntimeError: synthetic launcher failure" in content
    assert "exit_code=unhandled" in content


def test_cli_failure_is_logged_without_printing_a_traceback_to_user(
    isolated_logs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from live_subtitles import cli

    def fail(_arguments):
        raise ValueError("synthetic command failure")

    namespace = SimpleNamespace(command="synthetic", handler=fail)
    monkeypatch.setattr(cli, "build_parser", lambda: SimpleNamespace(parse_args=lambda _: namespace))
    diagnostic_logging.configure_diagnostic_logging()
    assert cli.main([]) == 2
    assert "Traceback" not in capsys.readouterr().err
    content = (isolated_logs / "application.log").read_text(encoding="utf-8")
    assert "command=synthetic" in content
    assert "Traceback" in content and "ValueError: synthetic command failure" in content


def test_unconfigured_logger_does_not_fall_back_to_console(
    isolated_logs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        raise RuntimeError("unconfigured error")
    except RuntimeError:
        diagnostic_logging.diagnostic_logger().exception("infrastructure error")
    assert capsys.readouterr().err == ""
    assert not isolated_logs.exists()


def test_subtitle_worker_logs_stage_stack_without_caption_or_model(
    isolated_logs: Path, tmp_path: Path
) -> None:
    import numpy as np

    from live_subtitles.pipeline.offline_file import PipelineTranslationError
    from live_subtitles.realtime.segment_processor import SegmentProcessor
    from live_subtitles.realtime.segmenter import AudioSegment

    caption = "не сохранять содержимое лекции"

    class FailedTranslatorPipeline:
        def transcribe_file(self, _path):
            return caption, SimpleNamespace(recognition_seconds=0.01)

        def translate_text(self, text):
            try:
                raise RuntimeError(f"synthetic backend failure: {text!r}")
            except RuntimeError as exc:
                raise PipelineTranslationError(f"translation failed: {text!r}") from exc

    diagnostic_logging.configure_diagnostic_logging(filename="worker.log", session_id="test")
    processor = SegmentProcessor(FailedTranslatorPipeline(), temp_directory=tmp_path)
    processor.start()
    processor.enqueue(
        1,
        AudioSegment(np.zeros(512, dtype=np.float32), 0, 512, 0.0, 0.032, False),
    )
    processor.finish()
    assert len(processor.results) == 1
    assert processor.results[0].error_stage == "translation"
    assert caption not in processor.results[0].error
    assert "<redacted-caption>" in processor.results[0].error
    content = (isolated_logs / "worker.log").read_text(encoding="utf-8")
    assert "Translation stage failed; segment=1" in content
    assert "ASR stage started; segment=1" in content
    assert "ASR stage finished; segment=1; elapsed_seconds=" in content
    assert "Translation stage started; segment=1" in content
    assert "thread=live-subtitle-worker" in content
    assert "RuntimeError:" in content and "PipelineTranslationError:" in content
    assert "direct cause" in content and caption not in content
    assert "<redacted-caption>" in content
    assert not tuple(tmp_path.glob("*.wav"))


@pytest.mark.parametrize("failure_stage", ["unexpected_translation", "result_callback"])
def test_fatal_worker_error_redacts_text_before_gui_transport(
    isolated_logs: Path, tmp_path: Path, failure_stage: str
) -> None:
    import numpy as np

    from live_subtitles.realtime.segment_processor import SegmentProcessor
    from live_subtitles.realtime.segmenter import AudioSegment

    russian = "не записывать секретный русский текст"
    chinese = "不要记录这句中文翻译"

    class Pipeline:
        def transcribe_file(self, _path):
            return russian, SimpleNamespace(recognition_seconds=0.01)

        def translate_text(self, text):
            if failure_stage == "unexpected_translation":
                raise RuntimeError(f"unhandled backend failure: {text!r}")
            return chinese, SimpleNamespace(translation_seconds=0.01)

    def on_result(result):
        raise RuntimeError(f"callback failed: {result.russian_text!r}, {result.chinese_text!r}")

    diagnostic_logging.configure_diagnostic_logging(filename="worker.log")
    processor = SegmentProcessor(Pipeline(), temp_directory=tmp_path, on_result=on_result)
    processor.start()
    processor.enqueue(
        1,
        AudioSegment(np.zeros(512, dtype=np.float32), 0, 512, 0.0, 0.032, False),
    )
    processor.finish()
    assert processor.fatal_event.is_set()
    assert processor.metrics().worker_exited
    assert processor.fatal_error is not None
    assert russian not in processor.fatal_error and chinese not in processor.fatal_error
    assert "<redacted-caption>" in processor.fatal_error
    content = (isolated_logs / "worker.log").read_text(encoding="utf-8")
    assert "Traceback" in content and "RuntimeError:" in content
    if failure_stage == "result_callback":
        assert "Translation stage finished; segment=1; elapsed_seconds=" in content
    assert russian not in content and chinese not in content
    assert "<redacted-caption>" in content
    assert not tuple(tmp_path.glob("*.wav"))


def test_vad_worker_records_exception_stack_without_loading_model(isolated_logs: Path) -> None:
    import numpy as np

    from live_subtitles.realtime.live_vad import LiveVadSession
    from live_subtitles.realtime.metrics import AudioBlock

    class FailedVad:
        def reset(self):
            pass

        def speech_probability(self, _samples):
            raise RuntimeError("synthetic VAD failure")

    diagnostic_logging.configure_diagnostic_logging(filename="worker.log")
    session = LiveVadSession(vad=FailedVad())
    session._audio_queue.put_nowait(AudioBlock(0, np.zeros(512, dtype=np.float32), 0.0, 0.0))
    session._worker()
    assert session._fatal_event.is_set() and session._worker_exited.is_set()
    content = (isolated_logs / "worker.log").read_text(encoding="utf-8")
    assert "VAD worker failed; processed_blocks=0" in content
    assert "Traceback" in content and "RuntimeError: synthetic VAD failure" in content
