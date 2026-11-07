"""Interface translations only. Subtitle content and diagnostic logs are untouched."""
LANGUAGES = ("en", "zh", "ru")
LANGUAGE_NAMES = ("English", "中文", "Русский")

# English is the stable source string; values are Chinese and Russian.
MESSAGES = {
    "Subtitle settings": ("字幕设置", "Настройки субтитров"),
    "Subtitles": ("字幕", "Субтитры"),
    "Input": ("输入", "Ввод"),
    "Window & files": ("窗口与保存", "Окно и файлы"),
    "Diagnostics": ("诊断与关于", "Диагностика"),
    "Interface language": ("界面语言", "Язык интерфейса"),
    "Language & size": ("语言与字号", "Язык и размер"),
    "Background & text": ("背景与文字", "Фон и текст"),
    "Show Russian": ("显示俄文", "Показывать русский"),
    "Chinese size (pt)": ("中文字号（磅）", "Китайский шрифт (пт)"),
    "Russian size (pt)": ("俄文字号（磅）", "Русский шрифт (пт)"),
    "Background opacity (%)": ("背景不透明度（%）", "Непрозрачность фона (%)"),
    "Text opacity (%)": ("文字不透明度（%）", "Непрозрачность текста (%)"),
    "Black text outline": ("黑色描边", "Чёрная обводка"),
    "Microphone input": ("麦克风输入", "Микрофон"),
    "Refresh": ("刷新", "Обновить"),
    "Session": ("当前会话", "Сеанс"),
    "Ready": ("就绪", "Готово"),
    "Fatal error": ("运行出错", "Ошибка приложения"),
    "Model setup required": ("需要安装模型", "Требуется установка моделей"),
    "Models ready": ("模型已就绪", "Модели готовы"),
    "Preparing models": ("正在准备模型", "Подготовка моделей"),
    "Preparing models...": ("正在准备模型…", "Подготовка моделей…"),
    "Preparing cached models...": ("正在准备本地模型…", "Подготовка локальных моделей…"),
    "Preparing speech recognition (ASR)": ("正在加载语音识别模型", "Загрузка модели распознавания речи"),
    "Preparing Chinese translation": ("正在加载中文翻译模型", "Загрузка модели перевода на китайский"),
    "Preparing voice detection (VAD)": ("正在加载语音检测模型", "Загрузка модели обнаружения речи"),
    "Demo: preparing without models": ("演示：无需加载模型", "Демонстрация: без загрузки моделей"),
    "System default": ("系统默认", "По умолчанию"),
    "No microphone input devices are available.": ("没有可用的麦克风输入设备。", "Нет доступных микрофонов."),
    "Selected microphone is no longer available. Refresh and choose another device.": (
        "所选麦克风已不可用，请刷新并选择其他设备。",
        "Выбранный микрофон недоступен. Обновите список и выберите другой."),
    "Start": ("开始", "Начать"),
    "Stop": ("停止", "Остановить"),
    "Stopping": ("正在停止", "Остановка"),
    "Cancel": ("取消", "Отмена"),
    "Listening": ("正在聆听", "Прослушивание"),
    "Preparing...": ("正在准备…", "Подготовка…"),
    "Stopping...": ("正在停止…", "Остановка…"),
    "Stopped": ("已停止", "Остановлено"),
    "Settings": ("设置", "Настройки"),
    "More": ("更多", "Ещё"),
    "Pinned": ("已置顶", "Поверх окон"),
    "Unpinned": ("未置顶", "Обычный режим"),
    "Clear display": ("清除显示", "Очистить экран"),
    "Exit application": ("退出应用", "Выйти"),
    "Window behavior": ("窗口行为", "Поведение окна"),
    "Always on top": ("字幕置顶", "Поверх других окон"),
    "Borderless window": ("无边框", "Без рамки"),
    "Show toolbar": ("显示工具栏", "Показывать панель"),
    "Subtitle files": ("字幕文件", "Файлы субтитров"),
    "Open subtitles folder": ("打开字幕目录", "Открыть папку субтитров"),
    "Position": ("快速移动", "Положение"),
    "Move to top": ("移到顶部", "Переместить вверх"),
    "Move to bottom": ("移到底部", "Переместить вниз"),
    "Reset this page": ("重置当前页", "Сбросить эту страницу"),
    "Reset only this page? Interface language and other pages are kept.": (
        "仅重置当前页？界面语言和其他页面的设置将保留。",
        "Сбросить только эту страницу? Язык интерфейса и другие страницы сохранятся."),
    "Model assets": ("模型资源", "Файлы моделей"),
    "Recheck model assets": ("重新检查模型", "Проверить модели"),
    "Open model folder": ("打开模型目录", "Открыть папку моделей"),
    "Open model setup instructions": ("模型安装说明", "Инструкция по установке моделей"),
    "Model setup help": ("模型安装帮助", "Помощь с моделями"),
    "Open logs folder": ("打开日志目录", "Открыть папку журналов"),
    "Save thread diagnostics": ("保存线程诊断", "Сохранить диагностику потоков"),
    "Models ready for offline use.": ("离线模型已就绪。", "Модели готовы к автономной работе."),
    "Model files need attention before starting.": ("开始前需要检查模型文件。", "Перед запуском проверьте файлы моделей."),
    "Demo mode · no microphone or models required.": ("演示模式 · 不使用麦克风或模型。", "Демонстрация · микрофон и модели не используются."),
    "Stop subtitles before changing the microphone.": ("请先停止字幕，再更换麦克风。", "Остановите субтитры перед сменой микрофона."),
    "F8 to start or stop. Audio is processed on this computer.": ("F8 开始或停止。音频仅在本机处理。", "F8 — запуск или остановка. Аудио обрабатывается локально."),
    "Subtitles are saved automatically (SRT).": ("字幕自动保存为 SRT。", "Субтитры сохраняются автоматически в SRT."),
    "SRT recording starts with the next session.": ("下次会话开始时自动记录 SRT。", "Запись SRT начнётся со следующего сеанса."),
    "Hidden at 0%. Settings remain available.": ("不透明度为 0 时不可见，设置仍可操作。", "При 0% слой невидим. Настройки доступны."),
    "Show shortcuts": ("显示快捷键", "Показать сочетания клавиш"),
    "Hide shortcuts": ("隐藏快捷键", "Скрыть сочетания клавиш"),
    "Double-click subtitles: show / hide toolbar\nRight-click subtitles: settings\nF8: start / stop   Ctrl+Q: exit": (
        "双击字幕：显示／隐藏工具栏\n右键字幕：设置\nF8：开始／停止   Ctrl+Q：退出",
        "Двойной щелчок: показать / скрыть панель\nПравая кнопка: настройки\nF8: запуск / остановка   Ctrl+Q: выход"),
}
_SOURCE = {translated: source for source, variants in MESSAGES.items() for translated in variants}

