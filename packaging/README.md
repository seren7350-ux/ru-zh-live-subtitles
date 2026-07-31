# Windows onedir packaging spike

> Version 0.2.0 packaging note (2026-07-31): the end-user CPU candidate defaults
> to the official pinned GigaAM Multilingual Large CTC Torch 2.10/TorchAudio
> 2.10 CPU backend. The old 0.1.0 onedir, installer, tag and Release remain the
> retained RNNT/ONNX baseline and must not be overwritten or relabeled.

This directory contains reproducible PyInstaller 6.21.0 inputs for two onedir
builds. `console.spec` creates the diagnostic CLI and `windowed.spec` creates the
noconsole overlay launcher. Both reuse `entrypoint.py`; its first runtime action
inside the main guard is `multiprocessing.freeze_support()`.

The package intentionally excludes model weights and user caches. GigaAM,
Silero VAD, and NLLB continue to load from the same external per-user caches as
the source application. The only bundled `onnx-asr` ONNX files are small audio
resampling graphs, not recognition models.

Create the isolated environment and build from the repository root:

```powershell
py -3.11 -m venv .venv-packaging
.\.venv-packaging\Scripts\python.exe -m pip install --upgrade pip
.\.venv-packaging\Scripts\python.exe -m pip install -e ".[dev,translation,packaging]"
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\console.spec
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\windowed.spec
```

Build the shared two-launcher candidate explicitly:

```powershell
# Complete safety baseline (default)
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\combined.spec

# Validated conservative profile; Torch source remains available
$env:RU_ZH_PACKAGE_PROFILE = "optimized"
$env:RU_ZH_TORCH_COLLECTION_MODE = "pyz+py"
.\.venv-packaging\Scripts\python.exe -m PyInstaller --clean --noconfirm packaging\combined.spec
Remove-Item Env:RU_ZH_PACKAGE_PROFILE
Remove-Item Env:RU_ZH_TORCH_COLLECTION_MODE
```

`combined.spec` produces `ru-zh-subtitles.exe` and
`ru-zh-subtitles-console.exe` in one directory with one `_internal` tree. The
old specs remain useful for independent diagnostic baselines. Never use the
failed experimental `pyz`-only Torch mode for distribution: real NLLB loading
requires inspectable source with this locked runtime.

Distribution evidence tools:

```powershell
.\.venv-packaging\Scripts\python.exe packaging\analyze_distribution.py <onedir> --json-output <report.json>
.\.venv-packaging\Scripts\python.exe packaging\diff_distributions.py <baseline.json> <candidate.json> --json-output <diff.json>
.\.venv-packaging\Scripts\python.exe packaging\analyze_pe_dependencies.py <onedir> --loaded-modules <sample.json> --output-dir <pe-output>
```

`capture_loaded_modules.ps1` samples one GUI process tree and stores dist paths
relative to the onedir; system modules are basenames only. Generated reports go
under ignored `data/packaging-size-analysis/`. The committed baseline template
and Torch inventory contain no machine absolute paths.

`build/`, `dist/`, `.venv-packaging/`, and generated manifests under
`data/packaging-manifests/` are ignored. Do not publish the onedir output from
this spike as an installer or release artifact.

After local validation, generate the ignored windowed manifest with concise
results, for example:

```powershell
.\.venv-packaging\Scripts\python.exe packaging\build_manifest.py dist\ru-zh-subtitles ru-zh-subtitles.exe --mode onedir-windowed --test-result "pytest=253 passed" --test-result "frozen_live=5 passed, 0 failed"
```

## Windows Sandbox validation kit

`packaging/clean_machine/` prepares a local-only, Git-ignored validation tree
and two network-disabled `.wsb` configurations. It validates the current commit,
both EXEs, relative SHA manifests, package privacy, exact approved cache files,
read-only package/model/script mappings, and a unique writable results mapping.
It never downloads models, enables Sandbox, maps the repository/user profile, or
infers CUDA support from vGPU.

See `packaging/clean_machine/README.md` and
`docs/windows-sandbox-clean-machine-validation.md`. Real generated `.wsb` files,
package/model copies, WAVs, manifests, logs, and results must stay under ignored
`data/clean-machine-validation/`; they must not be published or committed.

## CPU-only onedir

