# Live microphone VAD

## Scope

`live-vad` is a terminal-only diagnostic that connects one microphone stream to
the existing direct Silero 6.2.1 ONNX wrapper and `VadSegmenter`. It reports
speech boundaries and infrastructure/performance metrics. It does not invoke
GigaAM, any translation model, a subtitle state machine, or a GUI. It is not
native streaming ASR.

The path is intentionally fixed:

```text
sounddevice.InputStream
  -> mono float32, 16 kHz, exactly 512 samples / 32 ms
  -> immutable numbered AudioBlock
  -> bounded FIFO queue (default 320 blocks / 10.24 seconds)
  -> one worker and one stateful Silero ONNX CPU session
  -> existing probability-driven VadSegmenter
  -> terminal boundary events and optional diagnostic PCM16 WAVs
```

There is no resampling or channel mixing. The selected input must natively
support the required format, checked before the microphone is opened.

## Callback and backpressure contract

The PortAudio callback may only validate the delivered frame count and array,
copy the mono channel into an immutable `AudioBlock`, attach its sequence and
timestamps, and call `put_nowait`. It never performs VAD, disk I/O, terminal I/O,
or a blocking queue operation.

Both block timestamps use `time.perf_counter`. `ended_at` is the software-side
callback receipt time and `started_at` is approximated as `ended_at - 512/16000`.
They provide one monotonic local timeline but are not hardware timestamps. The
implementation never mixes PortAudio `inputBufferAdcTime` with perf-counter
values.

The queue is bounded. If it is full, the callback increments `dropped_blocks`,
records a fatal continuity error, and asks the session to stop. PortAudio input
overflow is also fatal. Status events and their text are retained in the final
summary. The worker verifies every sequence number before inference, so a gap
cannot be silently accepted.

One worker owns the VAD recurrent state and segmenter. It prepares the model
once per session, resets state at the start and end, consumes blocks in FIFO
order, and flushes the segmenter on a normal timed/Ctrl+C stop. Exceptions are
reported to the coordinator. The coordinator closes the input stream, sends the
worker stop marker after capture has ended, waits with a finite join timeout, and
reports whether both resources exited cleanly.

## Commands

```powershell
python -m live_subtitles vad-doctor
python -m live_subtitles devices
python -m live_subtitles live-vad --device 1 --duration 60
python -m live_subtitles live-vad --device 1 --duration 60 --audio-queue-size 320
python -m live_subtitles live-vad --device 1 --duration 60 --output-dir data/live-vad-segments
```

Duration `0` means run until Ctrl+C. Queue size is limited to 16 through 2,000
blocks. Segmentation controls are `--threshold`, `--negative-threshold`,
`--min-silence-ms`, `--speech-pad-ms`, `--pre-roll-ms`, `--min-segment-ms`, and
`--max-segment-seconds`. `--show-probabilities` prints one line per block from
the worker thread and is intended only for diagnosis.

By default no audio is saved. If `--output-dir` is supplied, the main thread
creates a unique session subdirectory after the worker exits and atomically
writes each immutable segment as mono, 16 kHz, PCM16 WAV. Saving never occurs in
the PortAudio callback or VAD worker. `data/` and WAV files remain ignored.

## Summary and acceptance signals

The final summary includes captured and processed blocks, total processed audio,
dropped blocks, sequence gaps, queue capacity/high-water/final depth, PortAudio
status count and text, segment/forced/ignored/save counts, session and model-load
times, inference total/average/median/P95/maximum, queue-wait
average/median/P95/maximum, ONNX session creation count, and explicit worker and
microphone cleanup states.

Totals, counts, and the all-session maximum are accumulated online. Median and
P95 use a fixed rolling window capped at 8,192 blocks (about 4.37 minutes), so an
indefinite Ctrl+C session does not grow metric memory without bound. Both real
60/120-second validations fit entirely inside that window.

A healthy run has zero dropped blocks, zero sequence gaps, zero PortAudio input
overflow, one ONNX session creation, a stable queue well below capacity, and
both cleanup flags set to `yes`. The real validation target for this Windows CPU
baseline is VAD P95 below 5 ms per 32 ms block.

## Tests

