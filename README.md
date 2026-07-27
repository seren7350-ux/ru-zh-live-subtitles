# Russian–Chinese Live Subtitles

An offline-first Windows prototype for Russian lecture subtitles. The current
milestone connects cached Silero VAD, GigaAM short-WAV recognition, and NLLB
translation in an ordered terminal subtitle loop.

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
pipeline. Its layout is deliberately fixed: a persistent control bar remains
visible above the subtitle content, while the optional Settings panel opens in
one reusable `Toplevel`. The main bar always exposes Start/Stop, Pinned/Unpinned,
Settings, and Exit. Settings only shows or hides the settings panel; right-click
is a shortcut to the same action. The earlier compact, expanded, and
captions-only modes have been removed.

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
depend on TorchAudio. It extracts the pinned official ONNX file after wheel and
model SHA-256 checks, then runs it with NumPy and CPU ONNX Runtime. The model and
MIT license are stored only in a per-user cache outside the repository.

NLLB (`facebook/nllb-200-distilled-600M`) is the current default
general-purpose candidate because its outputs were relatively natural on the
project's general lecture and operating-instruction samples. It is not a final
model choice. T5 and M2M100 remain available through CLI overrides and their
comparison results are retained as research history.

Mathematical terminology optimization is not a core acceptance requirement for
this project. The current milestone does not implement native streaming ASR,
GUI subtitle state, PowerPoint overlays, system-audio capture, resampling, or
Windows packaging.

NLLB is licensed CC-BY-NC-4.0. It is used here only as a learning, research, and
non-commercial candidate; licensing and model suitability must be reviewed
before any broader or commercial use.

## Install on Windows PowerShell

Python 3.10–3.14 is supported; Python 3.11 is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,translation]"
```

Translation requires a compatible PyTorch installation. Select the official
PyTorch command for the machine's NVIDIA driver and install it in `.venv`. This
machine was verified with the CUDA 13.0 wheel:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cu130
```

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
python -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cuda --num-beams 1
python -m live_subtitles overlay-demo --duration 0
python -m live_subtitles live-overlay --device 1 --duration 0 --translation-engine nllb --translation-device cuda --num-beams 1
python -m live_subtitles transcribe-file data/sample.wav
python -m live_subtitles translate-audio data/sample.wav
python -m live_subtitles translation-doctor
python -m live_subtitles translate-text "Здравствуйте."
python -m live_subtitles benchmark-translation benchmarks/translation_samples.json --device cuda
```

`translate-audio` defaults to GigaAM on `CPUExecutionProvider`, NLLB translation,
`device=auto`, and one beam. `auto` prefers CUDA when PyTorch reports it available
and otherwise uses CPU. An explicit `--device cuda` request fails instead of
silently falling back. T5 and M2M100 compatibility can be checked with
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

The first use of each model needs network access unless its files are already in
the Hugging Face cache. After both models have loaded successfully, force a
complete cache-only run in the current PowerShell session:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cuda --num-beams 1
python -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cuda --num-beams 1
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

The ASR path remains CPU-only in this milestone; translation can use CUDA. Audio
and recognized text stay in the local process. The `.venv`, `data`, WAV files,
model caches, weights, and generated benchmark output are ignored by Git and
must not be committed.

After one successful `vad-prepare`, `vad-doctor`, `vad-file`, and `live-vad` use
only the verified local VAD cache and never access the network.

## Limitations and troubleshooting

- `live-vad` remains a segmentation-only diagnostic; `live-terminal` performs
  ordered RU/ZH terminal output after each completed VAD segment.
- `live-terminal` is near-real-time at the segment boundary, not native
  streaming GigaAM decoding.
- A queue overflow, input overflow, or sequence discontinuity stops the session;
  use the printed summary to diagnose device/host load rather than accepting loss.
- Recording depends on Windows microphone permission and a free input device.
- GigaAM uses CPU ONNX Runtime; NLLB CUDA needs a compatible PyTorch wheel.
- Cache-only mode fails if either model snapshot is incomplete.
- NLLB is a current candidate, not a quality guarantee or production approval.
- Run `vad-doctor`, `doctor`, and `translation-doctor` for the corresponding
  model, runtime, device, or cache checks.
- `overlay-demo` opens no microphone and loads no model; it is the safe command
  for checking Settings, borderless/windowed, topmost, fonts, opacity, position,
  Start/Stop, and Exit behavior.
- Closing the settings panel withdraws it without stopping the session. Switching
  borderless mode keeps the same root, controls, subtitle state, and session.
- PowerPoint and Acrobat compatibility still require user validation. The GUI
  is not finally accepted, packaged, or claimed to reserve Windows work area.

See [architecture](docs/architecture.md),
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
