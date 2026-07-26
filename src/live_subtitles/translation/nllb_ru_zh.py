"""Lazy official NLLB Russian-to-Simplified-Chinese adapter."""

from __future__ import annotations

from typing import Any

from ..config import DEFAULT_NLLB_MODEL
from .runtime import ForcedBosRuZhTranslator
from .t5_ru_zh import TranslationModelError


class NllbRuZhTranslator(ForcedBosRuZhTranslator):
    engine = "nllb"
    default_model_name = DEFAULT_NLLB_MODEL
    source_language = "rus_Cyrl"
    target_language = "zho_Hans"

    def _target_token_id(self, tokenizer: Any) -> int:
        token_id = tokenizer.convert_tokens_to_ids(self.target_language)
        if token_id is None or token_id == getattr(tokenizer, "unk_token_id", None):
            raise TranslationModelError("NLLB tokenizer has no language token for 'zho_Hans'.")
        return int(token_id)
