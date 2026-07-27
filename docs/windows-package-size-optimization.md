# Windows onedir size-optimization spike

## Outcome

Status A — **Combined onedir validated** on the development machine. The
console and GUI launchers now share one dependency directory. This removes the
second copy of Torch/CUDA, Tk/Tcl, ONNX Runtime, and the Python runtime, but it
does not materially reduce the size of one complete GPU runtime. No model,
runtime, CUDA wheel, or application behavior was changed.

PR #9 was made ready and squash-merged before this work. Its `main` merge
commit is `3069e96744c97139f6198f8790f9a6f52d681f35`. This spike was performed on
`feat/windows-package-size-optimization` with Python 3.11.9, PyInstaller 6.21.0,
Torch 2.12.1+cu130, and CUDA runtime 13.0.

## Reproducible builds

The two original specs remain available as diagnostic baselines. The combined
spec uses one `Analysis`, one `PYZ`, two `EXE` objects, and one shared
`COLLECT`. `ru-zh-subtitles-console.exe` remains a console executable and
`ru-zh-subtitles.exe` remains windowed.

```powershell
# Original independent baselines
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\console.spec
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\windowed.spec

# Complete combined baseline; this is the default profile
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\combined.spec

# Validated conservative candidate
$env:RU_ZH_PACKAGE_PROFILE = "optimized"
$env:RU_ZH_TORCH_COLLECTION_MODE = "pyz+py"
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\combined.spec
Remove-Item Env:RU_ZH_PACKAGE_PROFILE
Remove-Item Env:RU_ZH_TORCH_COLLECTION_MODE
```

`baseline` excludes no binary and no copied data. `optimized` removes only
approved installer bookkeeping from `.dist-info` directories. It retains
`METADATA`, entry points, licenses, notices, SBOM material, every Python module,
and all 37 Torch DLLs. The version-locked profile fails on a Torch/CUDA version
mismatch, a missing approved target, an unexplained exclusion, or an unknown
large Torch DLL. Profile selection is explicit and defaults to `baseline`.

## Baseline and size results

Both original specs were rebuilt from the merged `main`. Each took about 100
seconds. Their dependency structure and category sizes exactly matched PR #9;
the EXE/header rebuild changed each directory by only 915 bytes.

| Build | Bytes | Files | DLLs | EXE SHA-256 |
| --- | ---: | ---: | ---: | --- |
| independent console | 3,006,418,834 | 5,549 | 98 | `EEAF8C61846FEDA41DB965B58C866BE2785631726CCED5F56B0C155B54B668BA` |
| independent GUI | 3,006,414,738 | 5,549 | 98 | `32F7BE41991CFFDE6BCE1A478BC4A6FEE7992AC9AA999923C199A5DC4A593D1` |
| combined baseline | 3,066,371,551 | 5,550 | 98 | two launchers, one dependency set |
| final conservative candidate | 3,064,137,629 | 5,463 | 98 | GUI `DE668C9B…9FB0B2`; console `FF5EEDCF…918337` |

The two independent rebuilt directories total 6,012,833,572 bytes. The final
combined candidate saves 2,948,695,943 bytes, or 49.040%, against that total.
It is still 57,722,891 bytes (1.920%) larger than the independent GUI baseline
because it also contains the console launcher. Therefore this result must not
be described as a material reduction of the single GPU runtime.

The final candidate contains three EXE files when PyTorch's bundled
`protoc.exe` is counted, 98 DLLs, 57 PYDs, and 4,258 loose Python files. The
largest file remains `cublasLt64_13.dll` at 477,896,816 bytes. Category totals
remain:

- Torch: 2,782,103,542 bytes; `torch/lib`: 2,737,631,560 bytes.
- CUDA-marker DLLs: 2,377,601,080 bytes.
- ONNX Runtime: 36,199,888 bytes.
- Transformers: 38,111,950 bytes.
- NumPy: 27,145,296 bytes; Tk/Tcl: 7,611,567 bytes.
- onnx-asr: 61,811 bytes; sounddevice/PortAudio: 308,686 bytes.

The combined baseline build took 108.600 seconds. Experiment 1 took 109.251
seconds. All full build warning files contained 894 lines; retained warnings
include optional TensorBoard/Triton imports, ctypes basename analysis, and
PyTorch distributed deprecations.

## Analysis method

