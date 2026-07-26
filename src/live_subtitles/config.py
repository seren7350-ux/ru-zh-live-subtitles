"""Small set of application defaults used by the prototype."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ASR_MODEL = "gigaam-v3-e2e-rnnt"
DEFAULT_PROVIDER = "CPUExecutionProvider"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def hugging_face_cache_dir() -> Path:
    """Return the effective Hugging Face Hub cache directory without creating it."""

    if cache := os.environ.get("HF_HUB_CACHE"):
        return Path(cache).expanduser()
    if home := os.environ.get("HF_HOME"):
        return Path(home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"
