"""Minimal translation contract."""

from typing import Protocol


class Translator(Protocol):
    def translate(self, text: str) -> str:
        """Translate one text and return the translated text."""
        ...
