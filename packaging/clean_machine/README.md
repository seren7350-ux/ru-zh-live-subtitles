# Windows Sandbox clean-machine validation kit

This directory contains reproducible tooling for validating the shared
PyInstaller onedir in a fresh, network-disabled Windows Sandbox. It does not
enable Windows features, download models, install software, or modify host
security settings. Generated packages, model assets, `.wsb` files, WAV files,
manifests, logs, and results belong under the Git-ignored
`data/clean-machine-validation/` tree.

Windows Sandbox is a useful disposable compatibility check, not proof that the
application works on every physical Windows computer. A visible vGPU is not
proof of CUDA support; only the frozen runtime's actual Torch CUDA result can
select the CUDA validation path.

## Trust boundary

- The combined onedir, selected model assets, and scripts are mapped read-only.
- Only a newly created, empty, run-specific results directory is writable.
- The repository, virtual environments, user profile, and complete Hugging Face
  cache are never mapped.
- Sandbox networking is disabled. Both Hugging Face offline variables are set
  for the cache-backed phase.
- Model assets are copied into a writable cache inside the disposable Sandbox;
  the host staging remains read-only.
- The model staging is local-test-only. It is never committed, uploaded, or
  bundled with the application. NLLB remains limited to CC-BY-NC-4.0
  non-commercial research validation.

The approved model set is exact:

| Component | ID/revision | License |
|---|---|---|
| Silero VAD | `silero-vad/6.2.1` | MIT |
| GigaAM | `istupakov/gigaam-v3-onnx@322c3b29492673eb7d0b434bfa9dfb8653e34d02` | MIT |
| NLLB | `facebook/nllb-200-distilled-600M@f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0 |

`prepare_assets.py` refuses extra model files, absolute manifest paths, user or
repository paths embedded in the package, credentials, authentication tokens,
audio, and unapproved model weights. The generated manifests contain relative
paths, SHA-256 values, sizes, revisions, license identifiers, and explicit
non-distribution flags.

## Host preparation

Run these commands only after building `dist/ru-zh-subtitles` from the reviewed
commit. They use the existing development environment and never resolve new
dependencies:

```powershell
$Root = (Resolve-Path .).Path
$Stage = Join-Path $Root "data\clean-machine-validation"
$Hub = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
$Silero = Join-Path $env:LOCALAPPDATA "ru-zh-live-subtitles\models\silero-vad\6.2.1"

.\.venv\Scripts\python.exe packaging\clean_machine\prepare_assets.py `
  --combined-dir dist\ru-zh-subtitles `
  --staging-root $Stage `
  --repo-root $Root `
  --toolkit-dir packaging\clean_machine `
  --expected-commit (git rev-parse HEAD) `
  --stage-models `
  --hf-hub $Hub `
  --silero-cache $Silero

.\.venv\Scripts\python.exe packaging\clean_machine\generate_sandbox_config.py `
  --staging-root $Stage `
  --repo-root $Root
```

If microphone redirection may be unavailable, add
`--test-wav data\sample-fixed-non-sensitive.wav` to `prepare_assets.py`. The
tool copies it only to the ignored scripts staging and creates a relative-path
SHA-256 `test-audio-manifest.json`; it never places audio in model-assets. Do not
use private speech.

The generator chooses 16 GB for hosts with at least 32 GB RAM, 12 GB for
24–31 GB, 8 GB for 16–23 GB, and a conservative 4 GB package-only baseline
below 16 GB. CPU NLLB validation may be resource-limited on small hosts.

## Disposable run sequence

1. Close any previous Sandbox, then open `generated-package-only.wsb`. Confirm
   that Python, `py`, pip, Git, source, virtual environments, model caches, and
   prior logs are absent. The logon script checks manifests, CLI help, devices,
   missing-cache doctors, overlay startup, a missing-cache live startup, network
   isolation, read-only package behavior, privacy, and residual processes.
2. Manually verify overlay Settings, Start/Stop, Pin/Unpin, Borderless, Exit,
   single-window behavior, and the absence of a console behind the GUI. Close
   the Sandbox and confirm only its dedicated result directory changed.
3. Open `generated-offline-cache.wsb` as a new instance. The logon script
   verifies both manifests, copies only approved assets to disposable writable
   caches, sets offline mode, runs all doctors, classifies actual CUDA versus CPU,
   and optionally runs a staged non-sensitive WAV pipeline.
4. Re-run `devices` inside the Sandbox. Never assume the host device number. If
   a 16 kHz mono input exists, perform the short microphone test. Use CUDA only
   when the frozen runtime reports CUDA available; otherwise use CPU and do not
   apply GPU latency gates.
5. After doctors, file pipeline, overlay smoke, and process checks pass, perform
   the appropriate live GUI test. Record captions by direct screen observation;
   they must not be copied into diagnostic logs.
6. Close the second Sandbox. Open the same offline config again for a third,
   fresh instance and repeat manifest checks, doctors, overlay, one file pipeline,
   GUI start/exit, and residual-process checks. This proves the second run did
   not depend on disposable cache residue.

The optional local test WAV must be added through `--test-wav`, not copied by
hand. It must be a non-sensitive fixed Russian test sentence and must never be
committed or uploaded. The offline startup refuses audio without a matching
relative SHA manifest.

## Manual capability checklist

If Windows Sandbox is unavailable, do not simulate a clean machine with a
reduced `PATH`. On a Pro, Enterprise, or Education machine, an administrator may
manually verify firmware virtualization, enable the Windows Sandbox optional
feature, restart if Windows requests it, and then repeat the sequence above.
Those host changes are intentionally outside this toolkit and must never be
performed automatically.

## Result handling

`collect_results.ps1` exports only command status, timings, hashes, counts,
provider/device status, and redacted output. It removes token-like values,
emails, absolute paths, and Russian/Chinese caption fields. Review every JSON
file before moving it outside the dedicated results directory. Defender may be
run inside Sandbox when its CLI is available, but the toolkit never disables
Defender, changes exclusions, or uploads binaries to third-party scanners.