Unit tests use fake input devices, streams, callback blocks, status flags, and
VAD probabilities. They do not open a real microphone, access the network, or
load model weights. Tests cover exact stream settings, immutable copying,
Unicode device names, queue and input overflow, sequence gaps, worker failures,
Ctrl+C/timed cleanup, session reuse constraints, strict WAV saving, and default
zero-output behavior.

## Real validation on 2026-07-27

The cached `vad-doctor` check passed before capture. Device discovery identified
device 1 as `麦克风 (HyperX Cloud III)`, and `check_input_settings` accepted native
mono float32 at 16 kHz. Both runs used default segmentation parameters, the
verified cached model at `%LOCALAPPDATA%`, and one `CPUExecutionProvider`
session. Neither live run invoked ASR or translation.

### 60-second segmentation and boundary check

The timed session lasted 60.032 seconds and processed 1,874 blocks / 59.968
seconds of audio. Five prompted sentences produced five non-forced segments:

| Segment | Start | End | Duration | Samples | Saved signal (peak / RMS) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 5.126 s | 9.252 s | 4.126 s | 66,016 | 1,247 / 152.20 |
| 2 | 12.678 s | 15.620 s | 2.942 s | 47,072 | 1,302 / 171.84 |
| 3 | 18.918 s | 22.372 s | 3.454 s | 55,264 | 1,155 / 123.75 |
| 4 | 26.470 s | 31.044 s | 4.574 s | 73,184 | 872 / 103.31 |
| 5 | 35.238 s | 37.732 s | 2.494 s | 39,904 | 1,483 / 171.47 |

All five files were mono, 16 kHz, PCM16 and were written under one ignored unique
session directory. With `HF_HUB_OFFLINE=1`, the existing independent
`transcribe-file` command returned, in order:

1. `Здравствуйте. Сегодня мы начинаем новую лекцию.`
2. `Сначала рассмотрим основную идею.`
3. `Затем приведём несколько простых примеров.`
4. `Если возникнут вопросы, мы обсудим их после занятия.`
5. `Перейдём к следующему слайду.`

This exactly matches the prompted sentences, providing objective evidence of no
obvious lost beginnings/endings, merged sentences, or split sentences. ASR was
run only after capture on saved files and is not integrated into `live-vad`.

The queue high-water mark was 1/320; dropped blocks, sequence gaps, PortAudio
status events, forced segments, ignored short segments, and save failures were
all zero. VAD average was 0.525 ms and P95 was 0.757 ms per block. Model load was
0.108486 seconds, the session creation count was one, and both the worker and
microphone exited cleanly.

### 120-second stability check

The no-save session lasted 120.051 seconds and processed all 3,750 captured
blocks / 120.000 seconds of audio. Eight prompted sentences produced eight
non-forced segments:

| Segment | Start | End | Duration |
| ---: | ---: | ---: | ---: |
| 1 | 3.878 s | 7.428 s | 3.550 s |
| 2 | 12.966 s | 16.100 s | 3.134 s |
| 3 | 21.286 s | 23.684 s | 2.398 s |
| 4 | 28.870 s | 32.132 s | 3.262 s |
| 5 | 36.774 s | 40.292 s | 3.518 s |
| 6 | 45.190 s | 48.612 s | 3.422 s |
| 7 | 55.974 s | 60.068 s | 4.094 s |
| 8 | 67.494 s | 70.596 s | 3.102 s |

The queue high-water mark remained 1/320. Dropped blocks, sequence gaps,
PortAudio status events, forced segments, ignored short segments, saved files,
and save failures were all zero. VAD average was 0.476 ms and P95 was 0.694 ms;
the model loaded in 0.115623 seconds and exactly one ONNX session was created.
The worker exited and microphone released normally after the duration elapsed.

The two-process Windows venv process tree was sampled 217 times. Working set was
78.51 MiB initially and 80.08 MiB at the last live sample, with a maximum of
80.08 MiB. The average of the first and last stable 20-sample windows changed
from 78.78 MiB to 80.08 MiB (+1.29 MiB). This small bounded change showed no
obvious runaway growth during the test. The final implementation also caps each
latency percentile window at 8,192 values to prevent indefinite metric growth.

The 60-second expected session directory contains exactly five diagnostic WAVs.
The 120-second and final two-second smoke runs saved no files. All generated
audio remains ignored and outside Git. Every acceptance gate for this phase was
met.
