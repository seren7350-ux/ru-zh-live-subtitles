# Architecture

## Current short-file pipeline

The direct VAD file foundation is independent of ASR and translation:

```text
Strict PCM16 mono 16 kHz WAV
  -> project-owned WAV reader
  -> float32 chunks (512 samples / 32 ms)
  -> official Silero VAD 6.2.1 ONNX model / CPUExecutionProvider
  -> recurrent state + 64-sample context carried between chunks
  -> probability hysteresis and padding state machine
  -> immutable speech segments
```

`vad-prepare` downloads a single pinned official PyPI wheel as data, verifies its
SHA-256, reads only the selected model and license ZIP members, verifies the
model SHA-256, and atomically writes a per-user cache. It does not import or
execute wheel code. The runtime uses NumPy and ONNX Runtime directly; neither
`silero-vad`, TorchAudio, nor Torch participates in VAD inference.

The migrated offline audio-to-translation path is:

```text
Local WAV file
  -> PCM WAV validation, mono downmix, and 16 kHz resampling
  -> official ai-sage/GigaAM-Multilingual Large CTC at immutable commit
  -> official PyTorch/TorchAudio feature extractor and CTC decoder
  -> non-empty Russian text check
  -> translator factory (default: NLLB; optional: T5 or M2M100)
  -> direct local Transformers generation
  -> Chinese text
```

ASR and translation remain independent components. The pipeline module only
coordinates their narrow interfaces and combines timing data; it does not copy
model logic. Both wrappers are lazy, so importing the package, displaying help,
or running a doctor command does not load a model. A pipeline instance creates
at most one ASR wrapper and one selected translator, allowing the same loaded
objects to be reused in a future long-running process.

The current commands handle local WAV files. GigaAM defaults to CPU and may use
CUDA only when explicitly selected and available, while translation independently
selects CUDA when `device=auto`. No audio or text is sent to a network service.
The ASR adapter resolves only the pinned local snapshot, forces offline mode,
and uses `local_files_only=True`; it never falls back to the legacy RNNT model.

The project calls the official model's acoustic forward path and `_decode` after
project-owned PCM WAV conversion. This avoids an undeclared system `ffmpeg`
dependency while preserving the official CTC implementation: argmax labels,
blank ID 70 removal, adjacent-repeat collapse, and the official 70-character
vocabulary. The adapter does not perform a second CTC collapse. Silero remains
responsible for keeping live segments below the official 25-second short-audio
limit; the gated Pyannote long-form path is not used.

T5, M2M100, and NLLB are not loaded together. NLLB is the current default
general-purpose candidate, while the other adapters remain selectable for
comparison and compatibility. Mathematical terminology is not a core project
acceptance requirement; earlier comparison failures remain documented as
research observations rather than a pipeline blocker.

## Current live terminal prototype

```text
PortAudio callback
  -> bounded audio queue
  -> one Silero VAD/segmenter worker
  -> immutable AudioSegment
  -> bounded segment queue (default 8, range 1..32)
  -> one serial GigaAM/translation worker
  -> ordered Russian and Chinese terminal results
```

This is a **VAD 分段后调用短音频离线 ASR 的近实时终端字幕原型**. Each segment
is temporarily encoded as mono PCM16 16 kHz WAV in the system temporary
directory, closed before GigaAM reads it, and removed in `finally`. No segment
audio is written under `data/`, and no temporary path is printed.

The ASR/translation worker is the only caller of the reusable preloaded GigaAM
and translator instances. It never processes segments in parallel. Individual
ASR/translation errors produce ordered failed results and do not prevent later
segments. Audio loss, either queue filling, PortAudio overflow, sequence gaps,
worker death, preparation failure, or finite join timeout stops the session.

Both queues use non-blocking producer writes and explicit fatal backpressure;
the PortAudio callback remains unchanged. Percentile windows and retained
subtitle results are capped at 8,192 entries.

## Current subtitle overlay

