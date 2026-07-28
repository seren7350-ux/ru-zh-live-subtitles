# CPU-only clean-machine recovery validation

## Outcome

The separate CPU package completed the offline file pipeline and GUI checks in
two VMware Windows guests restored independently from the same clean snapshot.
The supported statement is:

> Clean VMware CPU-only offline file pipeline validated. Clean VMware CPU-only
> live pipeline functionally validated. Clean VMware CPU-only validation
> reproduced from a fresh snapshot.

This is not a GPU clean-machine result, a universal-Windows claim, an installer
result, or production/release readiness. The existing GPU package remains a
separate development-machine-validated candidate.

## Preserved CUDA 13 failure evidence

The original immutable evidence remains local and ignored under
`data/clean-machine-validation/evidence/vmware-cuda13-failure/`. Its relative
manifest is `failure-evidence-manifest.json`; neither the raw JSON nor the
manifest is committed.

| Field | Preserved value |
|---|---|
| Primary result | `artifacts/offline-cache-result.json` |
| SHA-256 | `1a1310f27fc22db04e266d3e6f97acc6543a33bdf3d00af1399734e3e25d8418` |
| Faulting module | `c10_cuda.dll` |
| Exception | `0xC0000005` |
| Fault offset | `0x0000000000020433` |
| PyTorch | `2.12.1+cu130` |
| Guest NVIDIA device | none |
| Trigger stage | after NLLB weights reached 512/512 |

