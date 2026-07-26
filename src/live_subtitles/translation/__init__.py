"""Independent offline text-translation prototype."""

from .base import Translator
from .factory import TRANSLATION_ENGINES, create_translator
from .m2m100_ru_zh import M2M100RuZhTranslator
from .nllb_ru_zh import NllbRuZhTranslator
from .t5_ru_zh import T5RuZhTranslator, TranslationError, TranslationMetrics

__all__ = [
    "M2M100RuZhTranslator",
    "NllbRuZhTranslator",
    "T5RuZhTranslator",
    "TRANSLATION_ENGINES",
    "TranslationError",
    "TranslationMetrics",
    "Translator",
    "create_translator",
]
