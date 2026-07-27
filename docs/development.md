# Development notes

## Environment survey

- Operating environment: Windows, PowerShell
- Selected Python: Python.org CPython selected through `py -3.11`
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
- `torch 2.12.1+cu130` (installed separately from the official CUDA 13.0 wheel index)
- `transformers 5.14.1`
- `tokenizers 0.22.2`
- `sentencepiece 0.2.2`
- `safetensors 0.8.0`
- `sacrebleu 2.6.0`

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
.\.venv\Scripts\python.exe -m live_subtitles translate-audio data/sample.wav --translation-engine nllb --device cuda
.\.venv\Scripts\python.exe -m live_subtitles translation-doctor
.\.venv\Scripts\python.exe -m live_subtitles translate-text "Здравствуйте." --device auto
.\.venv\Scripts\python.exe -m live_subtitles benchmark-translation benchmarks/translation_samples.json --device cuda
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
- Model cache: the `models--istupakov--gigaam-v3-onnx` directory under the effective Hugging Face Hub cache.
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

## Translation validation

This section preserves the first T5-only benchmark as historical validation. T5
remains an experimental baseline. The later comparison retained all three
adapters and selected NLLB as the current general-purpose candidate; the
short-file pipeline now connects ASR to the selected translator. NLLB is not a
final model approval.

- Locally verified PyTorch installation command for this machine (not a universal
  Windows/NVIDIA recommendation):
  `.\.venv\Scripts\python.exe -m pip install torch==2.12.1 --index-url https://download.pytorch.org/whl/cu130`
- PyTorch CUDA runtime: 13.0.
- `torch.cuda.is_available()`: true.
- CUDA device: NVIDIA GeForce RTX 4060 Laptop GPU.
- Translation model: `utrobinmv/t5_translate_en_ru_zh_base_200`.
- Model download: successful; cache contains 10 files totaling 1,194,418,014 bytes
  under `models--utrobinmv--t5_translate_en_ru_zh_base_200` in the effective Hub cache.
- First online CUDA load: tokenizer 13.717 seconds, model 188.034 seconds,
  total 201.751 seconds.
- First CUDA translation: 0.654 seconds, float16, peak allocated CUDA memory
  658.6 MiB.
- First source: `Сегодня мы рассмотрим основные свойства линейных операторов.`
- First output: `今天我们来看看线下运营商的特点。`

### GPU benchmark summary

| Setting | Cold load | Warm mean | Median | P95 | Source chars/s | corpus chrF | Peak CUDA |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| beams=1, warmup=2, repeat=3 | 5.969 s | 0.184 s | 0.177 s | 0.269 s | 316.37 | 31.646 | 659.2 MiB |
| beams=4, warmup=2, repeat=3 | 14.706 s | 0.235 s | 0.224 s | 0.363 s | 248.21 | 35.043 | 666.7 MiB |

The higher beam count improved corpus chrF by 3.397 points but increased mean
warm latency by about 28%. chrF is an automatic reference metric and is not a
substitute for human evaluation.

### Actual GPU translations

| # | beams=1 | beams=4 |
| ---: | --- | --- |
| 1 | 這是對俄語辨識的檢查。 | 你好,这是俄罗斯语言识别测试。 |
| 2 | 今天我们来看看线下运营商的特点。 | 今天,我们来看看线性运营商的基本特性。 |
| 3 | 让 X - Banachov空间,A – 有限线性操作员。 | 让 X 是香蕉空间,而 A 是有限的线性运算符。 |
| 4 | 运算符称为紧凑型,如果它将有限的数组转换为前置的集合。 | 运算符称为紧凑型,如果它将有限的数组转换为前置的数组。 |
| 5 | 证明这个任务的存在和唯一性。 | 证明这个任务的存在和唯一性。 |
| 6 | 下面我们来看看,计算一下函数的规则。 | 让我们来看看下面的例子,并计算功能规范。 |
| 7 | 首先启动程序,然后在设置中选择麦克风。 | 首先启动程序,然后在设置中选择麦克风。 |
| 8 | 该模型在本地运行,不会将音频发送到互联网。 | 该模型在本地运行,不会将音频发送到互联网。 |
| 9 | 如果出现错误,请检查设备连接并重复尝试。 | 如果出现错误,请检查设备连接并重复尝试。 |
| 10 | 让我们进入下一个幻灯片。 | 让我们进入下一个幻灯片。 |
| 11 | 理论2.3在中断后得到证实。 | 理论2.3在中断后得到证实。 |
| 12 | 参数值为零,t =0。 | 参数值为零,t = 0。 |

