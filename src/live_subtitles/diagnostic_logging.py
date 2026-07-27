"""Small, privacy-conscious rotating diagnostics for the windowed executable."""

from __future__ import annotations

import io
import logging
import os
import re
import tempfile
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


def sanitize_diagnostic_text(value: object) -> str:
    """Redact tokens and user-specific roots from infrastructure diagnostics."""

    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    roots = (Path.home(), Path(tempfile.gettempdir()))
    for root in roots:
        raw = str(root)
        if raw:
            text = re.sub(re.escape(raw), "<redacted-path>", text, flags=re.IGNORECASE)
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
            text = text.replace(token, "<redacted-token>")
    return text or "No diagnostic detail."


class _PrivacyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = sanitize_diagnostic_text(record.getMessage())
        record.args = ()
        return True


def configure_diagnostic_logging() -> logging.Logger:
    """Configure the bounded per-user log once and return its logger."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if any(getattr(handler, "_ru_zh_handler", False) for handler in logger.handlers):
        return logger

    destination = log_directory()
    destination.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        destination / LOG_FILENAME,
        maxBytes=MAX_LOG_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler._ru_zh_handler = True  # type: ignore[attr-defined]
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(_PrivacyFilter())
    logger.addHandler(handler)
    return logger


def diagnostic_logger() -> logging.Logger:
    """Return the application logger without implicitly creating a file."""

    return logging.getLogger(LOGGER_NAME)