[PyTorch #162333](https://github.com/pytorch/pytorch/issues/162333) reports a
Windows access violation in `c10_cuda.dll` for a CUDA 13 build on a CPU or GPU
machine while checking CUDA availability. The project failure belongs to the
same broad Windows/CUDA-13/no-supported-device defect category: both use a CUDA
13 PyTorch build, fault in `c10_cuda.dll`, and raise `0xC0000005` where a safe
false/no-device result is expected. They are not proven to have the same
internal call path. The upstream report used a 2.9.0 nightly, triggered from
`torch.cuda.is_available()`, and recorded offset `0x15d3`; this project used
2.12.1+cu130, failed after NLLB weight loading, and recorded offset `0x20433`.

[PyTorch #162412](https://github.com/pytorch/pytorch/pull/162412) implemented an
upstream workaround for `cudaErrorNotSupported`. It is relevant context, not a
fix applied to this package. The recovery evaluated here isolates CPU PyTorch;
it does not modify or repair the GPU runtime.

## Exact Hugging Face revision refs

The old staging path wrote a revision with `write_text(... + "\n")`. On Windows
that produced the 40-character SHA followed by CRLF. The observed source ref was
42 bytes; staging created manually in the guest after removing CRLF was only
diagnostic and was never accepted as validation evidence.

`prepare_assets.py` now validates a revision against `[0-9a-f]{40}`, encodes it
as ASCII, writes with `write_bytes`, reads it back immediately, and requires
exact byte equality. Source refs are diagnosed separately; their terminal
newline is tolerated only while parsing the host cache and is never copied to
staging.

Both final staged refs are exactly 40 bytes with no UTF-8/UTF-16 BOM, CR, LF,
space, tab, NUL, uppercase, or non-ASCII data:

| Model | Revision |
|---|---|
| GigaAM ONNX | `322c3b29492673eb7d0b434bfa9dfb8653e34d02` |
| NLLB-200 distilled 600M | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` |

Tests cover 39/41-character values, uppercase, leading/trailing whitespace,
CR/LF/CRLF, NUL, non-ASCII and BOM input, deterministic generation, manifest
hashes, and local Hugging Face cache resolution without model loading or
network access.

## Separate CPU packaging boundary

The build environment is `.venv-packaging-cpu`, CPython 3.11.9 x64. It is
ignored and is not part of the package. Key versions were:

- PyTorch `2.12.1+cpu` from the official CPU wheel index;
- `torch.version.cuda is None` and `torch.cuda.is_available() is False`;
- Transformers `5.14.1`;
- ONNX Runtime `1.28.0`;
- onnx-asr `0.12.0`;
- NumPy `2.4.6`;
- sounddevice `0.5.5`;
- PyInstaller `6.21.0`.

`pip check` reported no broken requirements. The environment does not install
torchvision, torchaudio, Triton, `nvidia-*`, or a CUDA PyTorch wheel.

`packaging/combined_cpu.spec` has one Analysis, one PYZ, two EXEs and one shared
COLLECT. It continues to use `packaging/entrypoint.py`; the GUI EXE is windowed
and the console EXE retains a console. CPU policy checks run before and after
the build and reject `c10_cuda.dll`, `torch_cuda.dll`, CUDA/cuDNN/cuBLAS family
DLLs, NVRTC/NVJitLink/CUPTI/NVPerf files, or missing `torch_cpu.dll`.

The GPU files `packaging/combined.spec`, `packaging/optimization_profile.py`,
and `packaging/hooks/hook-torch.py` remained byte-identical to `main`.

## Package inventory

| Metric | CPU candidate | Existing GPU candidate |
|---|---:|---:|
| Total bytes | 658,296,022 | 3,064,138,625 |
| Files | 5,527 | 5,463 |
| DLLs | 70 | 98 |
| Torch bytes | 374,051,194 | 2,782,103,542 |
| Torch library bytes | 329,579,216 | 2,737,631,560 |
| CUDA DLL bytes | 0 | 2,377,601,080 |
| ONNX Runtime bytes | 36,199,888 | 36,199,888 |
| Transformers bytes | 38,111,950 | 38,111,950 |
| Tk/Tcl bytes | 7,611,567 | 7,611,567 |
| Largest file | `torch_cpu.dll`, 307,778,048 | `cublasLt64_13.dll`, 477,896,816 |

The CPU candidate is 2,405,842,603 bytes (78.52%) smaller. Model weights remain
external to both application packages, so this comparison does not include the
NLLB, GigaAM, or Silero staging assets. A smaller CPU build does not replace the
GPU candidate.

## Staging provenance

The accepted staging is local, ignored, and was regenerated into the unique
directory `data/clean-machine-validation/cpu-run-20260728T030308Z/` from:

- the original host Silero cache;
- the original host GigaAM Hugging Face cache;
- the original host NLLB Hugging Face cache;
- the newly built CPU-only combined onedir;
- the existing non-sensitive fixed WAV.

No file was copied back from the guest and no ref was edited in the guest. Host
validation checked 5,527 package records, 17 model records and one test-audio
record. All hashes matched. The 5,552 files below `package`, `model-assets` and
`scripts` were made read-only; the separate empty `results` directory remained
writable. Git ignored the complete tree and tracked none of it.

Several earlier generated candidates are intentionally retained with harness
failure evidence. They are not accepted validation inputs and were not modified
in place.

## VMware environment

Both accepted runs restored `00-Clean-Windows-Tools-NoNetwork` before starting
and used the same read-only staging.

| Property | Value |
|---|---|
| Windows | Windows 11 Pro, Chinese edition |
| Version/build | 10.0.26200 / 26200 |
| RAM | 8,588,644,352 bytes (8.0 GiB) |
| Logical CPUs | 4 |
| Reported CPU | 13th Gen Intel Core i7-13700H |
| Display | VMware SVGA 3D, driver 9.17.11.3 |
| NVIDIA guest device/driver | none observed |
| Free system disk before run 2 | 108,908,511,232 bytes |
| VMware Tools | 13.1.0 build-25218885 |
| Microphone | available; device 1 selected |
| Network | adapter disconnected; no default route; TCP probe failed |

There was no repository, venv, Git, `py.exe`, `pip.exe`, Hugging Face cache or
Silero cache at the second restored start. `python.exe` resolved only to the
WindowsApps Microsoft Store execution alias; no Python runtime was installed.

## First restored snapshot

The first accepted result is locally ignored at
`cpu-run-20260728T030308Z/results/vmware-cpu-offline-cache-1-20260728-111346/offline-cache-result.json`.
Its SHA-256 is
`95330888dc99bf2160e8dc10a4e3e428397ca38e64fb1bb2498e1fd8a70a5063`.

- package/model/test-audio manifests: 5,527/17/1 records, all valid;
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`;
- package family `cpu`, PyTorch `2.12.1+cpu`, CUDA `None/False`, selected device
  `cpu`, frozen state true;
- all seven commands exited 0, with no timeout, failed command or residual
  process;
- cache copy 4.038 s;
- standalone ASR: load 2.892 s, recognition 0.429 s, RTF 0.054;
- combined run: ASR load/recognition 2.547/0.652 s, NLLB load/translation
  11.408/2.464 s, total processing 47.623 s, end-to-end RTF 5.953.

A separate offline process measurement, without writing caption text to disk,
returned exit code 0 and normalized content equivalent to
`Здравствуйте. Это проверка распознавания русской речи.` and
`你好，这是一个俄罗斯语识别检查。`. Windows PowerShell displayed the UTF-8 text
through an incompatible console code page; the GUI rendered multilingual text
correctly. The measured run took 51.885 s wall time, peaked at 3,993,845,760
working-set bytes, 4,125,536,256 private bytes and 4,125,544,448 paged-memory
bytes.

The manually accepted overlay demo retained its controls, Start/Stop,
Pin/Unpin, borderless toggle and Exit, with no residual process. Real microphone
GUI testing deliberately exercised two Start/Stop cycles:

| Metric | Session 1 | Session 2 |
|---|---:|---:|
| Duration | 28.618 s | 88.899 s |
| Successful/failed subtitles | 3/0 | 10/0 |
| Audio blocks | 885/885 | 2,772/2,772 |
| Audio/segment queue HWM | 1/1 | 1/1 |
| Dropped/gaps/status/backlog | 0/0/0/0 | 0/0/0/0 |
| RTF P95 | 0.443 | 0.561 |
| Russian latency P95 | 0.770 s | 0.813 s |
| Chinese latency P95 | 1.539 s | 1.417 s |
| Temporary WAV created/deleted/remaining | 3/3/0 | 10/10/0 |

All GUI events were dequeued (23/23), render P95 was 0.053 s, maximum
heartbeat delay was 0.068 s, both workers exited and the microphone closed.
Logs contained no token, caption-text or user-path marker.

## Second restored snapshot

Before copying models, package-only validation proved the user Hugging Face and
Silero caches absent. The package share rejected a write probe. Defender scanned
the package in 14.725 s, exited 0 and reported no threats. Its ignored result
SHA-256 is
`7df4000ad8a938545cba041b338771e636ff641025a8125cb877fe2828a0cf59`.

The second accepted offline result is
`cpu-run-20260728T030308Z/results/vmware-cpu-offline-cache-2-20260728-114807/offline-cache-result.json`,
SHA-256
`b84b02d6bf21ee62c075a20fbec9d7307bbec239c35bbe654a246e8570fa68b5`.

- all three manifests were valid at 5,527/17/1 records;
- all seven commands exited 0 with no timeout or residual process;
- cache copy 13.524 s;
- standalone ASR: load 2.648 s, recognition 0.650 s, RTF 0.081;
- combined run: ASR load/recognition 2.904/0.450 s, NLLB load/translation
  11.565/2.597 s, total processing 47.977 s, end-to-end RTF 5.997;
- the guest remained offline and selected CPU.

The second real GUI retry displayed one successful subtitle in 16.652 s. Its
audio blocks were 513/513, queue HWM was 1/1, dropped/gaps/status/backlog were
0/0/0/0, RTF P95 was 0.274, Russian/Chinese latency P95 was 0.786/1.612 s,
the temporary WAV count was 1/1/0, workers exited, and the microphone closed.
GUI render P95 was 0.061 s and maximum heartbeat delay was 0.032 s. Log privacy
checks and residual-process checks again passed.

The first manual GUI launch in this snapshot omitted `HF_HOME`, so offline
Transformers correctly reported that no cached snapshot existed in its default
location. The cache was present in the validation-specific directory used by
the successful file pipeline. Setting `HF_HOME` to that already populated
directory fixed the launch without enabling network or changing staging. This
procedural error is retained as a warning, not hidden as a successful run.

## Harness corrections encountered during validation

The following pre-application harness failures were fixed and retained in local
ignored result directories:

1. PowerShell parsed `$escaped:` as an invalid scoped variable; `${escaped}:`
   is now used.
2. `where.exe` wrote the expected missing-command message to stderr under
   `$ErrorActionPreference='Stop'`; `Get-Command -ErrorAction SilentlyContinue`
   now performs discovery.
3. PowerShell unwrapped a one-record test-audio manifest; manifest output is
   normalized back to an array.
4. `Start-Process -ArgumentList` split a UNC path containing `Shared Folders`
   and returned null exit codes. Windows argument quoting and direct .NET
   `ProcessStartInfo` now preserve arguments and integer exit codes. The offline
   harness writes JSON and throws if any required command fails or times out.

Other retained warnings are the Windows symlink-degraded Hugging Face host
cache, Windows console mojibake, the Transformers notice that `max_new_tokens`
takes precedence over `max_length`, the intentional overlay-demo simulated
translation error, and the package-only GUI timeout used only as a bounded
startup probe. None is reported as a model or clean-machine success.

## Automated validation

The final source environment completed 367 tests; the coverage run also
completed 367 tests with 80% total coverage. The existing GPU packaging
environment completed its 102 focused packaging and clean-machine tests. The
separate CPU packaging environment completed 127 focused packaging,
clean-machine and CPU-policy tests. `pip check` reported no broken requirements
in all three environments.

Final repository checks found no tracked model, audio, executable, DLL, PYD,
diagnostic-log, dump or local evidence file. They also found no embedded host or
guest user path in the commit scope. The accepted staging, raw validation JSON,
failure evidence, virtual environments and build outputs remain local and
ignored. `git diff --check` and PowerShell parser checks passed.

## Performance and next gate

Cold file translation has an end-to-end RTF near 6 because it includes model
startup, so it is not real-time. Once models were prepared, the short live
sessions observed RTF P95 below 0.6 and Chinese latency P95 between 1.417 and
1.612 seconds with no backlog. This establishes functional compatibility and a
promising short-session CPU baseline, not a universal or sustained-load
real-time guarantee.

Do not start installer, onefile, release, signing or updater work from this
result alone. A later decision may compare the independently validated CPU and
GPU candidates on supported target hardware. GPU clean-machine validation on a
machine with a real NVIDIA device remains recommended and separate.
