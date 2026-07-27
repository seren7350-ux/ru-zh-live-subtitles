# Architecture

## Current short-file pipeline

The direct VAD file foundation is independent of ASR and translation:

```text
Strict PCM16 mono 16 kHz WAV
  -> project-owned WAV reader
  -> float32 chunks (512 samples / 32 ms)
  -> official Silero VAD 6.2.1 ONNX model / CPUExecutionProvider
  -> recurrent state + 64-sample context carried between chunks
  -> probability hysteresis and padding state machine
  -> immutable speech segments
```

`vad-prepare` downloads a single pinned official PyPI wheel as data, verifies its
SHA-256, reads only the selected model and license ZIP members, verifies the
model SHA-256, and atomically writes a per-user cache. It does not import or
execute wheel code. The runtime uses NumPy and ONNX Runtime directly; neither
`silero-vad`, TorchAudio, nor Torch participates in VAD inference.

The existing offline audio-to-translation path remains:

```text
Local WAV file
  -> WAV validation and duration reading
  -> GigaAM-v3 E2E RNN-T through onnx-asr / CPU ONNX Runtime
  -> non-empty Russian text check
  -> translator factory (default: NLLB; optional: T5 or M2M100)
  -> direct local Transformers generation
  -> Chinese text
```

ASR and translation remain independent components. The pipeline module only
coordinates their narrow interfaces and combines timing data; it does not copy
model logic. Both wrappers are lazy, so importing the package, displaying help,
or running a doctor command does not load a model. A pipeline instance creates
at most one ASR wrapper and one selected translator, allowing the same loaded
objects to be reused in a future long-running process.

The current commands handle local WAV files. GigaAM remains on CPU,
while translation selects CUDA when `device=auto` and CUDA is available. No
audio or text is sent to a network service. Cache-only operation requires both
Hugging Face offline environment variables and complete local model snapshots.

T5, M2M100, and NLLB are not loaded together. NLLB is the current default
general-purpose candidate, while the other adapters remain selectable for
comparison and compatibility. Mathematical terminology is not a core project
acceptance requirement; earlier comparison failures remain documented as
research observations rather than a pipeline blocker.

## Current live terminal prototype

```text
PortAudio callback
  -> bounded audio queue
  -> one Silero VAD/segmenter worker
  -> immutable AudioSegment
  -> bounded segment queue (default 8, range 1..32)
  -> one serial GigaAM/translation worker
  -> ordered Russian and Chinese terminal results
```

This is a **VAD 分段后调用短音频离线 ASR 的近实时终端字幕原型**. Each segment
is temporarily encoded as mono PCM16 16 kHz WAV in the system temporary
directory, closed before GigaAM reads it, and removed in `finally`. No segment
audio is written under `data/`, and no temporary path is printed.

The ASR/translation worker is the only caller of the reusable preloaded GigaAM
and translator instances. It never processes segments in parallel. Individual
ASR/translation errors produce ordered failed results and do not prevent later
segments. Audio loss, either queue filling, PortAudio overflow, sequence gaps,
worker death, preparation failure, or finite join timeout stops the session.

Both queues use non-blocking producer writes and explicit fatal backpressure;
the PortAudio callback remains unchanged. Percentile windows and retained
subtitle results are capped at 8,192 entries.

## Future target

```text
terminal results -> subtitle state management -> always-on-top GUI
```

The current implementation is not native streaming ASR. GigaAM starts only
after VAD closes a short segment.
ASR, translation, subtitle state, and GUI must remain decoupled so they can be
profiled and replaced independently. Future performance work must report ASR,
translation, and orchestration latency separately as well as end-to-end delay.

## Live capture concurrency boundary

```text
PortAudio callback
  -> immutable sequenced AudioBlock
  -> bounded FIFO queue
  -> single VAD/segmenter worker
  -> immutable AudioSegment results
  -> non-blocking bounded segment queue
  -> serial ASR/translation worker and terminal reporting
```

The callback has a strict real-time boundary: validate, copy, timestamp, and
`put_nowait` only. Queue full, PortAudio input overflow, and sequence gaps are
fatal because continuing would hide missing audio. The worker is the sole owner
of VAD recurrent state and the segmentation state machine. The coordinator owns
stream lifetime, termination, joining, summary generation, and optional writes.
This separation keeps microphone transport independent from future ASR,
translation, subtitle state, and GUI components.