The general software/device sentences are usable, but mathematical terminology
is frequently mistranslated: for example, linear operators become telecom
operators, Banach space becomes `Banachov空间` or `香蕉空间`, and functional norm
becomes `函数的规则` or `功能规范`. The model is therefore not acceptable for
unsupervised mathematical lecture subtitles without terminology adaptation or a
better model.

### CPU benchmark

beams=1 with warmup=1 and repeat=1 completed all 12 sentences: cold load 4.301
seconds, warm mean 0.279 seconds, median 0.267 seconds, P95 0.388 seconds,
208.91 source characters/second, corpus chrF 31.577, and no CUDA allocation.

### Fully offline verification

With both `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, CUDA translation loaded
only from the local cache and succeeded:

- Source: `Модель работает локально и не отправляет аудио в интернет.`
- Output: `该模型在本地运行,不会将音频发送到互联网。`
- Tokenizer load: 1.406 seconds.
- Model load: 0.800 seconds.
- Total load: 2.206 seconds.
- Translation: 0.625 seconds.
- dtype: float16.
- Peak allocated CUDA memory: 658.7 MiB.

## Translation warnings

- The 1.93 GB PyTorch CUDA wheel took about 12 minutes to download. One small
  dependency request timed out after 15 seconds and pip retried successfully.
- Hugging Face warned about unauthenticated rate limits; no token was provided or
  stored.
- Windows lacks cache symlink support in this setup. Caching works in degraded
  mode and may use more disk.
- Transformers reports that `shared.weight` and `lm_head.weight` differ despite
  the checkpoint's tied-weight configuration, so it deliberately does not tie
  them. The code does not mutate the upstream model configuration.

## Final translation-spike validation

- `python -m pip check`: no broken requirements found.
- `python -m pytest -v`: 47 tests passed in 0.44 seconds.
- `python -m pytest --cov=live_subtitles --cov-report=term-missing`: 47 tests
  passed in 0.60 seconds with 79% total coverage.
- Core translation coverage: 90% for `t5_ru_zh.py`, 83% for `benchmark.py`, and
  79% for translation diagnostics.
- The test suite replaces socket connection functions with failures, uses fake
  Torch/Transformers modules, and does not download a model, access the network,
  or require a GPU.
- `git diff --check` completed without whitespace errors.
- `.venv`, Hugging Face/model data, WAV files, generated `data/`, coverage data,
  and Python caches remain ignored and untracked.

## Translation model comparison validation

### Runtime and storage

- Branch base: main squash commit `5dbb8c8` from PR #2.
- Python: 3.11.9 from the project `.venv`.
- Torch: 2.12.1+cu130; Torch CUDA runtime: 13.0.
- CUDA available: true; device: NVIDIA GeForce RTX 4060 Laptop GPU.
- NVIDIA-SMI: 610.74; driver CUDA UMD: 13.3; GPU memory: 8,188 MiB.
- C drive free space before model work: 336,020,766,720 bytes.
- M2M100 revision: `55c2e61bbf05dfb8d7abccdc3fae6fc8512fd636`.
- NLLB revision: `f8d333a098d19b4fd9a8b18f94170487ad3f821d`.
- M2M100 standard snapshot: 1,941,931,012 bytes; whole cache:
  3,877,615,381 bytes.
- NLLB standard snapshot: 2,482,646,304 bytes; whole cache:
  4,943,003,911 bytes.

The user had already downloaded both official standard PyTorch checkpoints. One
M2M100 `vocab.json` read timed out and resumed successfully. Transformers later
fetched automatic safetensors conversion snapshots before the adapter explicitly
set `use_safetensors=False`. Nothing was deleted; final validation and all final
benchmarks use the official standard `pytorch_model.bin` files at the `main`
revisions above.

### Offline validation

With both `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`:

- M2M100: tokenizer 1.619 seconds; model 1.174 seconds; translation 0.568
  seconds; 938.0 MiB peak; output
  `该模型运行本地,不会向互联网发送音频。`.
- NLLB: tokenizer 2.196 seconds; model 2.343 seconds; translation 0.496
  seconds; 1,189.6 MiB peak; output
  `模型是本地运行的,不会发送音频到互联网.`.
- Both commands returned zero and the temporary environment variables were removed.

### Final benchmark conclusion

The same 32-sentence corpus was used in a separate Python process for each
configuration. GPU runs used two warmups and three timed repetitions; CPU runs
used one warmup and one timed repetition. Full tables, category results, all
outputs, severe errors, cache details, and the licensing decision are recorded in
`docs/translation-model-comparison.md`.

All models pass the local GPU P95 and peak-memory limits. None approaches the
historical 85% mathematical terminology threshold: T5 peaks at 13.3%, M2M100 at
8.9%, and NLLB at 8.9%. Those measurements remain useful research evidence, but
mathematical terminology is no longer a core acceptance requirement. NLLB is the
current general-purpose candidate and may be connected to ASR; it is not a final
model selection.

### Comparison warnings and errors

- The first no-network unit-test run had one incorrect fake expected term
  (`译1` instead of the fake translator's actual `译d`); the fixture was corrected
  and all tests passed.
- One benchmark orchestration attempt passed `gpu` to a CLI that correctly
  accepts `cuda`; it exited with code 2 before loading any model. The corrected
  serial run completed all eight configurations.
- Windows Hugging Face caching cannot use symlinks and therefore consumes more disk.
- Transformers reports that `max_new_tokens` takes precedence over the model's
  configured `max_length`; deterministic generation still uses `do_sample=False`.
- Model loading progress is written to stderr by Transformers; no model objects,
  weights, or cache paths are emitted into committed application data.

### Final comparison-branch checks

- `python -m pytest -v`: 57 passed in 0.40 seconds, 10 more collected test
  cases than the merged translation-baseline branch.
- `python -m pytest --cov=live_subtitles --cov-report=term-missing`: 57 passed
  in 0.66 seconds; total coverage 79%.
- Core comparison coverage: benchmark 87%, factory 94%, each Meta adapter 93%,
  shared runtime 80%, and T5 wrapper 91%.
- `python -m pip check`: no broken requirements found.
- CLI help confirms `--engine {t5,m2m100,nllb}` for both single-text translation
  and benchmarking.

## Offline audio-to-translation integration

Validated on 2026-07-27 after PR #3 was squash-merged:

- Branch: `feat/offline-audio-translation-pipeline`.
- Default translation engine: `nllb`.
- Default translation model: `facebook/nllb-200-distilled-600M`.
- Languages: `rus_Cyrl` to `zho_Hans`.
- ASR remains `gigaam-v3-e2e-rnnt` on `CPUExecutionProvider`.
- Translation device mode defaults to `auto`, which selected CUDA on this host;
  explicit CUDA requests do not fall back.
- Unit tests after integration: 70 passed in 0.45 seconds, with socket access
  blocked and all model and microphone interactions replaced by fakes.

The first real pipeline run used both `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, so both models loaded from local caches:

- File: `data/sample-retry.wav`; duration: 8.000 seconds.
- Russian: `Здравствуйте. Это проверка распознавания русской речи.`
- Chinese: `你好,这是一个俄罗斯语识别检查.`
- ASR load: 2.377 seconds; ASR recognition: 2.453 seconds.
- NLLB load: 4.383 seconds; translation: 0.609 seconds.
- Total: 12.481 seconds; end-to-end RTF: 1.560.
- Translation runtime: CUDA float16; peak allocation: 1,189.6 MiB.
- CPU offload: none configured or observed. ASR running on CPU is intentional
  and separate from translation offload.

The second fully offline run used a newly recorded ordinary lecture sample:

- WAV: mono PCM16, 16 kHz, 160,000 frames, 10.000 seconds, 320,044 bytes.
- Signal: peak 1,249/32,767; RMS 142.49/32,767; not near silence.
- Russian: `Сегодня мы рассмотрим новую тему и приведём несколько простых примеров.`
- Chinese: `今天我们将讨论一个新的主题,并举出一些简单的例子.`
- ASR load: 2.127 seconds; recognition: 2.792 seconds.
- NLLB load: 4.433 seconds; translation: 0.652 seconds.
- Total: 12.797 seconds; end-to-end RTF: 1.280.
- CUDA float16 peak allocation: 1,189.8 MiB; no CPU offload was configured or
  observed.
- Both offline flags were removed from the PowerShell session after the command.

