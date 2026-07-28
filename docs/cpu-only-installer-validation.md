# CPU-only installer validation

This document records the development-machine validation for the unsigned
per-user CPU installer. It must not be read as clean-machine validation.

## Candidate

- application version: `0.1.0`;
- stable AppId: `{8773A11B-6B74-42AF-85AF-CAD43EB946CF}`;
- default directory: `%LOCALAPPDATA%\Programs\RuZhLiveSubtitles`;
- privileges: current user, `PrivilegesRequired=lowest`, no UAC expected;
- source onedir: `dist\ru-zh-subtitles-cpu`;
- main shortcut arguments: `live-overlay --translation-device cpu --offline --no-auto-start`;
- optional desktop shortcut: unchecked by default;
- compiler: official Inno Setup 7.0.2 x64, with a valid Pyrsys B.V. signature;
- output is intentionally unsigned; SmartScreen behavior is not guaranteed.

The rebuilt CPU onedir contained 5,528 files and 70 DLLs, occupied 658,392,446
bytes, contained `torch_cpu.dll`, and contained zero CUDA DLLs and zero model
weights. The compressed installer was 215,924,985 bytes and built in 96.972
seconds with no Inno warnings. Its SHA-256 was
`DE0B535D123B2470F680737CB10F635433612E29D8C90DE44A31F65BF6A895CC`.

## Validation scope

The interactive path checks the default current-user directory, displayed disk
requirement, optional shortcut task, Start Menu entries, uninstall entry, and
absence of elevation. The silent path uses `/VERYSILENT`,
`/SUPPRESSMSGBOXES`, `/NORESTART`, and a local ignored log. A path containing
Chinese characters and a space is also exercised. Same-version reinstall is a
repair check, not a cross-version upgrade test.

Installed files are compared against the full CPU manifest. Only installer
documentation, release metadata, and `unins000` files may be additional. The
installed runtime must still pass the CPU translation doctor and contain no
CUDA DLL or model weight.

The missing-model GUI is run with isolated process-local `LOCALAPPDATA` and
`HF_HOME`. It must open without a console, display `Model setup required`, block
Start before worker or microphone creation, make no network connection, and
exit without residue. The cached-model GUI is run offline and must display one
real RU/ZH result, support Stop then microphone selection, and release workers,
the microphone, temporary WAVs, and the application process.

Uninstall removes `{app}`, installer-created shortcuts, and the AppId uninstall
entry. It must not remove `%LOCALAPPDATA%\ru-zh-live-subtitles\models`, the
normal Hugging Face cache, logs, settings, recordings, or staging. File count,
byte count, and key hashes are compared before and after uninstall.

Windows Defender custom scans cover the CPU onedir, setup executable, and
installed directory with real-time protection left enabled and no exclusions.
The installer itself remains unsigned.

Final measured reinstall, GUI, uninstall, Defender, and automated-test results
are recorded in [development notes](development.md).
