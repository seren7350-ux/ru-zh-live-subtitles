# Документация | 文档索引

Здесь собраны описание архитектуры, инструкции по сборке и результаты проверок.
Текущие возможности приложения описаны в [основном README](../README.md).
Исторические записи относятся к указанным в них версиям.

这里收录架构、构建说明与验证记录。当前功能以[仓库首页](../README.md)为准；
历史记录只对应各自注明的版本。

## Приложение и разработка / 应用与开发

- [Структура проекта / 项目结构](repository-layout.md)
- [Архитектура / 系统架构](architecture.md)
- [Настройки и диагностика / 设置与诊断](application-settings.md)
- [Подготовка моделей / 模型准备](model-assets-setup.md)
- [История разработки / 开发记录](development.md)
- [План исправлений по замечаниям преподавателя / 教师反馈修复计划](reliability-roadmap.md)
- [Дизайн интерфейса / 界面设计](ui-design-direction.md)

## Обработка речи и перевод / 语音处理与翻译

- [Silero VAD через ONNX / Silero ONNX 语音检测](direct-silero-onnx-vad.md)
- [Работа с микрофоном / 实时麦克风输入](live-microphone-vad.md)
- [Распознавание и перевод аудиофайлов / 音频文件识别与翻译](offline-audio-translation-pipeline.md)
- [Субтитры в терминале / 终端字幕](live-terminal-subtitles.md)
- [Окно субтитров / 字幕窗口](always-on-top-subtitle-overlay.md)
- [Выбор модели перевода / 翻译模型选择](translation-model-selection.md)

## Сборка и проверка / 构建与验证

- [Правила распространения CPU-версии / CPU 版本分发规则](cpu-only-distribution.md)
- [Полный автономный установщик / 完整离线安装器](self-contained-offline-installer.md)
- [Проверка установщика / 安装器验证记录](cpu-only-installer-validation.md)
- [Проверка в чистой среде / 洁净环境验证记录](cpu-clean-machine-recovery-validation.md)
- [Средства проверки в Windows Sandbox / Windows Sandbox 验证工具](windows-sandbox-clean-machine-validation.md)

## Предыдущие исследования / 历史研究

- [Сравнение моделей перевода / 翻译模型比较](translation-model-comparison.md)
- [Первоначальные опыты по сборке Windows-приложения / Windows 打包初步实验](windows-packaging-spike.md)
- [Уменьшение размера пакета / 软件包体积优化](windows-package-size-optimization.md)