Final integration checks: 70 tests passed in 0.45 seconds; the coverage run
passed all 70 tests in 0.78 seconds with 80% total coverage and 90% coverage for
`pipeline/offline_file.py`. `python -m pip check` reported no broken
requirements.

Transformers warned that the model's configured `max_length=200` and the CLI's
`max_new_tokens=256` were both present. It explicitly used `max_new_tokens`;
generation remained deterministic. See `offline-audio-translation-pipeline.md`
for the complete file-pipeline record.

## Direct Silero ONNX VAD validation

Validated on 2026-07-27 on `feat/live-vad-terminal-pipeline`:

- The proposed `silero-vad[onnx-cpu]==6.2.1` install was not performed because
  it would add TorchAudio 2.11.0 beside Torch 2.12.1+cu130. TorchAudio requires
  matching release lines, and the working CUDA Torch environment was preserved.
- `silero-vad`, TorchAudio, and `onnxruntime-gpu` were not installed.
- Torch remained 2.12.1+cu130 with CUDA 13.0 available.
- ONNX Runtime remained 1.28.0 with Azure and CPU providers; direct VAD uses only
  `CPUExecutionProvider`.
- The official wheel and model hashes, input/output metadata, cache design, and
  performance results are recorded in `direct-silero-onnx-vad.md`.
- `vad-prepare` downloaded and verified the pinned wheel, extracted only the
  default ONNX model and MIT license, and wrote the user cache atomically.
- `vad-doctor` verified the cache and loaded the real CPU session in 0.069168
  seconds on the first run and 0.072069 seconds during the simulated-offline run.
- Two original recordings each produced one segment. A third ignored WAV built
  only from those two real speech regions plus silence produced exactly two
  ordered segments.
- Invalid HTTP/HTTPS proxies were active for the cached prepare, doctor, and file
  validation; all succeeded without network access.
- Final unit tests passed 109 tests in 0.78 seconds. The coverage run passed all
  109 tests in 1.13 seconds with 80% total coverage; the new file VAD, segmenter,
  asset preparation, and model-wrapper modules reached 89%, 90%, 89%, and 78%.

The inspection wheel under ignored `data/dependency-inspection/`, the generated
two-utterance WAV, all source WAVs, the user cache, and coverage data remain
outside Git.

## Live microphone VAD development

Started on 2026-07-27 after PR #5 was marked ready and squash-merged as
`a894244`. Work continues on `feat/live-microphone-vad`.

- Python: 3.11.9 at the project `.venv` executable.
- pip: 26.1.2 from the project `.venv`.
- NumPy: 2.4.6.
- sounddevice: 0.5.5.
- ONNX Runtime: 1.28.0, CPU runtime retained.
- onnx-asr: 0.12.0 (installed for the separate file-ASR path; not imported by
  live VAD).
- GPU detected: NVIDIA GeForce RTX 4060 Laptop GPU; not used by live VAD.
- ffmpeg 8.1.1 detected; not used by live VAD.
- `python -m pip check`: no broken requirements found before implementation.
- Merged-branch baseline: 109 tests passed in 1.00 seconds.
- No dependencies, models, system packages, environment variables, or global Git
  configuration were changed for this milestone.

The new unit tests replace microphone streams and VAD inference with deterministic
fakes. They do not open a device, download/cache a model, use ASR/translation, or
write outside pytest temporary directories. Real 60-second and 120-second
validation results are recorded after the guided runs.

### Final live-VAD validation

- `python -m pytest -v`: 153 passed in 1.05 seconds.
- Coverage run: 153 passed in 1.46 seconds, 80% total coverage.
- New module coverage: `live_vad.py` 90%, `metrics.py` 96%, and
  `microphone.py` 93%.
- `python -m pip check`: no broken requirements found.
- `vad-doctor`: cached model/SHA valid; CPU session load 0.068191 seconds.
- Real input: device 1, `麦克风 (HyperX Cloud III)`; native 16 kHz mono float32
  settings accepted.
- 60 seconds: five prompted sentences became five segments, 1,874/1,874 blocks,
  queue HWM 1/320, dropped 0, gaps 0, statuses 0, average 0.525 ms, P95 0.757
  ms, one session, clean worker/device shutdown, and five valid ignored WAVs.
- Fully offline boundary check: independent file ASR exactly reproduced all five
  prompted Russian sentences; no evident beginning/end loss, merge, or split.
