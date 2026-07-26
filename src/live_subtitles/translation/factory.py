"""Translator factory for independently benchmarked engines."""

from __future__ import annotations

from typing import Any

from .m2m100_ru_zh import M2M100RuZhTranslator
from .nllb_ru_zh import NllbRuZhTranslator
from .t5_ru_zh import InvalidTranslationInputError, T5RuZhTranslator

TRANSLATION_ENGINES = ("t5", "m2m100", "nllb")


def create_translator(
    engine: str,
    model: str | None,
    device: str,
    num_beams: int,
    max_new_tokens: int,
) -> Any:
    """Create one lazy translator without importing Torch or loading weights."""

    classes = {
        "t5": T5RuZhTranslator,
        "m2m100": M2M100RuZhTranslator,
        "nllb": NllbRuZhTranslator,
    }
    try:
        translator_class = classes[engine]
    except KeyError as exc:
        allowed = ", ".join(TRANSLATION_ENGINES)
        raise InvalidTranslationInputError(
            f"Unknown translation engine {engine!r}; choose one of: {allowed}."
        ) from exc
    kwargs = {
        "device": device,
        "num_beams": num_beams,
        "max_new_tokens": max_new_tokens,
    }
    if model is not None:
        kwargs["model_name"] = model
    return translator_class(**kwargs)
