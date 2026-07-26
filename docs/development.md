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

The T5 checkpoint is an experimental baseline and provisional benchmark model,
not an approved final subtitle model. Its speed and memory use meet the prototype
target and general software instructions are often usable, but the recorded
mathematical terminology errors make it unsuitable for unattended mathematical
classroom subtitles. There is currently no final default translation model.
ASR and translation remain separate; the next stage compares M2M100 and NLLB
against this baseline.

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

All models pass the local GPU P95 and peak-memory limits. None approaches the 85%
mathematical terminology threshold: T5 peaks at 13.3%, M2M100 at 8.9%, and NLLB
at 8.9%. Dedicated machine-translation models still do not satisfy the project
requirement. No model is selected and ASR remains disconnected.

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