- 120 seconds: eight prompted sentences became eight segments, 3,750/3,750
  blocks, queue HWM 1/320, dropped 0, gaps 0, statuses 0, average 0.476 ms, P95
  0.694 ms, one session, clean timed shutdown, and no saved files.
- 120-second process-tree memory: 78.51 to 80.08 MiB; stable-window averages
  78.78 to 80.08 MiB (+1.29 MiB), with no obvious runaway growth.
- A final two-second no-save smoke run after bounding metric storage processed
  62/62 blocks with no loss/status, P95 0.734 ms, and clean resource release.

One first attempt to enumerate saved WAVs for offline ASR used an invalid
PowerShell path concatenation and reported `Second path fragment must not be a
drive or UNC name`; it did not run ASR or modify files. The corrected
`Join-Path` command completed all five cached transcriptions. The monitoring
wrapper's `Process.ExitCode` property rendered blank on this PowerShell host,
but both CLI commands and their enclosing shell calls returned success and the
application summaries reported normal duration-based shutdown.

## Live terminal subtitle development

Started on 2026-07-27 after PR #6 was marked ready and squash-merged as
`200836a`. Work continued on `feat/live-terminal-subtitles` without adding or
changing dependencies. Python remained 3.11.9; Torch remained 2.12.1+cu130 and
ONNX Runtime remained CPU package 1.28.0. `silero-vad` and TorchAudio remained
uninstalled.

Validation before real capture:

- `python -m pip check`: `No broken requirements found.`
- `python -m pytest -v`: 171 passed in 1.32 seconds.
- Coverage: 171 passed in 1.89 seconds; 80% total.
- New modules: `live_subtitles.py` 98% and `segment_processor.py` 94%.
- `vad-doctor`: pinned SHA valid, CPU session load 0.068014 seconds.
- `doctor`: 22 checks, 20 OK, 2 WARN, 0 FAIL.
- `translation-doctor`: 8 checks, 7 OK, 1 WARN, 0 FAIL.
- Device 1 (`麦克风 (HyperX Cloud III)`) passed native mono float32 16 kHz
  validation.
- System temporary-file baseline matching `ru-zh-live-subtitles-*.wav`: zero.

The guided, fully offline 60/120-second output and exact metrics are recorded in
`live-terminal-subtitles.md`. Both runs returned success from existing caches;
5/5 and 8/8 subtitles succeeded. All loss, sequence, PortAudio, backlog, and
temporary-residue counts were zero. Both model workers and the microphone
released cleanly. No WAV, cache, model, benchmark artifact, or validation log is
tracked by Git.

Known validation warnings:

- Transformers preferred `max_new_tokens=256` over the model's configured
  `max_length=200`; inference remained deterministic and successful.
- Windows WDDM returned `N/A` for per-process GPU memory through `nvidia-smi`;
  the application reported about 1,189.5 MiB peak CUDA allocation.
- A full-session auxiliary CIM process-tree sampler reached its command timeout.
  It did not affect the separately running 120-second application. A lighter
  late-session window showed no growth and observed the Python process release.
- PowerShell `Tee-Object` surfaced native stderr progress under a
  `NativeCommandError` heading even though the application exit code was zero.

## Subtitle overlay stabilization

Developed on 2026-07-27 on `feat/always-on-top-subtitle-overlay` without adding
dependencies or changing ASR, translation, VAD, Torch, ONNX Runtime, or audio
configuration. Python remained 3.11.9; Tk and Tcl both reported 8.6. `pip check`
continued to report no broken requirements.

The pre-fix GUI was exercised through real screen input. Opening its transient
settings window and changing Borderless terminated Python immediately. The
redirected stderr file remained empty because Python did not raise a Tk callback
exception. Windows Application Error event 1000 recorded `python.exe` failing in
`tk86t.dll` 8.6.2.12 with exception `0xc0000005`, fault offset
`0x0000000000024391`, and report ID
`b3147d68-cd48-4a91-82e7-9c8dc9393cf9`. The pre-fix callback applied
`overrideredirect()` while an active transient Toplevel also had a FocusOut
destroy callback pending. That native root/transient lifecycle collision—not a
generic or caught `TclError`—invalidated the Tk window state before another
context request could safely reuse it.

The fix removes compact/expanded/captions-only, keeps one persistent control
bar, keeps one withdrawn SettingsPanel, installs one root right-click binding,
and defers borderless restoration to `after_idle`. Topmost is applied only on an
explicit pin change, panel show, initial construction, or borderless restoration;
the 50 ms render poll does not call `attributes`, `lift`, or focus methods.

