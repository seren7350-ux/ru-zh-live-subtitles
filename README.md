# Russian–Chinese Live Subtitles

An offline-first Windows prototype for Russian lecture subtitles. The current
milestone connects cached Silero VAD, the official pinned GigaAM Multilingual
Large CTC short-WAV recognizer, and NLLB translation in an ordered subtitle loop.

## Current scope

The complete short-file path is now:

```text
WAV -> GigaAM ASR -> Russian text -> NLLB translation -> Chinese text
```

The live terminal path is:

```text
Microphone -> bounded audio queue -> Silero ONNX VAD -> immutable speech segment
  -> bounded segment queue -> one GigaAM/NLLB worker -> Russian and Chinese terminal text
```

The current GUI spike adds an always-on-top Tk subtitle surface around that
pipeline. Tk stays in the main process while each live session runs in one
spawned worker process and returns immutable events through a bounded queue.
This prevents CPU/GPU model work from starving the Tk mainloop. Its layout is
deliberately fixed: a persistent control bar remains visible above the subtitle
content, while the optional Settings panel opens in one reusable `Toplevel`.
The main bar always exposes Start/Stop, Pinned/Unpinned, Settings, and Exit.
Settings only shows or hides the settings panel; right-click is a shortcut to
the same action. The earlier compact, expanded, and captions-only modes have
been removed.

`live-overlay` Settings also provides a **Microphone input** selector backed by
the existing PortAudio discovery layer. `System default` stores `None` and is
resolved again when each new session starts; `--device N` supplies only the
initial GUI choice. Refresh re-enumerates input-capable endpoints and preserves
an explicit choice by device index. The selector and Refresh button are disabled
while preparing, listening, stopping, or closing. Stop the current session,
choose a device, and Start again to apply it. Selection is process-local: there
is no mid-session hot switching or cross-restart persistence. `overlay-demo`
does not show this selector and remains model-free and microphone-free.

**GUI overlay prototype accepted for packaging evaluation.** This status is
based on the documented user interaction/PowerPoint acceptance and real offline
60/120-second microphone validation. It does not mean production ready.

This is a **VAD 分段后调用短音频离线 ASR 的近实时终端字幕原型**. GigaAM is
called only after VAD closes a segment and receives a temporary WAV; it is not
native streaming ASR.

`live-vad` uses `sounddevice.InputStream` with exactly 512 samples per 32 ms
block. Its PortAudio callback only validates, copies, timestamps, and attempts a
non-blocking queue write. A single worker owns the stateful VAD and segmenter.
Queue overflow, input overflow, and sequence gaps are fatal diagnostic errors;
the command never silently discards audio.

Silero VAD 6.2.1 is obtained from its official PyPI wheel by `vad-prepare`.
The project does not install or execute the `silero-vad` package and does not
use TorchAudio for VAD. It extracts the pinned official ONNX file after wheel and
model SHA-256 checks, then runs it with NumPy and CPU ONNX Runtime. The model and
MIT license are stored only in a per-user cache outside the repository.

NLLB (`facebook/nllb-200-distilled-600M`) is the current default
general-purpose candidate because its outputs were relatively natural on the
project's general lecture and operating-instruction samples. It is not a final
model choice. T5 and M2M100 remain available through CLI overrides and their
comparison results are retained as research history.

Mathematical terminology optimization is not a core acceptance requirement for
this project. The current milestone does not implement native streaming ASR,
PowerPoint integration, system-audio capture, or production distribution. A
PyInstaller onedir feasibility spike now packages the existing GUI and CLI on
the development machine; it is not an installer or a portable release.

NLLB is licensed CC-BY-NC-4.0. It is used here only as a learning, research, and
non-commercial candidate; licensing and model suitability must be reviewed
before any broader or commercial use.

## Install on Windows PowerShell

