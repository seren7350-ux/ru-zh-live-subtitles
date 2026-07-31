# Live terminal Russian/Chinese subtitles

## Scope

`live-terminal` is a **VAD 分段后调用短音频离线 ASR 的近实时终端字幕原型**.
It is not native streaming ASR: Silero VAD must finish a speech segment before
GigaAM receives a short temporary WAV. There is no GUI, overlay, system-audio
capture, GPU ASR, parallel ASR, or packaging in this milestone.

## Threads and bounded queues

```text
PortAudio callback
  -> audio_queue (bounded, immutable 512-sample blocks, put_nowait)
  -> Silero VAD worker (one stateful session and segmenter)
  -> immutable AudioSegment
  -> segment_queue (bounded, default 8, 1..32, put_nowait)
  -> one ASR/translation worker
  -> ordered RU/ZH terminal results
```

The callback only validates, copies, timestamps, and enqueues audio. The VAD
worker only performs VAD/segmentation. The subtitle worker is the only thread
allowed to call GigaAM or NLLB, and processes exactly one segment at a time.
Queue full is never treated as a drop: it is a fatal infrastructure error and
stops capture.

## Preparation and model reuse

Startup completes in this order before recording:

1. validate the pinned local VAD cache;
2. validate the selected native 16 kHz microphone format;
3. create one Silero ONNX session;
4. create and preload one GigaAM recognizer on `CPUExecutionProvider`;
5. create and preload one selected translator (NLLB by default, CPU device);
6. print `Models ready`;
7. start the subtitle worker, open the microphone, then print `Listening...`.

Every `prepare()` is idempotent. Session summaries expose VAD session, GigaAM
load, tokenizer load, and translator-model load counts; a healthy session shows
one of each.

## Temporary WAV lifecycle

Each immutable float32 segment is clipped and encoded in the system temporary
directory as mono, 16 kHz, little-endian PCM16 WAV. `NamedTemporaryFile` is
closed before the common WAV writer and before GigaAM opens the path, which is
required on Windows. The name contains no speech text. A `finally` block removes
the file after success or any segment-stage failure. Paths are not printed.

## Timing definitions

All event timestamps share one `time.perf_counter` domain and are read at the
event, not reconstructed from stage durations:

- `vad_release_latency = segment_emitted - segment_end`
- `queue_wait = processing_started - queued`
- `RU latency = russian_ready - segment_end`
- `ZH latency = chinese_ready - segment_end`
- `processing RTF = processing_seconds / segment_audio_seconds`

The worker records segment start/end, VAD emission, successful enqueue,
dequeue/processing start, GigaAM return, and translator return. Empty audio does
not divide by zero. Rolling latency windows and retained results are capped at
8,192 samples.

## Offline command

After the three model caches have already been prepared:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
python -m live_subtitles vad-doctor
python -m live_subtitles doctor
python -m live_subtitles translation-doctor
python -m live_subtitles devices
python -m live_subtitles live-terminal --device 1 --duration 60 --translation-engine nllb --translation-device cuda --num-beams 1 --show-russian --show-metrics
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

Wait for both `Models ready` and `Listening...` before speaking. Duration `0`
means Ctrl+C. Both duration expiry and Ctrl+C close the stream, drain the audio
queue, flush VAD, drain the segment queue, delete temporary WAVs, and join both
workers with finite timeouts.

## Real offline validation (2026-07-27)

Both child PowerShell sessions set `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` before Python started and removed them before exit.
Both completed from existing caches with exit code 0. Device 1 was
`麦克风 (HyperX Cloud III)` and accepted the required native format.

### 60 seconds

All five prompted utterances produced one ordered successful subtitle each:

| # | Audio | Queue | ASR | Translation | RTF | RU latency | ZH latency |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 4.126 s | 0.000 s | 0.182 s | 1.257 s | 0.355 | 0.705 s | 1.968 s |
| 2 | 2.942 s | 0.000 s | 0.113 s | 0.490 s | 0.209 | 0.625 s | 1.117 s |
| 3 | 3.358 s | 0.000 s | 0.089 s | 0.453 s | 0.168 | 0.619 s | 1.073 s |
| 4 | 4.574 s | 0.000 s | 0.121 s | 0.492 s | 0.139 | 0.648 s | 1.141 s |
| 5 | 2.494 s | 0.000 s | 0.073 s | 0.480 s | 0.232 | 0.608 s | 1.089 s |

Full output:

1. RU: `Здравствуйте. Сегодня мы начинаем новую лекцию.`
   ZH: `你好,今天我们开始了新的讲座.`
2. RU: `Сначала рассмотрим основную идею.`
   ZH: `首先,让我们来看看一个基本的想法.`
3. RU: `Затем приведём несколько простых примеров.`
   ZH: `然后我们举几个简单的例子.`
