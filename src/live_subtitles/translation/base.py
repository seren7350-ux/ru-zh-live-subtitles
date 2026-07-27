"""Minimal translation contract."""

from typing import Protocol


class Translator(Protocol):
    def prepare(self) -> float:
        """Load tokenizer/model once and return total load seconds."""
        ...

    def translate(self, text: str) -> str:
        """Translate one text and return the translated text."""
        ...
