# Russian–Chinese Live Subtitles

An offline-first Windows prototype for Russian lecture subtitles. The current
milestone accepts local WAV files for two independent workflows: direct Silero
ONNX speech segmentation, and short-file GigaAM recognition plus offline
Russian-to-Chinese translation.

## Current scope

The complete short-file path is now:

```text
WAV -> GigaAM ASR -> Russian text -> NLLB translation -> Chinese text
```

The VAD foundation is separate and currently stops after segmentation:

```text
PCM16 mono 16 kHz WAV -> 512-sample chunks -> Silero ONNX probabilities -> speech segments
```

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
this project. The current milestone does not implement microphone VAD,
continuous recognition, streaming ASR, VAD-to-GigaAM integration, live subtitle
state, Chinese subtitle display, GUI, PowerPoint overlays, or Windows packaging.

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

## Cached offline use

The first use of each model needs network access unless its files are already in
the Hugging Face cache. After both models have loaded successfully, force a
complete cache-only run in the current PowerShell session:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cuda --num-beams 1
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

The ASR path remains CPU-only in this milestone; translation can use CUDA. Audio
and recognized text stay in the local process. The `.venv`, `data`, WAV files,
model caches, weights, and generated benchmark output are ignored by Git and
must not be committed.

After one successful `vad-prepare`, both `vad-doctor` and `vad-file` use only the
verified local VAD cache and never access the network.

## Limitations and troubleshooting

- Only short, local WAV files are supported; this is not a live subtitle loop.
- VAD currently segments files only and is not connected to GigaAM or a microphone.
- Recording depends on Windows microphone permission and a free input device.
- GigaAM uses CPU ONNX Runtime; NLLB CUDA needs a compatible PyTorch wheel.
- Cache-only mode fails if either model snapshot is incomplete.
- NLLB is a current candidate, not a quality guarantee or production approval.
- Run `vad-doctor`, `doctor`, and `translation-doctor` for the corresponding
  model, runtime, device, or cache checks.

See [architecture](docs/architecture.md),
[development notes](docs/development.md),
[pipeline validation](docs/offline-audio-translation-pipeline.md), and the
[translation comparison](docs/translation-model-comparison.md). Direct VAD
design and measurements are in
[direct Silero ONNX VAD](docs/direct-silero-onnx-vad.md).
