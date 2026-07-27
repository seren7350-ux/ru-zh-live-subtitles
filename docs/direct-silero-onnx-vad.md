# Direct Silero ONNX VAD foundation

## Decision and provenance

The project uses the default non-quantized ONNX model from the official Silero
VAD 6.2.1 PyPI wheel without installing or executing that wheel. The original
dependency plan would have installed TorchAudio 2.11.0 beside the existing
`torch 2.12.1+cu130`. Official TorchAudio guidance requires matching Torch and
TorchAudio release lines, while changing the working CUDA Torch environment was
explicitly out of scope. Direct ONNX inference avoids that conflict.

- Package: `silero-vad 6.2.1`.
- Wheel: `silero_vad-6.2.1-py3-none-any.whl`.
- Wheel size: 9,146,242 bytes.
- Wheel SHA-256: `09de93c4d874bb19c53e62a47dd38be5f163cedad2b5599583231f2a84ef79cb`.
- Selected member: `silero_vad/data/silero_vad.onnx`.
- Model size: 2,327,524 bytes.
- Model SHA-256: `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3`.
- License member: `silero_vad-6.2.1.dist-info/licenses/LICENSE` (MIT).
- Source: official `files.pythonhosted.org` release URL pinned in code.

The wheel also contains `silero_vad_16k_op15.onnx`, `silero_vad_half.onnx`, and
`silero_vad_op18_ifless.onnx`. The wheel's own `model.py` selects
`silero_vad.onnx` for the default `load_silero_vad(onnx=True, opset_version=16)`
path, so the project does not guess among variants.

## Preparation and cache

`vad-prepare` downloads the wheel into a temporary directory, verifies the
wheel digest, reads only the selected model and license ZIP members, verifies
the model size and digest, and atomically writes:

```text
%LOCALAPPDATA%\ru-zh-live-subtitles\models\silero-vad\6.2.1\
  silero_vad.onnx
  LICENSE
  metadata.json
```

If `LOCALAPPDATA` is unavailable, the fallback is
`~/.cache/ru-zh-live-subtitles/models/silero-vad/6.2.1`. An existing verified
cache returns without opening a network connection. A digest mismatch is
rejected rather than silently replaced. Wheel, model, license copy, metadata,
inspection artifacts, source WAVs, and generated segments are outside Git.

## Direct ONNX state handling

The observed model metadata is:

| Direction | Name | Shape | Type |
| --- | --- | --- | --- |
| Input | `input` | `[None, None]` | `tensor(float)` |
| Input | `state` | `[2, None, 128]` | `tensor(float)` |
| Input | `sr` | `[]` | `tensor(int64)` |
| Output | `output` | `[None, 1]` | `tensor(float)` |
| Output | `stateN` | `[None, None, None]` | `tensor(float)` |

At 16 kHz, each call accepts exactly 512 float32 samples. The wrapper prepends
the previous 64 samples, supplies scalar `sr=16000`, and carries the returned
`(2, 1, 128)` float32 state into the next call. `reset()` zeros both state and
context for a new stream. The ONNX Runtime session is lazy, CPU-only, and created
at most once per wrapper. Inputs containing the wrong shape/dtype, non-finite
values, or samples outside `[-1, 1]` are rejected.

## Segmentation

Defaults are threshold 0.5, negative threshold 0.35, 600 ms ending silence,
100 ms speech padding, 250 ms pre-roll, 300 ms minimum speech, and a 15-second
maximum segment. The middle probability band preserves the active state to avoid
threshold chatter. End-of-input flushes the final valid segment. File input is
strictly uncompressed PCM16, mono, 16 kHz; resampling is intentionally absent.

## Real cached/offline validation

After preparation, an invalid local HTTP/HTTPS proxy was set while rerunning
`vad-prepare`, `vad-doctor`, and all `vad-file` commands. The cache was verified
without download, demonstrating that the doctor and file path do not need
network access.

| File | Audio | Segments | Boundaries | Avg/chunk | P95/chunk |
| --- | ---: | ---: | --- | ---: | ---: |
| `sample-retry.wav` | 8.000 s / 250 chunks | 1 | 3.174–7.716 s | 0.122 ms | 0.156 ms |
| `lecture-sample.wav` | 10.000 s / 313 chunks | 1 | 1.894–7.364 s | 0.130 ms | 0.206 ms |
| `vad-two-utterances.wav` | 13.012 s / 407 chunks | 2 | 0.998–5.540 s; 6.470–12.036 s | 0.130 ms | 0.198 ms |

The third ignored test file contains one second of silence, the detected speech
from the first real user recording, one second of silence, the detected speech
from the second real recording, and a final second of silence. It detected two
ordered segments, did not preserve the long inter-segment silence, reported no
short ignored segments, and wrote no output WAVs by default.

## Limitations and next step

This milestone performs file segmentation only. It does not open a microphone,
call GigaAM, translate text, or display subtitles. Segment boundaries are VAD
decisions rather than transcript-aware cuts. The next step is a bounded-queue
microphone pipeline that reuses this stateful wrapper and separately preloaded
ASR/translation models.