PREFIXES = {
    "Unable to start with the selected microphone: ": ("无法使用所选麦克风启动：", "Не удалось запустить выбранный микрофон: "),
    "Selected for next session: ": ("下次会话使用：", "Для следующего сеанса: "),
    "Unable to query microphone devices: ": ("无法查询麦克风设备：", "Не удалось получить список микрофонов: "),
    "Listening... ": ("正在聆听… ", "Прослушивание… "),
    "Model setup required: ": ("需要安装模型：", "Требуется установка моделей: "),
    "Stopping... waiting for engine": ("正在停止…等待引擎退出", "Остановка… ожидание завершения движка"),
}


def translate(text, language):
    source = _SOURCE.get(text, text)
    if language == "en":
        return source
    if source not in MESSAGES:
        if " · " in source:
            stage, elapsed = source.rsplit(" · ", 1)
            if elapsed.endswith("s") and elapsed[:-1].isdigit():
                return translate(stage, language) + " · " + elapsed[:-1] + ("秒" if language == "zh" else " с")
        for prefix, variants in PREFIXES.items():
            if source.startswith(prefix):
                return variants[0 if language == "zh" else 1] + translate(source[len(prefix):], language)
        return source
    return MESSAGES[source][0 if language == "zh" else 1]


def translate_widgets(widget, language):
    """Translate known interface labels; never traverse the caption surface."""
    try:
        text = widget.cget("text")
    except Exception as error:
        # Tk containers don't expose -text. Do not swallow unrelated failures.
        if type(error).__name__ != "TclError":
            raise
    else:
        if isinstance(text, str):
            previous = getattr(widget, "_translation_output", None)
            # Retain the original dynamic message, including diagnostic suffixes.
            # Reverse lookup alone only works for exact catalog entries.
            if text != previous:
                widget._translation_source = _SOURCE.get(text, text)
            source = getattr(widget, "_translation_source", text)
            translated = translate(source, language)
            widget._translation_output = translated
            if translated != text:
                widget.configure(text=translated)
    for child in widget.winfo_children():
        translate_widgets(child, language)