```text
GUI main thread
  -> one Tk root
     -> persistent control bar
     -> subtitle content area
     -> one optional persistent SettingsPanel Toplevel
  <- immutable events from one bounded multiprocessing queue
Spawned live-session process
  -> cached model preparation
  -> PortAudio callback and bounded audio queue
  -> VAD/segmenter worker
  -> bounded segment queue
  -> serial GigaAM/translation worker
```

The overlay has no compact, expanded, or captions-only layout state. Its main
control bar remains present in both borderless and normal-window modes. Settings
and root right-click both call the same panel toggle; they do not alter the
subtitle layout or session state.

The SettingsPanel is created lazily, retained, and closed with `withdraw()`.
Reopening uses `deiconify()`, reapplies the current topmost value once, and calls
`lift()` once. A destroyed or stale panel reference is discarded before a new
panel is created. Borderless changes use one `overrideredirect()` call on the
existing root followed by one idle callback that restores geometry, topmost,
and opacity. Neither operation rebuilds widgets or creates a new live session.

Tk calls stay on the main thread. Model preparation, audio capture, VAD, ASR,
and translation stay in the spawned child. Background work emits immutable
queue events; subtitle rendering never changes focus, grabs input, or repeatedly
reapplies window-manager state. Raw single-writer process counters avoid a
Windows synchronization lock being abandoned during child shutdown. Stop sets
a process event without blocking Tk, and Exit polls completion from the Tk event
loop before destroying the root.

Only one child may be alive at a time. Stop releases its microphone and workers;
a later Start intentionally creates a fresh child and reloads each model once
from the existing local caches. It does not reuse model objects across stopped
sessions, create concurrent microphones, or persist subtitle text.

## Future target

```text
always-on-top GUI -> external application validation -> packaging
```

The current implementation is not native streaming ASR. GigaAM starts only
after VAD closes a short segment.
ASR, translation, subtitle state, and GUI must remain decoupled so they can be
profiled and replaced independently. Future performance work must report ASR,
translation, and orchestration latency separately as well as end-to-end delay.

## Frozen Windows boundary

The onedir spike adds a thin frozen shell around the same architecture. A
minimal entrypoint calls `multiprocessing.freeze_support()` before importing
the project, then dispatches to the existing CLI. Tk remains in the parent EXE;
the existing spawned live worker re-enters that EXE through PyInstaller's child
argument handler and never creates another GUI.

Bundled resources, writable user data, and models remain separate:

```text
onedir static code/runtime -> unified frozen resource helper
Hugging Face models        -> external user Hugging Face cache
Silero VAD                 -> external LocalAppData cache
temporary segments         -> system temporary directory
diagnostics                -> LocalAppData rotating log
```

No model lookup uses `_MEIPASS`, no runtime output targets `dist`, and current
working directory is not an architectural dependency.

## Live capture concurrency boundary

```text
PortAudio callback
  -> immutable sequenced AudioBlock
  -> bounded FIFO queue
  -> single VAD/segmenter worker
  -> immutable AudioSegment results
  -> non-blocking bounded segment queue
  -> serial ASR/translation worker and terminal reporting
```

The callback has a strict real-time boundary: validate, copy, timestamp, and
`put_nowait` only. Queue full, PortAudio input overflow, and sequence gaps are
fatal because continuing would hide missing audio. The worker is the sole owner
of VAD recurrent state and the segmentation state machine. The coordinator owns
stream lifetime, termination, joining, summary generation, and optional writes.
This separation keeps microphone transport independent from future ASR,
translation, subtitle state, and GUI components.

## Frozen Windows layout

```text
ru-zh-subtitles.exe (windowed) -------+
                                      +--> one shared _internal dependency tree
ru-zh-subtitles-console.exe ----------+    (Python, Tk, ONNX Runtime, Torch/CUDA)
```

`packaging/combined.spec` deliberately uses one analysis/PYZ/dependency collect
for both launchers. The executable basename still selects console or windowed
dispatch in the existing entrypoint, whose first runtime action remains
`multiprocessing.freeze_support()`. Model caches and runtime logs remain outside
the distribution. The size-analysis and PE tools are packaging-time utilities,
not application dependencies. Detailed boundaries and validation are in
`windows-package-size-optimization.md`.

