# Repository and local artifact layout

This document separates version-controlled inputs from machine-local generated
artifacts. Paths are relative to the repository root. Model weights, virtual
environments, build outputs, recordings, logs, and machine-specific validation
evidence never enter Git.

## Tracked repository

| Path | Responsibility |
|---|---|
| `.github/workflows/` | Windows CI for source and packaging-source tests. |
| `benchmarks/` | Small, reviewable text fixtures for translation comparisons. |
| `src/live_subtitles/` | Application source. Runtime subsystems remain separated by package. |
| `tests/` | Unit, contract, packaging-policy, and source-validation tests. |
| `packaging/` | PyInstaller specs, hooks, CPU policy, model-bundle validation, installer sources, and clean-machine tooling. |
| `docs/` | Active design/build documents and retained experiment history. |
| `pyproject.toml` | Python package metadata and dependency groups. |
| `THIRD_PARTY_NOTICES.md` | Runtime and model attribution boundaries. |

`docs/README.md` is the documentation index. Historical validation and experiment
documents remain tracked because their measurements explain current packaging
decisions; they should not be treated as current configuration files.

## Current ASR boundary

The current backend remains GigaAM-v3 E2E RNN-T through `onnx-asr` and
`CPUExecutionProvider`. This cleanup does not change the model, revision, decoder,
audio format, or output behavior.

| Path | ASR responsibility |
|---|---|
| `src/live_subtitles/asr/base.py` | Backend-neutral lifecycle, errors, metrics, and `SpeechRecognizer` protocol. |
| `src/live_subtitles/asr/gigaam_onnx.py` | Current GigaAM-v3 RNNT/ONNX loading and short-WAV recognition. |
| `src/live_subtitles/config.py` | Current default backend model name and provider. |
| `src/live_subtitles/model_assets.py` | Pinned external asset identities, revisions, file sets, sizes, and readiness checks. |
| `src/live_subtitles/pipeline/offline_file.py` | Backend-neutral ASR/translation orchestration. |
| `packaging/model_bundle.py` | Installer-time validation and metadata for the pinned model payload. |

The pipeline depends on the protocol, not on RNNT decoding details. The concrete
GigaAM class remains the default factory until a future migration is separately
implemented and validated.

## Next ASR backend migration

A later GigaAM Multilingual Large CTC change should be a separate feature branch.
The expected entry points are:

1. add a dedicated CTC backend module under `src/live_subtitles/asr/` that
   implements `SpeechRecognizer`;
2. add its tokenizer/vocabulary, preprocessing, decoder, runtime, and metrics
   tests without changing the protocol consumers;
3. add a distinct pinned `ModelAssetSpec` rather than reusing the RNNT identity;
4. update model-bundle and installer validation only after the new asset contract
   is fixed;
5. switch the default explicitly after file, live, GUI, CPU packaging, and clean-
   machine validation pass.

VAD, translation, GUI, microphone selection, segment queues, and process control
must not need model-specific rewrites.

## Ignored local layout

| Path | Category | Retention policy |
|---|---|---|
| `.venv/` | Current development environment | Preserve while the baseline is supported. |
| `.venv-packaging/` | Historical/internal GPU packaging environment | Preserve for reproducible packaging evidence. |
| `.venv-packaging-cpu/` | CPU packaging environment | Preserve; it is the current end-user build environment. |
| `build/` | PyInstaller work directories and CPU provenance | Regenerable, but retain current provenance while a matching dist is retained. |
| `dist/ru-zh-subtitles-cpu/` | Current CPU onedir | Preserve with its matching CPU metadata. |
| `dist/ru-zh-subtitles*/` | Historical/internal GPU and console onedirs | Archive or delete only after their evidence is no longer required. |
| `dist/installer-offline/` | Final teacher delivery and build evidence | Preserve. Never clean recursively. |
| `dist/installer/` | Historical model-less installer | Retain as history; never deliver it alone. |
| `data/clean-machine-validation/staging/` | Canonical package/model/scripts staging | Preserve at its existing path. |
| `data/clean-machine-validation/cpu-run-*/` | Independent clean-machine run captures | Preserve as validation evidence. |
| `data/packaging-size-analysis/` | GPU/onedir size experiments and reports | Preserve while historical conclusions are cited. |
| `data/final-main-validation/` | Final baseline validation and model backup | Preserve. |
| `data/course-delivery/` | Local reports and other teacher-facing documents | Preserve; excluded from Git. |
| `data/packaging-manifests/` | Generated local onedir manifests | Regenerable; archive useful provenance by commit. |

The final teacher installer is
`dist/installer-offline/ru-zh-live-subtitles-cpu-offline-0.1.0-setup.exe`.
Its adjacent build report, release/model metadata, compiler log, instructions,
and checksum records belong to the same retained delivery set.

## Safe cleanup rules

- Never use broad recursive cleanup against `build`, `dist`, `data`, a model
  root, or a virtual environment.
- Preserve canonical model staging, model manifests, current CPU provenance,
  teacher delivery files, model backups, clean-machine results, CUDA failure
  evidence, CI diagnostics, and installer-hardening evidence.
- A generated cache or build directory may be deleted only when its producing
  command is known, no retained result references it, and the matching current
  output/provenance is preserved.
- Prefer an atomic move into an ignored archive over copying multi-gigabyte model
  trees.
- Record file count, byte count, and important hashes before and after moving a
  retained artifact.
- Keep submitted documentation free of user names, credentials, tokens, and
  machine-specific absolute paths.
