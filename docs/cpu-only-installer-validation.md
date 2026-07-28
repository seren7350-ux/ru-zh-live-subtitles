# CPU-only installer validation

This document records development-machine validation for the unsigned
self-contained per-user CPU offline installer. It must not be read as
clean-machine validation.

## Candidate

- application version: `0.1.0`;
- stable AppId: `{8773A11B-6B74-42AF-85AF-CAD43EB946CF}`;
- default directory: `%LOCALAPPDATA%\Programs\RuZhLiveSubtitles`;
- privileges: current user, `PrivilegesRequired=lowest`, no UAC expected;
- source onedir: `dist\ru-zh-subtitles-cpu`;
- model payload: 17 pinned files, 3,377,386,294 bytes;
- model destination: `%LOCALAPPDATA%\ru-zh-live-subtitles\models`;
- main shortcut arguments: `live-overlay --translation-device cpu --offline --no-auto-start`;
- optional desktop shortcut: unchecked by default;
- compiler: official Inno Setup 7.0.2 x64, with a valid Pyrsys B.V. signature;
- output is intentionally unsigned; SmartScreen behavior is not guaranteed.

A maximum-compression syntax/size preflight produced a single
1,762,415,746-byte (1.641 GiB) unsigned setup, below the 3.8 GB disk-spanning
threshold. The final commit-bound build records its own exact size and SHA in
the ignored report; the preflight hash is not a delivery checksum.

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
DLLs and zero model weights. A final onedir rebuild adds
`MODEL_LICENSES.txt` beside `README.md`, `THIRD_PARTY_NOTICES.md`,
`MODEL_SETUP.txt`, and `CPU_BUILD_METADATA.json`; exact final count and bytes
are recorded by the validator. Setup size, SHA-256, compiler timing, and
provenance SHA are kept in ignored `dist\installer-offline\build-report.json`,
not copied into tracked documentation.

## Fail-closed build transaction

`build_installer.ps1` rejects every tracked modification, staged change,
conflict, and non-ignored untracked file using
`git status --porcelain=v1 --untracked-files=all`. Ignored build, dist, data,
model, log, and virtual-environment content remains permitted. There is no
bypass parameter.

CPU policy, provenance, the frozen translation doctor, full model manifest/
size/SHA validation, model and release metadata, ISCC compilation, installer
hashing/signature inspection, compiler logging, and the build report all
complete inside one unique ignored temporary directory. The old same-version
offline setup, metadata, instructions and numbered slices are removed before
the attempt. Success publishes evidence and any slices first, then setup as the
success marker. Catch/finally removes every same-version offline output and the
temporary directory after failure; historical model-less output is untouched.

An active stale-provenance test used a separate minimal CPU fixture whose
metadata commit was deliberately wrong. It failed before ISCC, removed the old
same-version setup/metadata/report/log, left no transaction directory, and
preserved a different-version candidate. Real temporary-Git-repository tests
also cover dirty worktrees and injected CPU-policy, model-bundle, ISCC, and
report failures. Tiny fake bundles test corruption without loading real models.

## Validation scope

The interactive path checks the default current-user directory, displayed disk
requirement, optional shortcut task, Start Menu entries, uninstall entry, and
absence of elevation. The silent path uses `/VERYSILENT`,
`/SUPPRESSMSGBOXES`, `/NORESTART`, and a local ignored log. A path containing
Chinese characters and a space is also exercised. Same-version reinstall is a
repair check, not a cross-version upgrade test.

Installed application files are compared against the full CPU manifest; release
and model-bundle metadata plus `unins000` files may be additional. Model files
are compared to the validated model manifest. The application runtime must pass
the CPU translation doctor, contain no CUDA DLL, and keep weights outside
`{app}`.

The installer no longer overwrites documentation from the repository or Inno
source directory. The four installed documents come only from the
provenance-bound CPU onedir, and their installed SHA-256 values must equal the
corresponding full-manifest records.

The empty-state install is run with isolated process-local `LOCALAPPDATA`, no
explicit Hugging Face variables, and no Python/venv in `PATH`. Setup must create
the model root automatically. `model-doctor` must report READY before the GUI is
started. The offline GUI must display one real RU/ZH result, support Stop then
microphone selection, make no application network connection, and release
workers, the microphone, temporary WAVs, and the application process.

Uninstall removes `{app}`, installer-created shortcuts, and the AppId uninstall
entry. It must not remove `%LOCALAPPDATA%\ru-zh-live-subtitles\models`, the
normal Hugging Face cache, logs, settings, recordings, or staging. File count,
byte count, and key hashes are compared before and after uninstall.

Windows Defender custom scans cover the CPU onedir, complete installer delivery,
installed application and installed model directory with real-time protection
left enabled and no exclusions. The installer itself remains unsigned.

Final measured reinstall, GUI, uninstall, Defender, and automated-test results
are recorded in [development notes](development.md).
