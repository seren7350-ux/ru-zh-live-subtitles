# Documentation map

Use this page to find the active design, build instructions, validation evidence,
and retained experiment history. Historical documents are intentionally kept
because they explain packaging and model decisions; they are not parallel sources
of current defaults.

## Start here

- [Repository layout](repository-layout.md): tracked source boundaries, ignored
  local artifacts, retention rules, and the ASR migration seam.
- [Architecture](architecture.md): current audio, ASR, translation, realtime, and
  GUI process boundaries.
- [Development notes](development.md): chronological implementation and validation
  record.
- [Model assets setup](model-assets-setup.md): pinned local model cache contract.

## Runtime components

- [Direct Silero ONNX VAD](direct-silero-onnx-vad.md)
- [Live microphone VAD](live-microphone-vad.md)
- [Offline audio-to-translation pipeline](offline-audio-translation-pipeline.md)
- [Live terminal subtitles](live-terminal-subtitles.md)
- [Always-on-top subtitle overlay](always-on-top-subtitle-overlay.md)
- [Translation model selection](translation-model-selection.md)

## Distribution and current evidence

- [CPU-only distribution policy](cpu-only-distribution.md)
- [Self-contained CPU offline installer](self-contained-offline-installer.md)
- [CPU-only installer validation](cpu-only-installer-validation.md)
- [CPU clean-machine recovery validation](cpu-clean-machine-recovery-validation.md)
- [Windows Sandbox validation kit](windows-sandbox-clean-machine-validation.md)

## Retained experiment history

- [Translation model comparison](translation-model-comparison.md)
- [Windows packaging feasibility spike](windows-packaging-spike.md)
- [Windows onedir size optimization](windows-package-size-optimization.md)

These history documents preserve measured baselines and rejected approaches.
Current commands and support boundaries come from the repository root README,
the packaging README files, and the current distribution documents above.
