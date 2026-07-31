# Offline audio-to-translation pipeline

## Scope

`translate-audio` coordinates one short local WAV through two independent model
wrappers:

```text
WAV -> pinned GigaAM Multilingual Large CTC -> Russian text -> NLLB -> Chinese text
```

The coordinator validates that ASR returned non-empty Russian text before it
creates or calls the translator. Errors identify the ASR or translation stage.
The result records model identities, audio duration, both load and processing
times, total elapsed time, end-to-end real-time factor, actual devices, dtype,
and CUDA peak allocation. No temporary service or network API receives audio or
recognized text.

NLLB is the current default candidate. T5 and M2M100 remain selectable. The
implementation is a short-file baseline, not streaming recognition, VAD, or a
subtitle display.

## Large CTC source verification (2026-07-31)

The new default uses the official `ai-sage/GigaAM-Multilingual` `large_ctc`
snapshot at `3905cd51c3ed4e88c8edf33f3302969ba480a327`. On the existing 8-second
Russian test WAV, the official public API and the project adapter produced the
same text:

```text
здравствуйте это проверка распознавания русской речи
```

The project adapter's first measured file run loaded in 7.202 seconds and
recognized in 1.432 seconds (RTF 0.179). The complete CPU ASR-to-NLLB run loaded
ASR in 6.110 seconds, recognized in 1.289 seconds, loaded translation in 2.282
seconds, translated in 1.597 seconds, and finished in 13.166 seconds (RTF 1.646):

```text
您好,这是俄罗斯语识别检查.
```

Both offline flags were set, the ASR adapter also forced `local_files_only`, and
no runtime download occurred. These are source/research-environment results, not
new onedir, installer, or clean-machine validation.

A final CPU-only integration rerun produced Russian
`здравствуйте это проверка распознавания русской речи` and Chinese
`您好,这是俄罗斯语识别检查.`. The file-only ASR load/recognition times were
4.959/1.285 seconds (RTF 0.161). In a fresh complete process, ASR
load/recognition were 3.988/1.290 seconds, NLLB load/translation were
1.869/1.246 seconds, total processing was 10.267 seconds, and end-to-end RTF was
1.283. Both stages used CPU float32 and reported zero CUDA allocation.

## Historical RNNT fully offline verification

The first cache-only end-to-end run on 2026-07-27 used
`data/sample-retry.wav`, with both `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`:

- Audio: 8.000 seconds.
- Russian: `Здравствуйте. Это проверка распознавания русской речи.`
- Chinese: `你好,这是一个俄罗斯语识别检查.`
- ASR: `gigaam-v3-e2e-rnnt`, `CPUExecutionProvider`.
- ASR load: 2.377 seconds; recognition: 2.453 seconds.
- Translation: `facebook/nllb-200-distilled-600M`, CUDA float16.
- Translation load: 4.383 seconds; translation: 0.609 seconds.
- Total: 12.481 seconds; end-to-end RTF: 1.560.
- Peak CUDA allocation: 1189.6 MiB.
- CPU offload: none observed or configured; ASR intentionally ran on CPU and
  the NLLB model was moved directly to CUDA.
- Network: disabled by both library offline flags; the run succeeded entirely
  from the existing local caches.

The second cache-only run used a newly recorded ordinary lecture sentence:

- Audio: mono PCM16, 16 kHz, 160,000 frames, 10.000 seconds, 320,044 bytes.
- Signal: peak 1,249/32,767 (3.8118%); RMS 142.49/32,767 (0.4349%); not near
  silence, although the level was still modest.
- Russian: `Сегодня мы рассмотрим новую тему и приведём несколько простых примеров.`
- Chinese: `今天我们将讨论一个新的主题,并举出一些简单的例子.`
- ASR load: 2.127 seconds; recognition: 2.792 seconds.
- Translation load: 4.433 seconds; translation: 0.652 seconds.
- Total: 12.797 seconds; end-to-end RTF: 1.280.
- Runtime: ASR on CPU; NLLB on CUDA float16; peak CUDA allocation 1189.8 MiB.
- Offline and offload: both offline flags were set; no CPU offload was configured
  or observed.

Both ASR outputs matched the intended Russian sentences. The ordinary lecture
sample also produced a clear, relevant Chinese translation. WAV files remain
under ignored `data/` and are never committed.

## Reproduction

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
.\.venv\Scripts\python.exe -m live_subtitles translate-audio data/sample-retry.wav --translation-engine nllb --device cpu --num-beams 1
Remove-Item Env:HF_HUB_OFFLINE
Remove-Item Env:TRANSFORMERS_OFFLINE
```

Direct Silero ONNX segmentation is documented in `direct-silero-onnx-vad.md`.
The `live-terminal` command now reuses one explicitly preloaded pipeline across
all completed microphone VAD segments. Existing file commands retain their lazy
behavior and output contracts. The live integration is documented in
`live-terminal-subtitles.md`.
