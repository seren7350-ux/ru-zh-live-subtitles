import json
import math

from live_subtitles.preferences import Preferences, validated
from live_subtitles.gui.workarea import fit_rectangle, positioned, client_placement_area


def test_preferences_round_trip_excludes_session_and_invalid_values(tmp_path):
    store = Preferences(tmp_path / "preferences.json")
    store.save({"opacity": 0, "text_opacity": 0, "show_russian": False,
                "text_outline": True, "window_rect": [-1800, 40, 900, 280],
                "microphone_name": "Microphone", "listening": True,
                "entries": ["private caption"], "chinese_font_size": 999})
    assert store.load() == {"opacity": 0.0, "text_opacity": 0.0,
                            "show_russian": False, "text_outline": True,
                            "window_rect": [-1800, 40, 900, 280], "microphone_name": "Microphone"}
    assert "private" not in store.path.read_text()
    assert not store.path.with_suffix(".json.new").exists()


def test_invalid_preferences_never_execute_or_accept_nonfinite_values(tmp_path):
    assert validated({"opacity": math.nan, "text_opacity": math.inf,
                      "topmost": "false", "window_rect": [0, 0, 1, 1]}) == {}
    store = Preferences(tmp_path / "preferences.json")
    assert store.load() == {}
    store.path.write_text('{"version":2,"preferences":{}}')
    import pytest
    with pytest.raises(ValueError):
        store.load()
    assert json.loads(store.path.read_text())["version"] == 2


def test_ui_language_is_validated_and_persisted(tmp_path):
    store = Preferences(tmp_path / "preferences.json")
    for language in ("en", "zh", "ru"):
        store.save({"ui_language": language})
        assert store.load() == {"ui_language": language}
    assert validated({"ui_language": "unexpected"}) == {}


def test_position_presets_use_negative_monitor_workarea():
    area = (-1920, 0, 1920, 1040)
    assert positioned((-1800, 300, 900, 280), area, "top") == (-1410, 20, 900, 280)
    assert positioned((-1800, 300, 900, 280), area, "bottom") == (-1410, 740, 900, 280)


def test_disconnected_monitor_geometry_is_recovered():
    assert fit_rectangle((-1800, 800, 900, 280), (0, 0, 1280, 680)) == (0, 400, 900, 280)
    assert fit_rectangle((3000, 3000, 1900, 1200), (0, 0, 1280, 680)) == (0, 0, 1280, 680)


def test_framed_placement_reserves_title_and_border():
    from types import SimpleNamespace
    window = SimpleNamespace(winfo_x=lambda:100, winfo_y=lambda:200,
                             winfo_rootx=lambda:108, winfo_rooty=lambda:231)
    area = client_placement_area(window, (0, 0, 1280, 680), framed=True)
    assert area == (0, 0, 1264, 641)
    x, y, width, height = positioned((100, 200, 900, 280), area, 'bottom')
    assert y + height + 39 <= 680
    assert client_placement_area(window, (0, 0, 1280, 680), framed=False) == (0, 0, 1280, 680)
