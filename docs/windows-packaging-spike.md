# Windows onedir packaging feasibility spike

Status: **Onedir GUI build validated on development machine.**

This spike evaluates PyInstaller 6.21.0 on Windows without claiming a portable,
signed, production-ready distribution. It deliberately does not build onefile,
an installer, a release artifact, or a signed executable.

## Reproducible environment

- Base commit: `140404b03774dc3243e7dc38f536d016285fc137`.
- Branch: `feat/windows-packaging-spike`.
- Windows: `Windows-10-10.0.26200-SP0`, x86-64.
- Python: CPython 3.11.9, 64 bit.
- Development environment: `.venv`, left unchanged.
- Isolated packaging environment: `.venv-packaging`.
- PyInstaller: 6.21.0, installed through the optional `packaging` extra.
- Shared runtime versions: NumPy 2.4.6, ONNX Runtime 1.28.0,
  onnx-asr 0.12.0, sounddevice 0.5.5, Torch 2.12.1+cu130,
  Transformers 5.14.1, Hugging Face Hub 1.24.0, tokenizers 0.22.2,
  sentencepiece 0.2.2, and safetensors 0.8.0.
- Packaging-only additions: altgraph 0.17.5, pefile 2024.8.26,
  PyInstaller 6.21.0, pyinstaller-hooks-contrib 2026.6, and
  pywin32-ctypes 0.2.3.

Both environments passed `pip check`. A first resolver attempt selected
Hugging Face Hub 1.25.0; validation stopped and the packaging environment was
corrected to the development environment's 1.24.0 before any build was used.
No runtime dependency was intentionally upgraded.

The exact shared `pip freeze` inventory was:

```text
annotated-doc==0.0.4
anyio==4.14.2
certifi==2026.7.22
cffi==2.1.0
click==8.4.2
colorama==0.4.6
coverage==7.15.2
filelock==3.32.0
flatbuffers==25.12.19
fsspec==2026.6.0
h11==0.16.0
hf-xet==1.5.2
httpcore==1.0.9
httpx==0.28.1
huggingface_hub==1.24.0
idna==3.18
iniconfig==2.3.0
Jinja2==3.1.6
lxml==6.1.1
markdown-it-py==4.2.0
MarkupSafe==3.0.3
mdurl==0.1.2
mpmath==1.3.0
networkx==3.6.1
numpy==2.4.6
onnx-asr==0.12.0
onnxruntime==1.28.0
packaging==26.2
pluggy==1.6.0
portalocker==3.2.0
protobuf==7.35.1
pycparser==3.0
Pygments==2.20.0
pytest==9.1.1
pytest-cov==7.1.0
pywin32==312
PyYAML==6.0.3
regex==2026.7.19
rich==15.0.0
sacrebleu==2.6.0
safetensors==0.8.0
sentencepiece==0.2.2
shellingham==1.5.4
sounddevice==0.5.5
sympy==1.14.0
tabulate==0.10.0
tokenizers==0.22.2
torch==2.12.1+cu130
tqdm==4.69.1
transformers==5.14.1
typer==0.27.0
typing_extensions==4.16.0
```

The editable project line pointed to the base commit. The packaging freeze adds
only the five packaging-only packages listed above.

## Frozen entry and paths

`packaging/entrypoint.py` imports only `multiprocessing` at module load. Its
first guarded runtime action is `multiprocessing.freeze_support()`, before the
project CLI, Tk, Torch, Transformers, or model modules are imported. PyInstaller
therefore intercepts `--multiprocessing-fork` child arguments before normal CLI
dispatch. Runtime process-tree checks showed one GUI parent and one expected
worker; no recursive GUI or unbounded executable spawning occurred.

`live_subtitles.frozen_entry` reuses the existing argparse CLI. The console EXE
shows help with no arguments. The windowed EXE starts `live-overlay` with its
existing defaults and replaces absent standard streams with console-compatible
sinks. `pythonw.exe` equivalence was checked before packaging.

`runtime_paths.py` is the only source module that refers to `_MEIPASS`. Bundled
static resources use its helper; Hugging Face models remain in the user's Hugging
Face cache, Silero remains under LocalAppData, temporary WAV files remain under
the system temporary directory, and diagnostic logs remain under LocalAppData.
Neither the current working directory nor the repository is used as a runtime
write location.

## Specs and hooks

The two repeatable specs are:

- `packaging/console.spec`: `ru-zh-subtitles-console`, `console=True`.
- `packaging/windowed.spec`: `ru-zh-subtitles`, `console=False`.

Both are onedir builds with `debug=False`, `strip=False`, and `upx=False`.
They use the default PyInstaller icon because the project has no approved icon.

Project hooks are deliberately scoped:

- `hook-live_subtitles.py` declares dynamic runtime packages and copies their
  package metadata.