Real screen-control checks completed Settings show/hide/reopen, subtitle-area
and control-bar right-click, direct Stop/Start, Unpinned/Pinned, 20 rounds of
mixed Settings/right-click/pin/session operations (40 clicks), and two clean
Exit/restart/Exit cycles. Only one settings window was visible at a time, the
main bar stayed visible, both exact test process trees exited, and the retained
stderr logs were empty. A real Windowed-to-Borderless transition also remained
responsive with no new Windows Application Error event.

The desktop-control API does not enumerate or target Tk roots after
`overrideredirect(True)`. Consequently it could not perform the reverse
Borderless-to-Windowed click or ten full screen-driven round trips. The fake-Tk
regression performs ten transitions and verifies geometry/topmost/opacity,
binding count, root identity, and session identity, but this is not represented
as a substitute for the missing screen clicks. At that intermediate point,
external-application acceptance and 60/120-second live subtitle runs had not yet
been completed; the later results are recorded below.

Final local checks: 235 tests passed in 1.40 seconds; the coverage run passed the
same 235 tests in 2.20 seconds with 79% total coverage. GUI module coverage was
65% for `app.py`, 95% for `controller.py`, 100% for `events.py`, 62% for
`overlay.py`, and 98% for `state.py`. `git diff --check` completed without
whitespace errors. `.coverage`, pytest/Python caches, `.venv`, `data`, WAV,
models, and downloaded artifacts remained ignored and untracked.

### User overlay acceptance

On 2026-07-27 the user formally reported A1–A5 visual/interaction and B1–B5
PowerPoint checks as passing. Repeated real
Borderless/Windowed changes retained position, opacity, and topmost state with
one SettingsPanel and no crash or terminal Tk error. Direct main-bar Stop,
Settings, Pin/Unpin, dragging, external focus behavior, and Exit were acceptable.
Acrobat was not installed; the user explicitly waived C1–C5, so those checks are
not claimed as passed. No user screenshot was provided or claimed. These human
checks are recorded separately from Codex's mechanical GUI tests and from the
live 60/120-second audio/model validation that follows.

## Final live overlay validation

Completed on 2026-07-27 on `feat/always-on-top-subtitle-overlay`. Real cached
model loading in a Python thread had starved the Tk mainloop. The final design
keeps Tk in the parent and runs one existing `LiveTerminalSession` in a spawned
child process. A bounded multiprocessing queue returns immutable events and a
compact summary. The child never calls Tk. A real three-second diagnostic found
and then verified fixes for Windows process-counter locking and stop-forwarder
shutdown; the corrected heartbeat maximum was 0.073 seconds with queue HWM 2,
overflow 0, 94/94 blocks, and clean release.

