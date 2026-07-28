# Windows onedir packaging spike

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

`build/`, `dist/`, `.venv-packaging/`, and the generated root
`packaging-manifest.json` are ignored. Do not publish the onedir output from
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

The 2026-07-28 development-machine rebuild measured 658,366,169 bytes for the
CPU onedir (0 CUDA DLLs) and 3,066,444,470 bytes for the GPU onedir (22 CUDA
DLLs). Both were run from a Chinese-and-space temp directory with a minimal PATH
and external offline model caches. These local checks do not renew the earlier
CPU clean-VMware result for the selector revision and do not establish GPU
clean-machine portability.
