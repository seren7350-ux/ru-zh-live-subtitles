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

Every accepted CPU onedir now carries a top-level `CPU_BUILD_METADATA.json`.
Its fixed schema binds application version, a 40-character lowercase Git SHA,
CPU runtime family, a clean-worktree assertion, Windows x64, and
`packaging/combined_cpu.spec`. The file is UTF-8 without a BOM and contains no
checkout, user, virtual-environment, remote, model, or machine path. The CPU
validator and installer metadata generator independently require the embedded
version and commit to match the clean current repository and the explicit
`ExpectedCommit`.

The hardened development-machine rebuild contained 5,529 files and 70 DLLs,
occupied 658,394,024 bytes, contained `torch_cpu.dll`, and contained zero CUDA
DLLs and zero model weights. `README.md`, `THIRD_PARTY_NOTICES.md`,
`MODEL_SETUP.txt`, and `CPU_BUILD_METADATA.json` were present at the onedir
root. Exact final setup size, SHA-256, compiler timing, and provenance SHA are
kept in the ignored `dist\installer\build-report.json` and release metadata,
not copied into tracked documentation.

## Fail-closed build transaction

`build_installer.ps1` rejects every tracked modification, staged change,
conflict, and non-ignored untracked file using
`git status --porcelain=v1 --untracked-files=all`. Ignored build, dist, data,
model, log, and virtual-environment content remains permitted. There is no
bypass parameter.

CPU policy, provenance, the frozen translation doctor, release metadata, ISCC
compilation, installer hashing/signature inspection, compiler logging, and the
build report all complete inside one unique ignored temporary directory. The
old same-version setup and its three companion outputs are removed before the
attempt. Success publishes release metadata, compiler log, and build report
first, then publishes setup last as the success marker. Catch/finally removes
all four same-version outputs and the temporary directory after any failure;
different-version historical candidates are not removed.

An active stale-provenance test used a separate minimal CPU fixture whose
metadata commit was deliberately wrong. It failed before ISCC, removed the old
same-version setup/metadata/report/log, left no transaction directory, and
preserved a different-version candidate. Real temporary-Git-repository tests
also cover dirty worktrees and injected CPU-policy, ISCC, and report failures.

## Validation scope

The interactive path checks the default current-user directory, displayed disk
requirement, optional shortcut task, Start Menu entries, uninstall entry, and
absence of elevation. The silent path uses `/VERYSILENT`,
`/SUPPRESSMSGBOXES`, `/NORESTART`, and a local ignored log. A path containing
Chinese characters and a space is also exercised. Same-version reinstall is a
repair check, not a cross-version upgrade test.

Installed files are compared against the full CPU manifest. Only release
metadata and `unins000` files may be additional. The
installed runtime must still pass the CPU translation doctor and contain no
CUDA DLL or model weight.

The installer no longer overwrites documentation from the repository or Inno
source directory. The three installed documents come only from the
provenance-bound CPU onedir, and their installed SHA-256 values must equal the
corresponding full-manifest records.

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
