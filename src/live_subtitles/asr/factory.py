"""Explicit ASR backend selection without silent fallback."""

from __future__ import annotations

from typing import Any

from ..config import (
    DEFAULT_ASR_BACKEND,
    GIGAAM_MULTILINGUAL_BACKEND,
    LEGACY_ASR_MODEL,
    LEGACY_GIGAAM_ONNX_BACKEND,
)
from .base import ModelLoadError, SpeechRecognizer
from .gigaam_multilingual_ctc import GigaAMMultilingualCtcRecognizer
from .gigaam_onnx import GigaAMOnnxRecognizer


def create_recognizer(
    *,
    backend: str = DEFAULT_ASR_BACKEND,
    model_name: str | None = None,
    provider: str = "cpu",
    **kwargs: Any,
) -> SpeechRecognizer:
    """Create exactly the selected backend; never fall back to another model."""

    if backend == GIGAAM_MULTILINGUAL_BACKEND:
        return GigaAMMultilingualCtcRecognizer(
            model_name=model_name or GigaAMMultilingualCtcRecognizer.model_id,
            provider=provider,
            **kwargs,
        )
    if backend == LEGACY_GIGAAM_ONNX_BACKEND:
        provider_aliases = {
            "cpu": "CPUExecutionProvider",
            "cuda": "CUDAExecutionProvider",
        }
        legacy_provider = provider_aliases.get(provider.casefold(), provider)
        return GigaAMOnnxRecognizer(
            model_name=model_name or LEGACY_ASR_MODEL,
            provider=legacy_provider,
            **kwargs,
        )
    raise ModelLoadError(
        f"Unknown ASR backend {backend!r}. Select {GIGAAM_MULTILINGUAL_BACKEND!r} "
        f"or {LEGACY_GIGAAM_ONNX_BACKEND!r}."
    )
