RUSSIAN-CHINESE LIVE SUBTITLES 0.2.0 - OFFLINE INSTALLATION
================================================================

This unsigned CPU-only course installer contains the application and the pinned
Silero VAD 6.2.1, GigaAM Multilingual Large CTC, and NLLB model assets. It is
for non-commercial course use.

1. Copy or download setup.exe, SHA256SUMS.txt, and every numbered .bin file.
2. Keep setup.exe and all numbered .bin files in the same directory. Missing
   any slice makes setup fail; do not rename the files.
3. Optionally verify every setup/.bin hash against SHA256SUMS.txt.
4. Double-click ru-zh-live-subtitles-cpu-offline-0.2.0-setup.exe.
5. No administrator privileges, Python, network connection, token, or manual
   model copy is required.
6. Setup requires at least 12 GiB of free space before installation.

Application location:
  %LOCALAPPDATA%\Programs\RuZhLiveSubtitles

Model location:
  %LOCALAPPDATA%\ru-zh-live-subtitles\models

The Start-menu shortcut launches:
  live-overlay --translation-device cpu --offline --no-auto-start

The default ASR is the pinned official ai-sage/GigaAM-Multilingual large_ctc
model. The legacy RNNT backend is retained only for explicit developer
comparison; its weights are not included in this 0.2.0 installer.

Large CTC and NLLB require substantial memory. The minimum supported system RAM
is 8 GiB and 16 GiB is recommended. Initial model preparation is slower than
later sessions because both CPU models must be loaded from disk.

Uninstall removes the application and shortcuts but preserves the model assets.
To reclaim that space later, manually delete:
  %LOCALAPPDATA%\ru-zh-live-subtitles\models

NLLB-200 distilled 600M is licensed under CC-BY-NC-4.0 and is restricted to
non-commercial use. See MODEL_LICENSES.txt after installation.
