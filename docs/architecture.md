# Architecture

## Current independent spikes

```text
Audio file
  -> WAV validation and duration reading
  -> GigaAM-v3 E2E RNN-T through onnx-asr / ONNX Runtime
  -> Russian text
```

```text
Russian text
  -> input validation and `translate to zh:` prefix
  -> T5 translation through direct Transformers APIs
  -> Chinese text
```

The current ASR implementation recognizes one short WAV file at a time. It is
not streaming ASR and does not use VAD. Its CPU implementation is a baseline for
correctness, portability, and latency measurement. Translation accepts explicit
text input and runs independently on CPU or CUDA. The two pipelines are
intentionally not connected in this spike.

The command layer depends on narrow audio, ASR, and translation protocols. ASR
and translation model creation is lazy: importing the package, displaying help,
or running either doctor command does not download or load a model.

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
