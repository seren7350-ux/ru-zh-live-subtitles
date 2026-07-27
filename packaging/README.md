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

`build/`, `dist/`, `.venv-packaging/`, and the generated root
`packaging-manifest.json` are ignored. Do not publish the onedir output from
this spike as an installer or release artifact.

After local validation, generate the ignored windowed manifest with concise
results, for example:

```powershell
.\.venv-packaging\Scripts\python.exe packaging\build_manifest.py dist\ru-zh-subtitles ru-zh-subtitles.exe --mode onedir-windowed --test-result "pytest=253 passed" --test-result "frozen_live=5 passed, 0 failed"
```
