"""Small set of application defaults used by the prototype."""

from __future__ import annotations

from pathlib import Path

from .model_assets import (
    GIGAAM_MULTILINGUAL_MODEL_ID,
    LEGACY_GIGAAM_MODEL_ID,
    hugging_face_cache_candidates,
)
from .runtime_paths import bundled_resource_path, is_frozen

GIGAAM_MULTILINGUAL_BACKEND = "gigaam_multilingual_large_ctc"
LEGACY_GIGAAM_ONNX_BACKEND = "gigaam_v3_e2e_rnnt_onnx_legacy"
ASR_BACKENDS = (GIGAAM_MULTILINGUAL_BACKEND, LEGACY_GIGAAM_ONNX_BACKEND)
DEFAULT_ASR_BACKEND = GIGAAM_MULTILINGUAL_BACKEND
DEFAULT_ASR_MODEL = GIGAAM_MULTILINGUAL_MODEL_ID
DEFAULT_PROVIDER = "cpu"
LEGACY_ASR_MODEL = "gigaam-v3-e2e-rnnt"
LEGACY_PROVIDER = "CPUExecutionProvider"
DEFAULT_T5_TRANSLATION_MODEL = "utrobinmv/t5_translate_en_ru_zh_base_200"
DEFAULT_M2M100_MODEL = "facebook/m2m100_418M"
DEFAULT_NLLB_MODEL = "facebook/nllb-200-distilled-600M"
DEFAULT_TRANSLATION_ENGINE = "nllb"
DEFAULT_TRANSLATION_MODEL = DEFAULT_NLLB_MODEL
DEFAULT_SOURCE_LANGUAGE = "rus_Cyrl"
DEFAULT_TARGET_LANGUAGE = "zho_Hans"
DEFAULT_TRANSLATION_DEVICE = "cpu"
PROJECT_ROOT = (
    bundled_resource_path(".") if is_frozen() else Path(__file__).resolve().parents[2]
)


def hugging_face_cache_dir() -> Path:
    """Return the effective Hugging Face Hub cache directory without creating it."""

    return hugging_face_cache_candidates()[0]


def hugging_face_model_cache_dir(model_name: str) -> Path:
    """Return the conventional Hub cache directory for one repository."""

    return hugging_face_cache_dir() / f"models--{model_name.replace('/', '--')}"