All real GUI commands set `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. They used Python 3.11.9, Tk/Tcl 8.6, device 1
(`麦克风 (HyperX Cloud III)`), Silero VAD and GigaAM on CPU ONNX Runtime, and
NLLB on CUDA float16. No dependency, runtime, model, or system configuration was
changed and no network download occurred.

The accepted 60-second run displayed 5/5 subtitles. GUI events were 10/10,
queue HWM 2, overflow 0, render latency average/median/P95
0.030/0.026/0.054 seconds, and heartbeat maximum 0.077 seconds. It processed
1,874/1,874 blocks with audio/segment HWMs 1/320 and 1/8. Dropped blocks,
sequence gaps, PortAudio status, backlog, and queue wait were zero. Processing
RTF average/median/P95 was 0.211/0.207/0.308; RU latency was
0.628/0.611/0.680 seconds and ZH latency was 1.232/1.075/1.712 seconds. Model
counts were 1/1/1/1, CUDA peak was 1,189.6 MiB, and temporary WAV lifecycle was
5/5/0.

The real Stop → Start → Stop test produced one subtitle in each session, used
one child at a time, and released both microphones/workers. By design, the
second Start spawned a new child and reloaded each cached model once; it did not
reuse objects from the stopped process. The prepare-period Exit test emitted no
Listening event, never opened the microphone, created no WAV, remained
responsive, and left no process.

Two 120-second attempts were retained as honest non-passing evidence because
they produced only 5 and 7 subtitles. The first nevertheless exercised Settings,
Show Russian, opacity, Unpin, and Pin during live updates without regression.
The final 120.018-second run passed with 11/11 subtitles, GUI events 16/16,
queue HWM 2, overflow 0, render average/median/P95 0.033/0.029/0.055 seconds,
and heartbeat maximum 0.019 seconds. It processed 3,749/3,749 blocks; audio and
segment HWMs were 1/320 and 1/8; loss, gaps, PortAudio status, backlog, and queue
wait were all zero. Processing RTF average/median/P95 was 0.184/0.179/0.291,
RU latency 0.600/0.599/0.626 seconds, and ZH latency
0.989/0.974/1.369 seconds. Model counts were 1/1/1/1, CUDA peak was 1,189.4
MiB, and temporary WAV lifecycle was 11/11/0. A late stable memory window moved
from 5,327.1/8,594.6 MiB working/private to 5,328.2/8,595.3 MiB, with no
obvious growth trend. All workers, microphones, GUI windows, and live child
processes exited.

Exact RU/ZH output and all GUI/pipeline measurements are in
`always-on-top-subtitle-overlay.md`. The known Transformers
`max_new_tokens`/`max_length` warning remained harmless. The acceptance wording
is **GUI overlay prototype accepted for packaging evaluation**, not production
ready.

Final automated verification commands and results:

- `python -m pytest -v`: 239 passed in 1.87 seconds (the previous 235 plus four
  process-controller regressions).
- `python -m pytest --cov=live_subtitles --cov-report=term-missing`: 239 passed
  in 2.58 seconds; 79% total coverage. `process_controller.py` reached 84%,
  `app.py` 63%, `controller.py` 95%, `events.py` 100%, `overlay.py` 62%, and
  `state.py` 98%.
- Targeted GUI suite: 66 passed in 0.47 seconds.
- `python -m pip check`: `No broken requirements found.`
- `doctor`: 20 OK, 2 WARN, 0 FAIL; the warnings were the intentionally absent
  CUDA ONNX provider and the generic first-load network reminder.
- `vad-doctor`: pinned SHA valid; CPU session load 0.067652 seconds.
- `translation-doctor`: 7 OK, 1 WARN, 0 FAIL; cached NLLB exists and CUDA is
  available.
- `git diff --check`: success; Git printed only the existing Windows LF-to-CRLF
  checkout warning.
- Repository scans found no tracked WAV/ONNX/wheel/log/image artifact, no token,
  no user absolute path in the diff, no Tk call in the child controller, and no
  new network or subtitle-persistence path. `.venv`, `data`, `.coverage`, and
  Python/pytest caches remained ignored.

One targeted pytest command mistakenly named the nonexistent
`tests/test_gui_runtime.py`; collection stopped with zero tests. The corrected
command used the five actual GUI test files and passed 66/66. The first launch
attempt for the final 120-second run was rejected by the command safety policy
because it included log-file removal; no application started and no file was
changed. A unique log name was then used without overwriting anything.

## Windows onedir packaging spike

Packaging started from merged commit `140404b` on
`feat/windows-packaging-spike`. The original `.venv` remained the development
environment; PyInstaller 6.21.0 and its helper packages were installed only in
`.venv-packaging`. Python was 3.11.9 x64 on Windows build 26200. Runtime
dependencies exactly matched the accepted source environment, including Torch
2.12.1+cu130, Transformers 5.14.1, ONNX Runtime 1.28.0, onnx-asr 0.12.0,
sounddevice 0.5.5, NumPy 2.4.6, and Hugging Face Hub 1.24.0. Both environments
passed `pip check`.

Final repeatable builds took about 102 seconds (console) and 103 seconds
(windowed). They contain 5,549 files and 98 DLLs each. Console is
3,006,417,919 bytes; windowed is 3,006,413,823 bytes. Torch/CUDA accounts for
most of the footprint. Full commands, hashes, dependency inventory, warning
classification, privacy scans, Defender result, and the complete real 60-second
measurement are recorded in `windows-packaging-spike.md`.

The final automated suite passed 253 tests in 1.80 seconds; coverage passed the
same 253 tests in 2.58 seconds at 80%. Packaging-specific tests passed 14/14 in
both environments. The final cached frozen run produced 5/5 subtitles, no loss
or backlog, 0.060-second render P95, 0.286 RTF P95, 0.698/1.656-second RU/ZH
latency P95, and no remaining temporary WAV or process. The exact status is
**Onedir GUI build validated on development machine**.
