RUSSIAN-CHINESE LIVE SUBTITLES - OFFLINE INSTALLATION
=====================================================

This is the self-contained CPU-only course-delivery installer. It includes the
application plus pinned Silero, GigaAM and NLLB model assets.

1. Copy the approximately 1.8 GB setup to the target Windows computer. If the
   delivery unexpectedly contains numbered .bin files, copy the entire folder.
2. Keep setup.exe and every numbered .bin file together if .bin files exist.
3. Double-click ru-zh-live-subtitles-cpu-offline-0.1.0-setup.exe.
4. No administrator privileges, Python, network connection, token or manual
   model copy is required.
5. Setup requires at least 8 GiB of free space before installation.

Application location:
  %LOCALAPPDATA%\Programs\RuZhLiveSubtitles

Model location:
  %LOCALAPPDATA%\ru-zh-live-subtitles\models

The Start-menu shortcut launches:
  live-overlay --translation-device cpu --offline --no-auto-start

Uninstall removes the application and shortcuts but preserves the model assets.
To reclaim that space later, manually delete:
  %LOCALAPPDATA%\ru-zh-live-subtitles\models

NLLB-200 distilled 600M is licensed under CC-BY-NC-4.0 and is restricted to
non-commercial use. See MODEL_LICENSES.txt after installation.