Python 3.10–3.14 is supported; Python 3.11 is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[asr-multilingual,dev,translation]"
```

The official Large CTC snapshot requires matching Torch 2.10.x and TorchAudio
2.10.x builds plus Transformers 5.x. The commands above install the required
official CPU wheels before the editable project.

If PowerShell policy prevents activation, call
`.\.venv\Scripts\python.exe` directly. Do not install project dependencies
globally.

## Commands

Both `python -m live_subtitles` and the `live-subtitles` console command expose
the same interface.

```powershell
python -m live_subtitles --help
python -m live_subtitles doctor
python -m live_subtitles devices
python -m live_subtitles record --seconds 8 --output data/sample.wav
python -m live_subtitles vad-prepare
python -m live_subtitles vad-doctor
python -m live_subtitles vad-file data/sample.wav
python -m live_subtitles live-vad --device 1 --duration 60
python -m live_subtitles live-vad --device 1 --duration 60 --output-dir data/live-vad-segments
python -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cpu --num-beams 1
python -m live_subtitles overlay-demo --duration 0
python -m live_subtitles live-overlay --device 1 --duration 0 --translation-engine nllb --translation-device cpu --num-beams 1
python -m live_subtitles transcribe-file data/sample.wav
python -m live_subtitles translate-audio data/sample.wav
python -m live_subtitles translation-doctor
python -m live_subtitles translate-text "Здравствуйте."
python -m live_subtitles benchmark-translation benchmarks/translation_samples.json --device cpu
```

`translate-audio` defaults to `gigaam_multilingual_large_ctc` using the immutable
`ai-sage/GigaAM-Multilingual` `large_ctc` snapshot on `cpu`, NLLB translation,
`device=cpu`, and one beam. This migration and its supported execution path are
CPU-only. T5 and M2M100 compatibility can be checked with
`--translation-engine t5` or `--translation-engine m2m100`.

`vad-file` accepts only uncompressed PCM16, mono, 16 kHz WAV files. It reports
segment boundaries and per-chunk timing without writing files by default. Use
`--output-dir data/vad-segments` only when ignored diagnostic WAV segments are
needed; do not commit them.

Run `vad-doctor` and `devices` before `live-vad`. The selected microphone must
natively accept mono float32 at 16 kHz; this command does not resample. Duration
`0` runs until Ctrl+C. The default bounded queue contains 320 blocks (10.24
seconds). Segment audio is not written unless `--output-dir` is supplied; when
enabled, each run gets a unique session subdirectory containing PCM16 mono 16 kHz
WAV files. `--show-probabilities` is a verbose diagnostic switch and should not
be used for normal latency measurements.

`live-terminal` uses the same exact microphone and VAD contract. Before opening
the microphone it validates the cached VAD asset/device, creates one Silero ONNX
session, and preloads one GigaAM recognizer plus one selected translator. The
default complete-segment queue holds eight segments and accepts 1 through 32.
Queue full is fatal because losing a complete utterance would make subtitles
misleading. `--show-russian` and `--show-metrics` are enabled by default; use
their `--no-...` forms to disable them. Duration `0` runs until Ctrl+C.

## Cached offline use

Download/stage models separately before running the application. The Large CTC
backend resolves only the pinned commit, forces Hugging Face/Transformers offline
mode, and calls `from_pretrained(..., local_files_only=True)`; it never downloads
at runtime. After both ASR and translation snapshots are staged, verify a complete
cache-only run in the current PowerShell session:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cpu --num-beams 1
python -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cpu --num-beams 1
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

The new Large CTC ASR backend accepts only `cpu`, and translation defaults to
CPU as well. Historical explicit GPU code is not part of this migration's
supported or validated path. Audio
and recognized text stay in the local process. The `.venv`, `data`, WAV files,
model caches, weights, and generated benchmark output are ignored by Git and
must not be committed.

After one successful `vad-prepare`, `vad-doctor`, `vad-file`, and `live-vad` use
only the verified local VAD cache and never access the network.

## Windows CPU-only packaging

Development version 0.3.0 uses the isolated `.venv-packaging-cpu` environment and
`packaging/combined_cpu.spec` to create one shared two-launcher CPU onedir.
It pins official Torch/TorchAudio 2.10.0 CPU wheels and contains no CUDA runtime
or model weights. The onedir is combined with a separately verified Silero,
GigaAM Large CTC and NLLB bundle only at installer build time. No GPU package is
part of the 0.3.0 delivery. See `packaging/README.md`.

## Limitations and troubleshooting

- `live-vad` remains a segmentation-only diagnostic; `live-terminal` performs
  ordered RU/ZH terminal output after each completed VAD segment.
- `live-terminal` is near-real-time at the segment boundary, not native
  streaming GigaAM decoding.
- A queue overflow, input overflow, or sequence discontinuity stops the session;
  use the printed summary to diagnose device/host load rather than accepting loss.
- Recording depends on Windows microphone permission and a free input device.
- The default GigaAM Large CTC backend uses official PyTorch/Transformers code;
  the former RNNT/ONNX backend remains available only by explicit legacy choice.
- Cache-only mode fails if either model snapshot is incomplete.
- NLLB is a current candidate, not a quality guarantee or production approval.
- Run `vad-doctor`, `doctor`, and `translation-doctor` for the corresponding
  model, runtime, device, or cache checks.
- `overlay-demo` opens no microphone and loads no model; it is the safe command
  for checking Settings, borderless/windowed resizing, complete long subtitles,
  stable-window latest-entry font fitting, scrollable history, topmost,
  fonts, opacity, position, Start/Stop, and Exit behavior.
- Closing the settings panel withdraws it without stopping the session. Switching
  borderless mode keeps the same root, controls, subtitle state, and session.
- The user accepted the interaction checks and PowerPoint slide-show behavior.
  Acrobat checks were explicitly waived because Acrobat is not installed on the
  validation machine; the overlay is not an Acrobat or PowerPoint plugin.
- The GUI is not click-through, production ready, signed, or claimed to reserve
  Windows work area. The onedir spike is validated only on its development
  machine and does not persist subtitle history across application restarts.

See [architecture](docs/architecture.md),
[documentation map](docs/README.md),
[repository layout](docs/repository-layout.md),
[development notes](docs/development.md),
[pipeline validation](docs/offline-audio-translation-pipeline.md), and the
[translation comparison](docs/translation-model-comparison.md). Direct VAD
design and measurements are in
[direct Silero ONNX VAD](docs/direct-silero-onnx-vad.md); the live capture design
and operational checks are in
[live microphone VAD](docs/live-microphone-vad.md).
The integrated terminal prototype, latency definitions, and guided offline
validation are in [live terminal subtitles](docs/live-terminal-subtitles.md).
The overlay lifecycle, controls, crash analysis, and remaining manual checks are
in [always-on-top subtitle overlay](docs/always-on-top-subtitle-overlay.md).
The shared console/GUI onedir design, exact size evidence, DLL sampling, PE
closure, pruning experiments, and final offline measurements are in
[Windows onedir size optimization](docs/windows-package-size-optimization.md).
The network-disabled Windows Sandbox staging boundary, exact local-only cache
allowlist, generated configuration workflow, and current host-edition blocker
are in [Windows Sandbox clean-machine validation](docs/windows-sandbox-clean-machine-validation.md).

The 0.3.0 installer candidate combines the CPU-only onedir with exactly
4,826,649,490 bytes of pinned Silero, official GigaAM Multilingual Large CTC and
NLLB assets. It excludes legacy RNNT weights. It requires no Python,
administrator access, network connection, token, or manual model copy and
installs the application under
`%LOCALAPPDATA%\Programs\RuZhLiveSubtitles` and models under
`%LOCALAPPDATA%\ru-zh-live-subtitles\models`. Installed shortcuts use CPU,
offline, no-auto-start mode; first launch does not download anything.

The new delivery is generated separately in `dist\installer-offline-0.3.0`.
Every attachment must remain below 2,000,000,000 bytes, so the build uses native
Inno disk spanning with slices no larger than 1,900,000,000 bytes when required.
At least 12 GiB of free disk space and 8 GiB RAM are required; 16 GiB RAM is
recommended. Uninstall removes the app, shortcuts, managed offline models,
logs, caches, and all other data in the fixed application-owned
`%LOCALAPPDATA%\ru-zh-live-subtitles` directory. The installer is unsigned and may trigger
SmartScreen. Initial frozen model-load timing is recorded from the final
development-machine installation rather than estimated. See
[self-contained offline installer](docs/self-contained-offline-installer.md).

The clean-machine validation kit is under `packaging/clean_machine/`. Generated
packages, model staging, machine-specific `.wsb` files, WAVs, logs, manifests,
and results remain in ignored `data/clean-machine-validation/`. Windows Sandbox
is still unavailable on the Windows 11 Home development host, but the separate
CPU-only package has now completed offline file and live-GUI validation twice
in a network-disabled VMware Windows 11 Pro guest restored from the same clean
snapshot. See [CPU-only clean-machine recovery validation](docs/cpu-clean-machine-recovery-validation.md).

The GPU spec remains an internal historical artifact; it is not built or
distributed in this 0.3.0 stage. The earlier CPU clean-VMware result predates
the Large CTC installer revision. Version 0.3.0 is an unsigned development-machine
course candidate and is not published as a Release in this stage. Model
weights remain outside the CPU onedir but are included in the offline installer
payload. NLLB remains restricted to non-commercial use. The older roughly
216 MB model-less setup is a historical development artifact and must not be
delivered by itself. The existing 0.1.0 RNNT and public 0.2.0 Large CTC
installers, tags, and GitHub Releases remain unchanged. See
[CPU-only distribution policy](docs/cpu-only-distribution.md) and
[installer validation](docs/cpu-only-installer-validation.md).
