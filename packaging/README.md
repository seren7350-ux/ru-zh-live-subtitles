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
