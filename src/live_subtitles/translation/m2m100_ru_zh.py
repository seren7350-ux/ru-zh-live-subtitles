"""Lazy official M2M100 Russian-to-Chinese adapter."""

from __future__ import annotations

from typing import Any

from ..config import DEFAULT_M2M100_MODEL
from .runtime import ForcedBosRuZhTranslator
from .t5_ru_zh import TranslationModelError


class M2M100RuZhTranslator(ForcedBosRuZhTranslator):
    engine = "m2m100"
    default_model_name = DEFAULT_M2M100_MODEL
    source_language = "ru"
    target_language = "zh"

    def _target_token_id(self, tokenizer: Any) -> int:
        token_id = tokenizer.get_lang_id(self.target_language)
        if token_id is None:
            raise TranslationModelError("M2M100 tokenizer has no language token for 'zh'.")
        return int(token_id)