## Clean-machine validation boundary

Windows Sandbox validation is packaging infrastructure, not an application
runtime layer. The generated configuration maps the combined onedir, a minimal
script set, and the exact Silero/GigaAM/NLLB staging read-only. Only a unique,
empty results directory is writable. The repository, virtual environments,
user profile, complete Hugging Face cache, and model download paths remain
outside the guest boundary; networking is disabled.

The cache-backed startup copies approved assets from the read-only mapping into
the disposable guest's writable caches and sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. This preserves the host cache and accommodates
libraries that create cache metadata or lock files. vGPU configuration only
exposes a possible graphics path: actual frozen Torch CUDA detection determines
CUDA versus CPU validation, never the vGPU setting itself. See
`windows-sandbox-clean-machine-validation.md` for the exact trust boundary and
the current Windows Home blocker.

## Separate CPU and GPU package families

The frozen runtime now has two deliberately separate candidate families. The
existing `combined.spec` route remains the CUDA/GPU development-machine build.
`combined_cpu.spec` is built from an independent CPU-wheel environment and
rejects CUDA runtime DLLs before and after collection. Neither route silently
falls back into the other, and they never share one dist directory.

The accepted CPU staging was generated from original host caches, exposed
read-only, and validated twice from the same restored, network-disabled VMware
snapshot. The GUI uses prepared short-file ASR/translation workers; it is still
not native streaming ASR. Cold model-start RTF and prepared live-segment latency
are recorded separately. See `cpu-clean-machine-recovery-validation.md`.

## GUI microphone selection boundary

The live settings panel does not query PortAudio directly and does not own the
process controller:

```text
recording.list_input_devices/select_input_device
  -> no-Tk MicrophoneSelectorModel (identity = PortAudio index)
  -> GuiRuntime callbacks
  -> persistent SettingsPanel ttk.Combobox
  -> LiveProcessOverlayController.set_device_index
  -> dataclasses.replace(frozen LiveWorkerConfig)
  -> next spawned live worker
```

Enumeration occurs only when the live SettingsPanel is first created or the
user clicks Refresh. Rendering does not poll devices. Labels are presentation
only; duplicate names remain distinct because combobox positions map to device
indexes. `System default` maps to `None`, so startup uses
`select_input_device(None)` instead of pinning an earlier default.

GuiRuntime validates the selection before `begin_session()` and before child
process creation. A disconnected or invalid endpoint cannot enter Preparing,
load models, or open a microphone. Config replacement is allowed only after the
worker fully stops. The panel contains no controller reference, background Tk
thread, or device poll. The demo controller receives no selector callbacks, so
`overlay-demo` retains its model-free and microphone-free boundary.

## Installed offline model boundary

The installed application keeps code and models separate:

```text
per-user CPU {app}
  -> process-local offline policy
  -> fast model-assets preflight (no ML imports)
  -> user-controlled Start
  -> CPU VAD / ASR / NLLB workers

%LOCALAPPDATA%\ru-zh-live-subtitles\models
or an explicit/default Hugging Face cache
  -> pinned Silero, GigaAM and NLLB assets
```

`ModelAssetsModel` performs a one-shot check after the Tk root exists and again
before Start. It checks fixed revisions, exact `refs/main` form, required files,
and known sizes without importing Torch, Transformers, ONNX Runtime, or model
modules. Missing assets leave the GUI alive but prevent worker and microphone
creation. Settings owns Recheck/Open-folder/Open-instructions callbacks; it adds
no second Tk, grab, focus forcing, background Tk calls, or polling.

`--offline` sets only process-local `HF_HUB_OFFLINE` and
`TRANSFORMERS_OFFLINE` before worker creation. The installer contains no model
weights and uninstall never targets the external model root. The CPU installer
is the end-user candidate; the GPU graph remains internal only.
