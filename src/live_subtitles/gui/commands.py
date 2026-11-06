"""Keyboard bindings shared by the subtitle and settings windows."""
from typing import Any, Callable


def bind_start_stop(window: Any, command: Callable[[], None]) -> None:
    def invoke(_event: Any) -> str:
        command()
        return "break"

    for sequence in ("<F8>", "<Control-space>"):
        window.bind(sequence, invoke)