4. RU: `Если возникнут вопросы, мы обсудим их после занятия.`
   ZH: `如果有问题,我们会在课后讨论.`
5. RU: `Перейдём к следующему слайду.`
   ZH: `我们再转到下一个幻灯片.`

The 60.023-second session processed 1,874/1,874 blocks. Audio queue HWM was
1/320 and segment queue HWM was 1/8 with final depth 0. Dropped blocks,
sequence gaps, PortAudio statuses, ignored short segments, failed subtitles,
and backlog failures were all zero. VAD P95 was 0.884 ms. Average processing
RTF was 0.220. RU latency average/median/P95 was 0.641/0.625/0.694 seconds;
ZH was 1.278/1.117/1.803 seconds.

VAD/ASR/translator loads were 0.113/1.894/5.473 seconds; outer translation
preparation, including imports and device setup, was 9.171 seconds. VAD session,
ASR model, tokenizer, and translator model counts were all one. CUDA peak
allocation was 1,189.6 MiB. The sampled process-tree working set changed from
5,211.24 to 5,214.66 MiB over 40 samples (maximum 5,214.77 MiB), with no
visible growth trend. Five temporary WAVs were created and deleted; residue was
zero. Both workers exited and the microphone was released.

### 120 seconds

Eight prompted utterances produced eight ordered successful subtitles:

| # | Russian | Chinese |
| ---: | --- | --- |
| 1 | Здравствуйте, мы продолжаем нашу лекцию. | 你好,我们继续讲. |
| 2 | Сегодня поговорим о важной теме. | 今天我们要谈一下一个重要的主题. |
| 3 | Сначала повторим основные понятия. | 首先,我们要重复基本的概念. |
| 4 | Затем рассмотрим практический пример. | 然后我们来看一个实用的例子. |
| 5 | Обратите внимание на этот результат. | 现在,请注意这个结果. |
| 6 | Теперь сделаем короткую паузу. | 现在我们要做一个短暂的休息. |
| 7 | После перерыва ответим на вопросы. | 我们在休息后会回答问题. |
| 8 | В конце подведём итоги занятия. | 我们将在最后总结课程. |

The 120.022-second session processed 3,749/3,749 blocks. Audio/segment queue
HWMs were 1/320 and 1/8; the segment queue ended at zero. All eight subtitles
succeeded. Dropped blocks, sequence gaps, PortAudio statuses, short segments,
and backlog errors were zero. Queue wait average/median/P95 was
0.000/0.000/0.000 seconds. Processing average/median/P95 was
0.665/0.596/1.000 seconds and RTF average/median/P95 was 0.237/0.209/0.365.
RU latency average/median/P95 was 0.610/0.607/0.645 seconds; ZH was
1.174/1.105/1.512 seconds.

VAD/ASR/translator loads were 0.116/2.111/3.928 seconds; every load count was
one. CUDA peak allocation was 1,189.5 MiB. A late process-tree sampling window
started at 5,355.72 MiB and never exceeded 5,355.72 MiB, then fell to
1,183.06 MiB while the Python child exited. The first, heavier full-session CIM
sampler itself timed out and returned no samples, so this is evidence of no
late-session growth rather than a precise start-to-end memory delta. Eight
temporary WAVs were created/deleted with zero residue. Both workers exited and
the microphone was released.

### Acceptance and warnings

The offline, reuse, loss/backpressure, ordering, quality, RTF, RU/ZH latency,
temporary-file, duration-shutdown, and resource-cleanup gates passed. The
automated Ctrl+C path also passed with fake devices/workers. The real runs used
duration shutdown; no second real Ctrl+C capture was needed.

Transformers printed its existing warning that both model `max_length=200` and
CLI `max_new_tokens=256` were present; it used `max_new_tokens`. Under Windows
WDDM, `nvidia-smi --query-compute-apps` reported per-process memory as `N/A`, so
the application-owned PyTorch peak is the authoritative CUDA allocation value.
The visible PowerShell `Tee-Object` wrapper classified native stderr progress as
`NativeCommandError`; this was a wrapper presentation artifact, not an
application error. The pull request remains Draft.

## GUI process boundary and final overlay validation

`live-overlay` reuses the same `LiveTerminalSession` contract and metrics, but
runs each session in one spawned child process so cached model work cannot starve
the Tk parent mainloop. Stop terminates that child cleanly; a later Start creates
a fresh child and reloads each cached model exactly once. This does not change
`live-terminal`, introduce native streaming decoding, or persist audio/text.

On 2026-07-27 the real offline overlay passed a 60-second 5/5 subtitle run, the
Stop → Start → Stop lifecycle, Exit during model preparation, and a final
120-second 11/11 subtitle stability run. All loss/backpressure counters and
temporary residue were zero. Exact GUI, pipeline, memory, CUDA, RU/ZH, and
cleanup evidence is recorded in `always-on-top-subtitle-overlay.md`.
