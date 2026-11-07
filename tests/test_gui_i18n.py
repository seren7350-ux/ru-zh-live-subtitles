from live_subtitles.gui.i18n import MESSAGES, translate, translate_widgets


def test_all_catalog_entries_round_trip():
    for source, (chinese, russian) in MESSAGES.items():
        assert chinese and russian
        assert translate(source, "zh") == chinese
        assert translate(chinese, "ru") == russian
        assert translate(russian, "en") == source


def test_dynamic_status_translates_ui_without_changing_device_or_error():
    assert translate("Listening... USB Mic", "zh") == "正在聆听… USB Mic"
    assert translate("Preparing Chinese translation · 12s", "ru") == "Загрузка модели перевода на китайский · 12 с"
    assert translate("Unable to query microphone devices: Error -9999", "zh") == "无法查询麦克风设备：Error -9999"
    assert translate("Selected for next session: System default", "zh") == "下次会话使用：系统默认"
    assert translate("Unknown diagnostic detail", "ru") == "Unknown diagnostic detail"


def test_dynamic_widget_keeps_original_across_language_changes():
    class Label:
        text = "Selected for next session: USB microphone"
        def cget(self, _name):
            return self.text
        def configure(self, *, text):
            self.text = text
        def winfo_children(self):
            return []
    label = Label()
    original = label.text
    for language in ("zh", "ru", "en", "ru", "zh", "en"):
        translate_widgets(label, language)
        assert label.text == translate(original, language)
    label.text = "Listening... USB microphone"
    translate_widgets(label, "zh")
    assert label.text == "正在聆听… USB microphone"


def test_stop_elapsed_time_is_localized():
    assert translate("Stopping... waiting for engine · 12s", "zh") == "正在停止…等待引擎退出 · 12秒"