`combined_cpu.spec` is an independent two-launcher/shared-COLLECT build for the
official PyTorch CPU wheel. Create and maintain it in `.venv-packaging-cpu`;
use `requirements-cpu.txt` and `constraints-cpu.txt` so pip cannot replace the
CPU wheel with a CUDA build. Run `validate_cpu_distribution.py` against the
finished onedir. The validator requires `torch_cpu.dll` and rejects CUDA,
cuDNN, cuBLAS, NVRTC, NVJitLink, CUPTI and NVPerf runtime files.

Install both matching CPU wheels before resolving the remaining locked set:

```powershell
.\.venv-packaging-cpu\Scripts\python.exe -m pip install torch==2.10.0 torchaudio==2.10.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv-packaging-cpu\Scripts\python.exe -m pip install -r packaging\requirements-cpu.txt -c packaging\constraints-cpu.txt
```

The CPU build also requires a clean Git worktree. It generates ignored
`build/cpu-provenance/CPU_BUILD_METADATA.json`, then publishes that path-safe
metadata and the three end-user documents at the onedir root after COLLECT.
The metadata commit must match both clean HEAD and the installer
`ExpectedCommit`; rebuilding from a new commit is mandatory even when the old
onedir otherwise appears valid. `combined.spec` remains byte-identical and
contains no CPU provenance.

Do not build CPU and GPU candidates into one directory. `combined.spec`,
`optimization_profile.py` and `hooks/hook-torch.py` remain the GPU path.
Clean-machine results and exact inventory are documented in
`docs/cpu-clean-machine-recovery-validation.md`.

## GUI microphone selector packaging check

Both combined specs discover the selector through the normal
`live_subtitles.gui.app -> overlay -> microphone_selector` import graph; no
hidden import or new package dependency is required. For a local frozen check,
launch the windowed executable from a repository-external directory, open
Settings, and verify System default, an explicit device index, Refresh, running
lockout, and Stop -> change -> Start. Use `translation-doctor` from the same
external current directory to confirm the frozen runtime family.

The 0.2.0 CPU rehearsal on 2026-07-31 measured 613,257,398 bytes and 5,616 files
with zero CUDA DLL/bytes and zero product model-weight files/bytes. From a
repository-external Unicode-and-space directory, the frozen console loaded the
pinned external `modeling_gigaam.py`, recognized the real 8-second Russian WAV,
and translated it with NLLB while offline. First frozen Large CTC load was
4.853 seconds; recognition was 1.170 seconds (RTF 0.146). A separate full
pipeline process measured ASR load 3.747 seconds, NLLB load 1.655 seconds and
end-to-end RTF 1.143. Timing varies with disk cache and host load.

PyInstaller emitted only retained non-fatal warnings: optional TensorBoard was
absent, a Linux-only `/usr/lib64/libgomp.so.1` ctypes reference was ignored on
Windows, and Torch distributed compatibility modules emitted deprecations. No
CUDA wheel, GPU build, or clean-machine rerun was performed.

## End-user installer candidate

`combined_cpu.spec` is the only end-user package source. The GPU spec, Torch
hook, and optimization profile remain internal development/historical assets
and are not inputs to an installer. `packaging/installer/build_installer.ps1`
accepts a policy-valid CPU onedir, a mandatory explicit verified
`-ModelAssetsRoot`, and the expected Git commit. It verifies the official Inno
Setup 7.0.2 compiler, runs the frozen CPU doctor, fully hashes the model bundle,
creates release metadata, and compiles `cpu-only.iss` into ignored,
version-isolated `dist/installer-offline-0.2.0` output.

The build is fail-closed: dirty Git state, stale CPU provenance, or an invalid
manifest, ref, size, or SHA fails before ISCC. It never falls back to a user
cache or downloads models. Successful publication moves release/model metadata,
compiler log, build report, instructions, `SHA256SUMS.txt` and numbered slices
before setup, which remains the final success marker. Every attachment must be
below 2,000,000,000 bytes; native Inno disk spanning uses slices no larger than
1,900,000,000 bytes.

The installer is per-user, non-administrative, x64, offline by default, and
contains no CUDA runtime in the application onedir. The installer payload does
include all pinned model weights and installs them to LocalAppData. Its stable
AppId supports same-version repair and removal. Uninstall targets only the
application, installer-created shortcuts, and its uninstall key; model assets
are preserved. See `docs/cpu-only-installer-validation.md`.
