# Russian–Chinese Live Subtitles

An offline-first Windows application for Russian lecture subtitles. This spike
establishes the audio and speech-recognition baseline with Sber's GigaAM-v3 E2E
RNN-T model through ONNX Runtime.

## Current scope

The current implementation records short mono WAV files, recognizes Russian
speech from a local WAV file, and separately translates supplied Russian text to
Chinese with a local T5 experimental baseline. The ASR and translation paths are not connected.
It is not streaming ASR. Continuous microphone recognition, VAD, live subtitle
state, GUI, PowerPoint overlays, and Windows packaging have not been implemented.

The T5 translator is a provisional benchmark model, not an approved final
subtitle model. Its speed and GPU memory usage satisfy the prototype target and
general software instructions are often usable, but its mathematical terminology
contains serious errors. It must not be used for unattended mathematical classroom
subtitles. There is currently no final default translation model; the next stage
compares the T5 baseline with M2M100 and NLLB while keeping ASR and translation
separate.

## Install on Windows PowerShell

Python 3.10–3.14 is supported; Python 3.11 is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Translation uses a separately installed CUDA-enabled PyTorch wheel plus optional
project dependencies. Select the official PyTorch command for the local CUDA
driver, install only `torch`, then install the project extras. The CUDA 13.0
command below is a locally verified example for this machine, not a universal
recommendation for every Windows/NVIDIA computer:

```powershell
python -m pip install torch --index-url https://download.pytorch.org/whl/cu130
python -m pip install -e ".[dev,translation]"
```

If PowerShell policy prevents activation, use the virtual-environment executable
directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Commands

Both `python -m live_subtitles` and the `live-subtitles` console command expose
the same interface.

```powershell
python -m live_subtitles --help
python -m live_subtitles doctor
python -m live_subtitles devices
python -m live_subtitles record --seconds 8 --output data/sample.wav
python -m live_subtitles transcribe-file data/sample.wav
python -m live_subtitles translation-doctor
python -m live_subtitles translate-text "Здравствуйте." --device auto
python -m live_subtitles benchmark-translation benchmarks/translation_samples.json --device cuda
```

`doctor` reports Python, dependency, ONNX Runtime provider, GPU, cache, and audio
device status without loading a model or opening the microphone. `devices` lists
input-capable audio devices. `record` writes mono, 16 kHz, PCM16 WAV audio.

The first `transcribe-file` invocation may need internet access to download
`gigaam-v3-e2e-rnnt` from Hugging Face. After a successful download, repeat the
same command with the cache forced offline:

```powershell
$env:HF_HUB_OFFLINE = "1"
python -m live_subtitles transcribe-file data/sample.wav
Remove-Item Env:HF_HUB_OFFLINE
```

The first `translate-text` invocation likewise downloads
`utrobinmv/t5_translate_en_ru_zh_base_200`. After it is cached, verify translation
without network access:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m live_subtitles translate-text "Модель работает локально." --device auto
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

The `.venv`, `data`, model/cache directories, WAV files, and model weights are
ignored by Git and must not be committed.

## Limitations and troubleshooting

- Only short WAV files (up to the model's practical 20–30 second limit) are in scope.
- The supported baseline provider is `CPUExecutionProvider`.
- Translation is a separate text-only spike and does not consume ASR output yet.
- T5 is an experimental baseline and is not approved for unattended mathematical subtitles.
- There is no final default translation model yet; M2M100 and NLLB are the next comparison targets.
- Translation GPU execution requires a separately installed compatible CUDA PyTorch wheel.
- Recording depends on Windows microphone permissions and a free input device.
- Model download depends on Hugging Face availability during the first run.
- Run `python -m live_subtitles doctor` first when setup or device detection fails.

See [development notes](docs/development.md) for verified environment details and
[architecture](docs/architecture.md) for component boundaries and future work.