`packaging/analyze_distribution.py` produces a terminal summary and a complete
relative-path JSON inventory. It rejects model weights, cached assets, audio,
logs, and unexpected ONNX files. `packaging/diff_distributions.py` reports
added, removed, and changed files plus exact byte/percentage differences.
Machine-generated reports live under ignored `data/packaging-size-analysis/`;
only the path-free template is committed.

Three independent final-candidate runs were sampled every requested 200 ms
(the effective cadence can be slower while CIM enumerates the process tree):

1. static GUI with `--no-auto-start`: 12 samples, 82 module records;
2. `overlay-demo`: 12 samples, 82 module records;
3. real cache-only 60-second subtitles: 168 samples, 256 records.

All three had zero module-read permission errors. Their union contained 97
distinct dist-relative modules and 89 Windows system module basenames. The real
run's parent loaded 33 unique dist modules (14 DLL, 18 PYD); its single worker
loaded 94 (55 DLL, 38 PYD). System DLLs are recorded only by basename/category;
no machine path appears in the saved data. A first attempt incorrectly iterated
`.Modules` on the array returned by `Get-Process -Module`; the script was fixed
to iterate that array directly. A shutdown race is now distinguished from a
permission failure, and JSON is UTF-8 without BOM.

## PE dependency evidence

`packaging/analyze_pe_dependencies.py` reads normal and delay import tables for
EXE, DLL, and PYD files, resolves dist dependencies case-insensitively, and
recognizes files present in Windows system directories without writing those
absolute paths. It separately computes the EXE/PYD static closure before adding
the dynamic DLL entry set.

- PE files scanned: 158.
- Static entries: 60; static closure: 108 files.
- Dynamic-entry union closure: 157 files.
- Normal import relationships: 921.
- Delay imports: 2 (`POWRPROF.dll` and `wevtapi.dll`, both system).
- Missing dependencies: 0.
- Dynamically loaded but outside the static closure: 24.
- Static closure files not observed in the three runs: 35.

The 24 dynamic-only files include PortAudio, the ONNX Runtime provider bridge,
the UCRT, and multiple cuDNN/NVRTC/CUDA helper DLLs. This demonstrates why
absence from a PE import table is not removal evidence. Conversely, the 35
static-only files include optional command PYDs and API-set forwarders; absence
from three runs is also not removal evidence.

## Torch/CUDA inventory and experiments

`packaging/torch_binary_inventory.json` is a sanitized, dist-relative table of
all 37 Torch DLLs. It records SHA-256, category, size, dynamic observation,
first stage, PE evidence, direct dependants, baseline inclusion, candidate
status, risk, and test result. Categories include Torch core/CPU/CUDA, CUDA
runtime, cuBLAS/cuBLASLt, cuDNN, cuFFT, cuRAND, cuSOLVER, cuSPARSE, NVRTC,
nvJitLink, profiling/NVTX, distributed/TensorPipe, and unknown. The one
name-only `unknown` file (`zlibwapi.dll`, 89,088 bytes) is retained by policy.

Every one of the 37 Torch DLLs was actually loaded by the real NLLB CUDA worker.
Therefore no CUDA group met the mandatory condition of being absent from all
three runs. No DLL exclusion experiment was authorized; the final excluded DLL
set is empty and the retained set is all 37 files.

Experiments were isolated:

- **Experiment 0 — shared combined baseline:** passed. It saves 49.003% versus
  two independent directories, while adding 59,956,813 bytes versus one GUI
  directory for the second launcher.
- **Experiment 1 — installer bookkeeping:** passed. Removing 87 approved
  `.dist-info` records saved 2,233,922 bytes (0.073%) without changing code or
  binaries. Frozen device/VAD/doctor checks and real cache-only GigaAM CPU +
  NLLB CUDA translation passed.
- **Experiment 2 — Torch `pyz` only:** failed and was rolled back. It saved an
  additional 41,259,670 bytes, but real offline `translate-audio` exited 2 with
  `Translation dependencies are unavailable: could not get source code`.
  Final mode is `pyz+py`.
- **Experiment 3 — tests/benchmark/distributed modules:** not built because the
  candidate precondition failed. The largest apparent testing graph is directly
  imported from `torch.distributed.tensor`, while Transformers imports
  distributed, Dynamo, and Inductor paths. Remaining isolated benchmark-only
  files are too small to justify blind dynamic-import risk.
- **Experiments 4+ — CUDA groups:** not attempted. All 37 DLLs were observed in
  the real child process, so cuDNN, cuFFT, cuRAND, cuSOLVER, cuSPARSE, NVRTC,
  nvJitLink, profiling/NVTX, and distributed/TensorPipe all fail the stated
  candidate gate.

