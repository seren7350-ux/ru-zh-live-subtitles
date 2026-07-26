# Architecture

## Current spike

```text
Audio file
  -> WAV validation and duration reading
  -> GigaAM-v3 E2E RNN-T through onnx-asr / ONNX Runtime
  -> Russian text
```

The current implementation recognizes one short WAV file at a time. It is not
streaming ASR and does not use VAD. The CPU implementation is a baseline for
correctness, portability, and latency measurement.

The command layer depends on narrow audio and ASR interfaces. Model creation is
lazy: importing the package, displaying help, running diagnostics, and listing
devices do not download or load the model.

## Future target

```text
Microphone
  -> audio frames
  -> VAD / segmentation
  -> ASR
  -> offline Russian-to-Chinese translation
  -> subtitle state management
  -> always-on-top GUI
```

ASR, translation, subtitle state, and GUI components must remain decoupled so
they can be profiled and replaced independently. Future performance work must
measure ASR latency and translation latency separately instead of reporting one
combined number.
