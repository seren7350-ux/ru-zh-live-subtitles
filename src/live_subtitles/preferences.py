"""Versioned user preferences. Session state and subtitle content are never stored."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from .runtime_paths import user_data_directory

BOOL_FIELDS = ("show_russian", "topmost", "borderless", "toolbar_visible", "text_outline")
NUM_FIELDS = {"opacity": (0, 1), "text_opacity": (0, 1),
              "chinese_font_size": (16, 72), "russian_font_size": (10, 48)}


def validated(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        return {}
    result = {key: values[key] for key in BOOL_FIELDS if type(values.get(key)) is bool}
    for key, (minimum, maximum) in NUM_FIELDS.items():
        value = values.get(key)
        if type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum:
            result[key] = int(value) if "font_size" in key else float(value)
    rect = values.get("window_rect")
    if (isinstance(rect, list) and len(rect) == 4 and all(type(n) is int for n in rect)
            and all(abs(n) <= 100000 for n in rect) and rect[2] >= 520 and rect[3] >= 180):
        result["window_rect"] = rect
    device = values.get("microphone_name")
    if values.get("ui_language") in ("en", "zh", "ru"):
        result["ui_language"] = values["ui_language"]
    if isinstance(device, str) and len(device) <= 1000:
        result["microphone_name"] = device
    return result


class Preferences:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or user_data_directory() / "preferences.json"

    def load(self) -> dict[str, Any]:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(document, dict) or document.get("version") != 1:
            raise ValueError("Unsupported preferences format")
        return validated(document.get("preferences"))

    def save(self, values: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.new")
        payload = {"version": 1, "preferences": validated(values)}
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, self.path)
