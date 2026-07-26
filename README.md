# Russian–Chinese Live Subtitles

An offline-first Windows application for Russian lecture subtitles. This spike
establishes the audio and speech-recognition baseline with Sber's GigaAM-v3 E2E
RNN-T model through ONNX Runtime.

## Current scope

The current implementation records short mono WAV files and recognizes Russian
speech from a local WAV file. It is a file-transcription prototype, not streaming
ASR. Chinese translation, continuous microphone recognition, VAD, subtitles,
GUI, PowerPoint overlays, and Windows packaging have not been implemented.

## Install on Windows PowerShell

Python 3.10–3.14 is supported; Python 3.11 is recommended.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
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

The `.venv`, `data`, model/cache directories, WAV files, and model weights are
ignored by Git and must not be committed.

## Limitations and troubleshooting

- Only short WAV files (up to the model's practical 20–30 second limit) are in scope.
- The supported baseline provider is `CPUExecutionProvider`.
- Recording depends on Windows microphone permissions and a free input device.
- Model download depends on Hugging Face availability during the first run.
- Run `python -m live_subtitles doctor` first when setup or device detection fails.

See [development notes](docs/development.md) for verified environment details and
[architecture](docs/architecture.md) for component boundaries and future work.
