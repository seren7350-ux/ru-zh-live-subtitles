"""Small set of application defaults used by the prototype."""

from __future__ import annotations

import os
from pathlib import Path

from .runtime_paths import bundled_resource_path, is_frozen

DEFAULT_ASR_MODEL = "gigaam-v3-e2e-rnnt"
DEFAULT_PROVIDER = "CPUExecutionProvider"
DEFAULT_T5_TRANSLATION_MODEL = "utrobinmv/t5_translate_en_ru_zh_base_200"
DEFAULT_M2M100_MODEL = "facebook/m2m100_418M"
DEFAULT_NLLB_MODEL = "facebook/nllb-200-distilled-600M"
DEFAULT_TRANSLATION_ENGINE = "nllb"
DEFAULT_TRANSLATION_MODEL = DEFAULT_NLLB_MODEL
DEFAULT_SOURCE_LANGUAGE = "rus_Cyrl"
DEFAULT_TARGET_LANGUAGE = "zho_Hans"
DEFAULT_TRANSLATION_DEVICE = "auto"
PROJECT_ROOT = (
    bundled_resource_path(".") if is_frozen() else Path(__file__).resolve().parents[2]
)


def hugging_face_cache_dir() -> Path:
    """Return the effective Hugging Face Hub cache directory without creating it."""

    if cache := os.environ.get("HF_HUB_CACHE"):
        return Path(cache).expanduser()
    if home := os.environ.get("HF_HOME"):
        return Path(home).expanduser() / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def hugging_face_model_cache_dir(model_name: str) -> Path:
    """Return the conventional Hub cache directory for one repository."""

    return hugging_face_cache_dir() / f"models--{model_name.replace('/', '--')}"
