# Development notes

## Environment survey

- Operating environment: Windows, PowerShell
- Selected Python: `C:\Users\seren\AppData\Local\Programs\Python\Python311\python.exe`
- Selected Python version: `Python 3.11.9` (64-bit)
- Project interpreter: `.venv\Scripts\python.exe`
- pip: `26.1.2`, installed inside `.venv`
- GPU: NVIDIA GeForce RTX 4060 Laptop GPU; NVIDIA-SMI 610.74
- GPU runtime policy: CPU-only `onnxruntime` for this spike
- ffmpeg: `8.1.1-full_build-www.gyan.dev` (detected but not required)

`where.exe python` also reported the Microsoft Store alias under
`WindowsApps`; it was not selected.

## Dependencies

Editable installation completed successfully inside `.venv`. Key versions:

- `pip 26.1.2`
- `onnx-asr 0.12.0`
- `onnxruntime 1.28.0` (CPU package; providers: Azure and CPU)
- `numpy 2.4.6`
- `sounddevice 0.5.5`
- `huggingface-hub 1.24.0`
- `pytest 9.1.1`
- `pytest-cov 7.1.0`

`python -m pip check` reports `No broken requirements found.` No freeze or
lockfile was committed; `pyproject.toml` remains the dependency source.

## Validation commands

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m pytest --cov=live_subtitles --cov-report=term-missing
.\.venv\Scripts\python.exe -m live_subtitles --help
.\.venv\Scripts\python.exe -m live_subtitles doctor
.\.venv\Scripts\python.exe -m live_subtitles devices
.\.venv\Scripts\python.exe -m live_subtitles record --seconds 8 --output data/sample.wav
.\.venv\Scripts\python.exe -m live_subtitles transcribe-file data/sample.wav
```

## Real and offline validation

Validated on 2026-07-26:

- Unit tests: 25 passed in 4.56 seconds (`pytest -v` initial run).
- Coverage: 80% total; 25 passed in 1.12 seconds.
- Doctor: 22 checks, 20 OK, 2 WARN, 0 FAIL.
- Input devices: 15; default input is device 1, `麦克风 (HyperX Cloud III)`.
- Recording: success; mono PCM16, 16 kHz, 8.000 seconds, 128,000 frames,
  256,044 bytes at `data/sample.wav`.
- Recorded peak amplitude: 699/32767 and RMS 60.41; the microphone level was low.
- Model: `gigaam-v3-e2e-rnnt`, provider `CPUExecutionProvider`.
- Model download: success, with five model repository files fetched.
- Model cache: `C:\Users\seren\.cache\huggingface\hub\models--istupakov--gigaam-v3-onnx`.
- Cache observation: 7 files totaling 892,417,061 bytes.
- First model load (including download): 203.925 seconds.
- First recognition: 1.803 seconds for 8.000 seconds of audio; RTF 0.225.
- First recognized text: `Бананья, русская лечи.`
- Offline verification with `HF_HUB_OFFLINE=1`: success.
- UTF-8 offline verification load: 1.899 seconds; recognition: 2.740 seconds;
  RTF 0.343; text: `Бананья, русская лечи.`

The recording did not produce the requested reference sentence accurately. The
low captured level is the main observed quality risk; recognition execution and
offline cache behavior both succeeded.

During the first download, a process spot check showed about 228 MiB working set,
287 MiB peak working set, and about 1.44 GiB private committed memory. No runaway
CPU or memory behavior was observed; this is a spot check, not a full profiler.

## Known warnings

- The first editable-install attempt hit the command runner's 124-second timeout.
  Its remaining project-local pip process was stopped, and one clean retry
  completed successfully. No package downgrade or framework change was made.
- Git warns that LF files may be converted to CRLF by the existing Windows Git
  configuration. Global Git configuration was not changed.
- Hugging Face warned that unauthenticated downloads have lower rate limits. No
  token is needed for this public model and no token was stored.
- Hugging Face symlink caching is unavailable in the current Windows setup, so
  the cache works in a degraded mode that may consume more disk space.
- `CUDAExecutionProvider` is not installed by design; the RTX 4060 was detected,
  but this spike formally validates only CPU inference.
- One offline run displayed Cyrillic as console mojibake through PowerShell's
  native-output encoding. Repeating with temporary UTF-8 console output produced
  the correct Russian display; no translation feature was involved.

Model and audio artifacts remain ignored and outside Git.