The first Experiment 1 build was intentionally stopped by the safety check
because `nvperf_host.dll` (27,764,256 bytes) was not in the known-large prefix
list. Inventory and dynamic evidence classified it as an observed
profiling/NVTX file, so `nvperf` (and `cupti`) were added as known **retained**
prefixes. Nothing was deleted by that failed build.

## Frozen validation

The final candidate ran cache-only with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, a PATH containing only Windows system tools, and a
repository-external working directory containing Chinese characters and a
space. Console help, devices, VAD doctor, doctor, and translation doctor passed.
Fifteen Unicode-named input devices were reported. No system Python was used.

The real 8-second WAV path produced:

- RU: `Здравствуйте. Это проверка распознавания русской речи.`
- ZH: `你好,这是一个俄罗斯语识别检查.`
- GigaAM CPU load/recognition: 2.651/2.006 seconds.
- NLLB CUDA load/translation: 5.220/0.612 seconds.
- total 12.383 seconds, end-to-end RTF 1.548, CUDA peak 1,189.6 MiB.

The final 60-second GUI run used device 1, cached VAD/GigaAM/NLLB, CPU ONNX ASR,
CUDA float16 translation, one beam, topmost borderless GUI, and auto-start. The
privacy log intentionally contains no subtitle text, audio path, token, or
user-home path; exact displayed RU/ZH text is therefore not reconstructed from
disk.

- session 60.049 seconds; displayed/failed 5/0; GUI events 10/10;
- render P95 0.050 seconds; maximum heartbeat delay 0.037 seconds;
- audio blocks 1,875/1,875; audio queue HWM 2/320;
- segment queue HWM 1/8;
- dropped blocks, sequence gaps, PortAudio status, and backlog: 0/0/0/0;
- processing RTF P95 0.313;
- RU/ZH latency P95 0.702/1.807 seconds;
- VAD/ASR/tokenizer/translator loads 1/1/1/1;
- CUDA peak 1,189.6 MiB;
- temporary WAV created/deleted/remaining 5/5/0;
- workers and microphone released; no parent, child, or sampler process remained.

Against the accepted frozen baseline, RTF P95 increased 9.4%, RU latency P95
0.6%, and ZH latency P95 9.1%; all are below the 20% regression gate. Render
P95 improved from 0.060 to 0.050 seconds. Heartbeat increased from 0.019 to
0.037 seconds but remains far below the 0.500-second functional limit. Model
preparation took 11.637 seconds in the final warm cache-only process.

Static GUI, overlay demo, normal close, duration stop, multiprocessing spawn,
worker cleanup, and microphone release passed. GUI automation could not target
the borderless Tk window through the available accessibility window list, so
normal close was requested through its main-window message for static/demo
sampling; the user performed the real-run Exit. Existing GUI unit and earlier
manual interaction tests continue to cover Settings, Start/Stop, Pin/Unpin,
popover, Escape, and focus behavior.

## Privacy, Defender, and limitations

The final dist contains no `.pt`, `.pth`, `.safetensors`, `.bin`, WAV, MP3,
FLAC, log, model snapshot, cache, token, or environment. Its only ONNX files are
seven small onnx-asr resampling graphs. A source scan found only deliberately
fake token strings inside redaction tests; no real token or absolute user path
was found. Generated baseline, module, PE, Defender, and build outputs remain
ignored and are not committed.

The final automated source run passed 271/271 tests in 1.69 seconds. The coverage
run passed the same 271 tests in 2.68 seconds with 80% total coverage. The
packaging environment passed 32/32 packaging/size-analysis tests, and both the
development and packaging environments reported no broken requirements.

Microsoft Defender remained enabled with real-time protection enabled. A custom
scan of the final 3.064 GB candidate completed in 8.317 seconds with zero new
detections. No Defender setting, exclusion, or policy was changed.

This was not a clean-machine test. The EXEs are unsigned; no installer,
onefile, release, upload, or production distribution was created. Model caches
remain external. NLLB's CC-BY-NC-4.0 research/non-commercial limitation and all
existing third-party notices remain applicable.

The next packaging step should be an independent clean Windows-machine
validation of the combined candidate. Because Torch/CUDA is the dominant and
observed-loaded size source, a separate future evaluation may compare a
CPU-only package, CTranslate2, ONNX translation, or a separately downloadable
GPU runtime. None of those runtime migrations belongs to this spike.