- `hook-onnx_asr.py` includes package code, `fbanks.npz`, and seven small
  `resample_*_16.onnx` audio preprocessing graphs; it includes no ASR weights.
- `hook-sounddevice.py` includes the non-ASIO 64-bit PortAudio DLL and its
  notice, not every bundled PortAudio variant.
- `hook-torch.py` preserves all wheel-provided runtime DLLs and dynamically
  loaded runtime modules. It filters private test modules, while retaining
  `torch.testing._internal.common_dtype`, which `torch._refs` requires in the
  verified Transformers path. Transitive Torch runtime imports still retain
  34 files under `torch/testing` (2,367,127 bytes); these are retained because
  runtime Torch modules import them, not because the project collected a test
  suite wholesale.

No hook uses `collect_all`. No unknown CUDA or ONNX DLL was deleted.

## Build results

```powershell
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\console.spec
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\windowed.spec
```

Final local builds took approximately 102 seconds for console and 103 seconds
for windowed. The first fully conservative iterations took approximately 131
and 174 seconds. Intermediate evidence-based filtering builds took about 99 to
101 seconds.

| Build | Size | Files | DLLs | EXE SHA-256 |
| --- | ---: | ---: | ---: | --- |
| console | 3,006,417,919 bytes | 5,549 | 98 | `79919BFC597D001F57A0A9CF11E2C2F275636585CED5EA5249A20A49DB32C8BB` |
| windowed | 3,006,413,823 bytes | 5,549 | 98 | `CF309BA385B00C388DC56CE122007230EA59D9512079EBCF4B2E53960D57D6AD` |

The largest file is `cublasLt64_13.dll` at 477,896,816 bytes. The Torch tree is
2,782,103,542 bytes; its 37 DLLs alone are 2,737,631,560 bytes. ONNX Runtime is
36,199,888 bytes. Tcl/Tk data and DLLs are about 8.7 MiB. The output is large,
but this functional spike does not blindly remove CUDA libraries.

Each final warning file has 894 lines and 152,696 bytes. Review classified the
entries as Windows-inapplicable POSIX imports, optional/test integrations
(TensorFlow, CoreML, TVM, SciPy test paths, TensorBoard, Triton and similar),
PyInstaller false-positive attribute imports, or modules requiring runtime
verification. Two genuine Torch packaging misses were found during real GUI
model preparation (`torch.testing`, then `torch.testing._internal`); the final
custom Torch hook retained the exact `common_dtype` runtime dependency and the
same real path passed. No final required missing module is known from the tested
GigaAM/NLLB/VAD/GUI path.

## Frozen validation

All CLI tests ran from a repository-external directory whose name contained
Chinese characters and spaces, with a minimal Windows PATH,
`PYTHONHOME`/`PYTHONPATH` removed, and both Hugging Face offline variables set.
The path contained neither environment. `sys.executable` reported the frozen
EXE; process command lines contained no `python.exe`.

- No-argument help and `--help`: exit 0.
- `devices`: exit 0, 15 input devices, Unicode names intact.
- `doctor`: 19 OK, 3 WARN, 0 FAIL. The warnings were the expected inactive
  virtual environment, absent CUDA ONNX provider, and generic first-load note.
- `vad-doctor`: cached SHA valid; CPU ONNX load 0.071231 seconds.
- `translation-doctor`: 7 OK, 1 WARN, 0 FAIL; CUDA and cached NLLB present.
- Cached short-WAV pipeline: exact Russian text
  `Здравствуйте. Это проверка распознавания русской речи.` and Chinese
  `你好,这是一个俄罗斯语识别检查.`; ASR load/recognition 2.499/2.159 seconds,
  translation load/inference 5.277/0.635 seconds, total 12.489 seconds,
  RTF 1.561, CUDA peak 1,189.6 MiB.

The final windowed EXE displayed no console, opened one GUI, used one worker,
loaded the external caches, and stopped/closed normally. `overlay-demo` loaded
no model and opened no microphone. Screen control verified direct Stop,
Pin/Unpin, Settings, Escape close, and normal Exit. No residual process remained.

### Real frozen 60-second run

The run used device 1 (`麦克风 (HyperX Cloud III)`), cache-only mode, CUDA NLLB,
one beam, a repository-external Unicode/space working directory, and the
windowed EXE. A framed overlay was selected for reliable screen observation;
the executable's default borderless mode was separately launched successfully.

All five subtitles succeeded, in order, without duplicates or omissions:

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

Measured results:

- Session 60.050 seconds; successful/failed 5/0.
- GUI events 10/10; queue HWM 2/256; overflow 0.
- GUI render P95 0.060 seconds; maximum heartbeat delay 0.019 seconds.
- Audio blocks 1,875/1,875; queue HWM 1/320.
- Segment queue HWM 1/8.
- Dropped blocks, sequence gaps, PortAudio statuses, and backlog failures: 0.
- Processing RTF P95 0.286.
- Russian/Chinese latency P95: 0.698/1.656 seconds.
- VAD/ASR/tokenizer/translator creation counts: 1/1/1/1.
- CUDA peak allocation: 1,189.6 MiB.
- Temporary WAV created/deleted/remaining: 5/5/0.
- VAD and subtitle workers exited; microphone released; no residual process.
- Sampled child working/private memory near the end was about
  5,278/8,033 MiB; the worker then exited at the duration boundary.

Against the accepted source 60-second baseline, frozen render P95 changed from
0.054 to 0.060 seconds, RTF P95 from 0.308 to 0.286, Russian latency P95 from
0.680 to 0.698 seconds, Chinese latency P95 from 1.712 to 1.656 seconds, and
heartbeat maximum from 0.077 to 0.019 seconds. These warm metrics show no clear
regression on this development machine; cold model preparation was about 55
seconds and remains a packaging/startup cost to investigate.

## Privacy, distribution, and security checks

Windowed diagnostics are written to
`%LOCALAPPDATA%\ru-zh-live-subtitles\logs\application.log`. Logs rotate at
1 MiB with two backups (three files total), default to INFO, redact home/temp
paths and tokens, and contain lifecycle, model-stage, infrastructure-error, and
aggregate exit metrics only. The real log contained no Russian or Chinese
subtitle text, audio, temporary WAV path, token, or full user directory.

The final distribution scan found no WAV, `.bin`, `.safetensors`, `.pt`, `.pth`,
model snapshot, Hugging Face cache, Silero cache, pytest, coverage, Git, pip, SSH,
or environment directory. The only ONNX files are seven 3.7–10.0 KiB onnx-asr
resampling graphs. Binary/text scanning found no machine-specific home-directory
prefix, repository environment path, account name, or token. Generic
email-pattern hits were public
third-party license/SBOM/source metadata, not user data. DLLs were attributable
to Python, Windows runtime, Torch/CUDA, ONNX Runtime, NumPy, pywin32, Tcl/Tk, or
sounddevice/PortAudio.

The EXEs are unsigned. No SmartScreen, unknown-publisher, or Defender blocking
prompt appeared during local launches. A one-time Microsoft Defender CLI custom
scan of the final windowed onedir returned exit 0 and `found no threats`; no
security setting, exclusion, or policy was changed.

Model weights are not distributed. Users must prepare their own external caches.
NLLB remains a CC-BY-NC-4.0 non-commercial research candidate; this build is
only for learning, research, and non-commercial validation. A complete legal
review is required before distribution.

## Automated checks and remaining work

- Source suite: 253 passed in 1.80 seconds.
- Coverage: 253 passed in 2.58 seconds; 80% total.
- Packaging tests: 14/14 in both development and packaging environments.
- Both environments: `pip check` reported no broken requirements.
- CI validates spec/hook syntax and runs tests; it does not build or upload the
  multi-gigabyte CUDA distribution and does not download models.

Known warnings/errors retained as evidence:

- The first packaging resolver mismatch was corrected before building.
- Two intermediate GUI builds failed during model preparation because Torch's
  runtime dependency on `torch.testing._internal.common_dtype` was not yet
  retained; the final build fixes and passes that path.
- One GUI automation click started an extra bounded five-second test session;
  it stopped and exited normally without residue.
- One license metadata display encountered a Windows GBK encode error on an
  upstream author name; it did not change the environment.
- Transformers warns that `max_new_tokens=256` takes precedence over configured
  `max_length=200`; inference succeeded and the algorithm was not changed.
- The packaging build emits optional TensorBoard/Triton/deprecation warnings.
- One hook-import verification was first invoked with the development
  interpreter, where PyInstaller is intentionally absent; it failed without
  changing files and passed when corrected to `.venv-packaging`.
- Git reports the existing LF-to-CRLF checkout warning on Windows.

Recommendation: perform a separate, evidence-driven size-optimization pass and
then evaluate the untouched onedir on a clean Windows machine. Do not start an
installer, release, signing, or commercial-distribution phase until the clean
machine, license, footprint, and startup findings are resolved.

Follow-up completed: PR #9 was merged and the console/windowed outputs were
combined into one shared onedir. The evidence, safe metadata cleanup, failed
Torch `pyz` experiment, all-retained CUDA DLL inventory, and final 5/5 offline
run are documented in [Windows onedir size optimization](windows-package-size-optimization.md).

The next follow-up prepared a machine-path-free Windows Sandbox validation kit,
but the current host is Windows 11 Home and has no Windows Sandbox application.
No feature enablement, elevation, restart, or reduced-PATH substitute was used,
and no clean-machine pass is claimed. See
[Windows Sandbox clean-machine validation](windows-sandbox-clean-machine-validation.md)
for the exact cache boundary and manual eligible-host sequence.
