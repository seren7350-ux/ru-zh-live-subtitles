"""Small, privacy-conscious rotating diagnostics for the windowed executable."""

from __future__ import annotations

import copy
import io
import json
import logging
import os
import re
import tempfile
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

from .runtime_paths import log_directory

LOGGER_NAME = "live_subtitles"
LOG_FILENAME = "application.log"
MAX_LOG_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 2  # current file plus two backups = at most three files


class NullTextStream(io.TextIOBase):
    """A text sink suitable for libraries that expect a console-like object."""

    encoding = "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None


def safe_text_stream(stream: TextIO | None) -> TextIO:
    """Return *stream* or a harmless sink when a windowed process has no console."""

    return stream if stream is not None else NullTextStream()


def _text_variants(text: str) -> set[str]:
    """Include the common escaped forms used in exception messages."""

    return {
        text,
        repr(text)[1:-1],
        ascii(text)[1:-1],
        json.dumps(text, ensure_ascii=False)[1:-1],
        json.dumps(text, ensure_ascii=True)[1:-1],
    }


def sanitize_diagnostic_text(
    value: object,
    *,
    preserve_newlines: bool = False,
    sensitive_text: Iterable[str] = (),
) -> str:
    """Redact tokens and user-specific roots from infrastructure diagnostics."""

    text = str(value)
    # Callers handling translation errors know the input caption.  Redact it
    # before formatting because an upstream exception can echo that input.
    variants: set[str] = set()
    for sensitive in sensitive_text:
        if sensitive:
            variants.update(_text_variants(sensitive))
    for sensitive in sorted(variants, key=len, reverse=True):
        text = text.replace(sensitive, "<redacted-caption>")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not preserve_newlines:
        text = text.replace("\n", " ")
    text = text.strip()
    roots = (Path.home(), Path(tempfile.gettempdir()))
    for root in roots:
        raw = str(root)
        if raw:
            path_variants = _text_variants(raw) | _text_variants(raw.replace("\\", "/"))
            for path_variant in sorted(path_variants, key=len, reverse=True):
                text = re.sub(
                    re.escape(path_variant), "<redacted-path>", text,
                    flags=re.IGNORECASE,
                )
    text = re.sub(r"\bhf_[A-Za-z0-9]{8,}\b", "<redacted-token>", text)
    text = re.sub(
        r"\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer <redacted-token>",
        text,
        flags=re.IGNORECASE,
    )
    for variable in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        token = os.environ.get(variable)
        if token:
            for variant in sorted(_text_variants(token), key=len, reverse=True):
                text = text.replace(variant, "<redacted-token>")
    return text or "No diagnostic detail."


class _PrivacyFormatter(logging.Formatter):
    """Sanitize the entire rendered exception chain, without capturing locals."""

    def __init__(self, session_id: str | None) -> None:
        super().__init__(
            "%(asctime)s %(levelname)s %(name)s pid=%(process)d "
            "thread=%(threadName)s session=%(session_id)s %(message)s"
        )
        self.session_id = sanitize_diagnostic_text(session_id) if session_id else "-"

    def format(self, record: logging.LogRecord) -> str:
        # Formatter caches exc_text on the record; use a copy so the diagnostic
        # handler neither exposes raw cached text nor changes other handlers.
        safe_record = copy.copy(record)
        safe_record.session_id = self.session_id
        safe_record.exc_text = None
        sensitive = getattr(record, "sensitive_text", ())
        return sanitize_diagnostic_text(
            super().format(safe_record),
            preserve_newlines=True,
            sensitive_text=sensitive,
        )


def configure_diagnostic_logging(
    *, filename: str = LOG_FILENAME, session_id: str | None = None
) -> logging.Logger:
    """Configure one bounded log per process; workers supply their own filename.

    Repeating the same destination is idempotent.  A caller can update session
    context without creating duplicate handlers.  Exception records retain
    their full chain and stack frames, with paths, tokens and explicitly known
    caption text redacted after formatting.
    """

    if (
        not filename
        or Path(filename).name != filename
        or any(character in filename for character in "/\\:")
        or filename in {".", ".."}
    ):
        raise ValueError("Diagnostic log filename must be a plain filename.")

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    destination = log_directory()
    destination.mkdir(parents=True, exist_ok=True)
    log_path = (destination / filename).resolve()
    for existing in tuple(logger.handlers):
        if not getattr(existing, "_ru_zh_handler", False):
            continue
        if Path(existing.baseFilename) == log_path:
            if session_id is not None:
                existing.setFormatter(_PrivacyFormatter(session_id))
            return logger
        logger.removeHandler(existing)
        existing.close()
    handler = RotatingFileHandler(
        log_path,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler._ru_zh_handler = True  # type: ignore[attr-defined]
    handler.setLevel(logging.INFO)
    handler.setFormatter(_PrivacyFormatter(session_id))
    logger.addHandler(handler)
    return logger


def diagnostic_logger() -> logging.Logger:
    """Return the application logger without implicitly creating a file."""

    logger = logging.getLogger(LOGGER_NAME)
    if not logger.handlers:
        # Keep CLI errors concise when file logging has not been enabled; in
        # particular, do not let logging.lastResort print a second traceback.
        logger.addHandler(logging.NullHandler())
    return logger
