# Always-on-top subtitle overlay

## Scope

The Tkinter overlay presents the existing ordered Russian/Chinese subtitle
events. `overlay-demo --duration 0` is model-free and microphone-free; it is the
preferred interaction test command. `live-overlay` connects the same view to
the existing live pipeline. This work does not implement native streaming ASR,
click-through, global shortcuts, PowerPoint/Acrobat integration, or packaging.

## Fixed interaction model

The root always contains a persistent 38 px control bar and a subtitle content
area. The bar exposes Drag, status, Start/Stop, Pinned/Unpinned, Settings, and
Exit. The old compact, expanded, and captions-only modes no longer exist.
Starting or stopping a session changes the primary button state but never hides
the bar.

## Resizing and complete subtitle history

Version 0.3.0 keeps native Tk/Windows resizing enabled whenever Borderless is
off. In Borderless mode, a seven-pixel root-edge hit area maps the four edges
and four corners to the corresponding resize cursor. A drag computes geometry
from the captured pointer/window origin, clamps it to 520 x 180 pixels, and
marks the position preset as floating. The explicit Drag region ignores resize
hits, and subtitle content is not a window-drag target.

The subtitle area is a Canvas-backed vertical history. Every retained entry has
separate complete Russian and Chinese labels; there is no string slicing,
character limit, or ellipsis. Canvas Configure events set each label's
wraplength from the current actual content width and ignore an unchanged size.
The user's font setting is the preferred maximum. Each new Russian/Chinese pair
is measured after Tk lays it out, but content never changes the user-selected
root-window geometry. The newest pair instead reduces its view fonts as needed,
down to 8 px Russian / 12 px Chinese. If an exceptional pair still exceeds the
viewport, all text remains intact in the internal scroll area and automatic
following starts at that pair's beginning rather than hiding its first lines.
Increasing the height restores the configured size. Font changes rebuild the
labels at the same width. New entries follow the bottom by default, scrolling
upward pauses that follow behavior, and Clear or a new session restores an empty
bottom-following state. The persistent control bar and the separate error row
remain outside the scrolling area.

Settings has one responsibility: show or hide the SettingsPanel. Root
right-click invokes the same method as a shortcut. A single root binding covers
descendant widgets through Tk's bindtags; binding both root and every child
would execute the toggle twice on one click.

## SettingsPanel lifecycle

The panel is one lazily created `Toplevel` owned by the subtitle root. Its close
protocol and Escape handler call `withdraw()`, preserving the controls and
values without stopping the subtitle session. A later open checks
`winfo_exists()`, uses `deiconify()`, restores its remembered geometry, applies
the root's current topmost value once, and lifts once. If the window manager has
actually destroyed it or a Tk call reports a stale reference, the overlay clears
that reference and creates one replacement.

The panel contains Start/Stop, Clear, Show Russian, Always on top, Borderless,
top/bottom/floating position presets, opacity, Chinese and Russian font sizes,
and Exit. It uses no `grab_set`, `focus_force`, background Tk calls, ordinary
`tk.Menu`, or repeating lift/topmost timer.

## Borderless and topmost behavior

Borderless toggles the original root with one `root.overrideredirect(value)`.
Before that call the overlay stores geometry and withdraws the settings panel.
One `after_idle` callback restores geometry, topmost, and opacity, then refreshes
labels. The root, widget tree, bindings, subtitle history, controller, and live
session are not rebuilt.

Pinned/Unpinned is always available on the main bar. An explicit change applies
`root.attributes("-topmost", value)` immediately and synchronizes an existing
panel once. Unpinning does not stop processing, and repinning does not start a
new session. Rendering subtitles never calls focus, focus_set, focus_force,
grab_set, lift, or topmost APIs.

The top, bottom, and floating choices are ordinary position presets. They do not
reserve Windows workspace for PowerPoint, Acrobat, or any other application.

## Native crash analysis

Before this stabilization, a real settings/Borderless click killed the Python
process with no Python traceback or stderr output. Windows Application Error
event 1000 identified `tk86t.dll` 8.6.2.12, access violation `0xc0000005`, fault
offset `0x0000000000024391`, and report ID
`b3147d68-cd48-4a91-82e7-9c8dc9393cf9`.

The old panel was a transient Toplevel that could be destroyed by a pending
FocusOut callback while the same GUI callback changed the root's
`overrideredirect` state and immediately reapplied window attributes. The Python
field still represented the panel while Tk was tearing down its native window.
The first context request created a valid panel; the Borderless transition then
invalidated that root/transient relationship, so the following operation entered
Tk with stale native lifecycle state. Because the access violation occurred in
Tk itself, `root.report_callback_exception` could not produce a Python exception
type, source file, or line. The handler remains installed for ordinary future Tk
callback exceptions and requests a non-blocking safe stop.

The replacement avoids the collision: the panel is withdrawn rather than
destroyed, FocusOut no longer owns its lifecycle, borderless state restoration
waits for the Tk idle boundary, and a stale panel is detected before use.

## Automated and screen validation

The fake-Tk suite covers module import, fixed layout state, persistent controls,
panel creation/withdraw/reopen/recreate, direct Stop, topmost synchronization,
ten borderless transitions, geometry/topmost/opacity retention, one context
binding, callback-error handling, and non-blocking Exit. Network, models, and
microphone access are replaced by fakes.

Real screen input verified:

- Settings opened, hid, and reopened without changing the subtitle layout or
  button label; only one settings window was visible.
- Right-click in subtitle content and the control bar toggled the same panel.
- Stop remained visible and worked without Settings/right-click; Start restarted
  one demo session.
- Unpin and repin preserved the running demo and did not steal keyboard focus.
- Twenty mixed rounds covered five Settings show/hide pairs, five context-click
  show/hide pairs, five pin/unpin pairs, and five Stop/Start pairs (40 clicks).
- One real Windowed-to-Borderless change remained responsive, retained its bar,
  and produced neither stderr nor a new Application Error event.
- Exit closed both test processes; a new demo launched and exited cleanly again.

The Windows desktop-control API cannot enumerate or target the root once Tk sets
`overrideredirect(True)`. It therefore could not drive the reverse click or ten
complete screen-level Borderless round trips. The ten-transition fake-Tk test
does not replace that missing visual check. At that intermediate stabilization
stage, no 60/120-second live test or external-application test had yet been
performed; later results are recorded below.

## User acceptance

On 2026-07-27 the user reported A1–A5 and B1–B5 complete and passing, and
explicitly waived C1–C5 because Acrobat was not installed. This is separate from
Codex's mechanical screen-control regression above; no user screenshot was
provided or claimed.

### A. Visual and interaction: passed

- A1: Start/Stop, Pinned/Unpinned, Settings, and Exit were easy to understand.
- A2: Settings opened and hid naturally, its labels were clear, and the subtitle
  area did not change without purpose.
- A3: Chinese/Russian fonts, line spacing, wrapping, opacity, background, and
  control-bar appearance were acceptable.
- A4: Repeated real Borderless/Windowed transitions preserved position,
  opacity, and topmost state; did not duplicate SettingsPanel; and produced no
  crash or terminal error.
- A5: Stop remained directly usable from the main bar after Start, without
  Settings or right-click.

### B. PowerPoint compatibility: passed

The user confirmed B1–B5 in slide-show mode: pinned subtitles remained visible,
the overlay did not continuously take keyboard focus, PowerPoint remained usable
after Unpin, the repinned SettingsPanel was not covered, and PowerPoint context
menus and slide-show controls remained usable.

### C. Acrobat compatibility: waived

The validation machine does not have Acrobat. The user explicitly allowed these
checks to be omitted, so C1–C5 were not executed and are not claimed as passed.
This waiver does not change the PowerPoint or general interaction result.

These results accept the overlay-demo visual and PowerPoint interaction checks.
They do not by themselves establish live audio/model stability, native streaming
ASR, plugin integration, packaging readiness, or production readiness.

## Live-process responsiveness fix

Real cached model preparation initially starved the Tk mainloop even though it
ran in a Python thread. The live overlay now keeps Tk in the parent process and
runs one unchanged `LiveTerminalSession` in a spawned child process. Immutable
events and a compact final summary cross a bounded multiprocessing queue. No
child thread calls Tk.

The first implementation exposed two Windows shutdown defects during a real
three-second diagnostic: shared locked counters and a daemon waiting forever on
a process event could leave the GUI unable to drain the queue after the child
exited. The final transport uses raw single-writer counters, and the child sets
the stop event in `finally` before closing its queue. The corrected real
diagnostic reported a 0.073-second maximum heartbeat delay, queue HWM 2,
overflow 0, 94/94 audio blocks, no audio loss, zero temporary residue, and clean
worker/microphone release.

## Real offline GUI validation (2026-07-27)

Every command below ran with `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, device 1 (`麦克风 (HyperX Cloud III)`), cached Silero
VAD/GigaAM/NLLB assets, GigaAM on CPU ONNX Runtime, and NLLB on CUDA float16.
No model was downloaded. The system temporary-file baseline and final count for
`ru-zh-live-subtitles-*.wav` were both zero.

### 60-second run

Command:

```powershell
.\.venv\Scripts\python.exe -m live_subtitles live-overlay --device 1 --duration 60 --translation-engine nllb --translation-device cuda --num-beams 1 --show-russian --topmost --borderless --auto-start
```

Five ordered subtitles were displayed with no duplicate, omission, or failure:

| # | Russian | Chinese |
| ---: | --- | --- |
| 1 | Здравствуйте. Сегодня мы начинаем новую лекцию. | 你好,今天我们开始了新的讲座. |
| 2 | Сначала рассмотрим основную идею. | 首先,让我们来看看一个基本的想法. |
| 3 | Затем приведём несколько простых примеров. | 然后我们举几个简单的例子. |
| 4 | Если возникнут вопросы, мы обсудим их после занятия. | 如果有问题,我们会在课后讨论. |
| 5 | Перейдём к следующему слайду. | 我们再转到下一个幻灯片. |

GUI events were 10/10, queue HWM/final/capacity 2/0/256, overflow 0,
displayed/failed 5/0, render latency average/median/P95
0.030/0.026/0.054 seconds, and maximum heartbeat delay 0.077 seconds. The
60.019-second session processed 1,874/1,874 blocks; audio and segment queue HWMs
were 1/320 and 1/8. Dropped blocks, sequence gaps, PortAudio statuses, backlog,
and queue wait were all zero. Processing average/median/P95 was
0.724/0.569/1.200 seconds; RTF was 0.211/0.207/0.308; RU latency was
0.628/0.611/0.680 seconds; ZH latency was 1.232/1.075/1.712 seconds.

VAD/ASR/tokenizer/translation load counts were 1/1/1/1, load times were
0.110/1.923/3.685 seconds, and CUDA peak allocation was 1,189.6 MiB. Five
temporary WAVs were created and deleted with zero residue. Both workers exited,
the microphone closed, and no live-overlay process remained.

### Stop, restart, stop

The real duration-zero session was stopped from the always-visible main bar,
restarted from the same bar, stopped again, and exited. The two recognized
results were:

1. `Здравствуйте. Это первый запуск. Сейчас мы остановим распознавание.` →
   `你好,这是第一次发射,我们现在停止识别.`
2. `Это второй запуск после остановки.` → `这是停车后的第二次发射.`

The two sessions lasted 16.658 and 13.998 seconds and processed 519 and 436
blocks. Each loaded VAD/ASR/tokenizer/translation exactly once, created and
deleted one temporary WAV, released both workers and the microphone, and left no
process. This is the intended lifecycle: the second Start creates a new child
and reloads cached model objects once; models are not reused across a completed
session. No concurrent session, duplicate microphone, duplicate subtitle, or
temporary residue was observed.

### Exit during model preparation

Exit was clicked while the real child was preparing cached models. The request
remained responsive, no `ListeningEvent` was emitted, the microphone never
opened, no subtitle or temporary WAV was created, and the child completed
necessary cleanup before the window closed. GUI events were 4/4, queue HWM 3,
overflow 0, and maximum heartbeat delay 0.015 seconds. No traceback or process
residue remained.

### 120-second stability

The first 120-second run exercised Settings show/hide, Show Russian, opacity,
Unpin, and Pin while subtitles continued. It was technically stable but only
five utterances were spoken, so it did not meet the eight-subtitle threshold. A
second run produced seven subtitles and was also retained as a non-passing
attempt. Neither result was represented as a pass.

The final run used the same command with `--duration 120` and produced 11/11
successful ordered subtitles:

| # | Russian | Chinese |
| ---: | --- | --- |
| 1 | Здравствуйте. Сегодня хорошая погода. | 你好,今天天气很好. |
| 2 | Здравствуйте. | 您好,您好. |
| 3 | Мы продолжаем нашу лекцию. | 我们继续讲. |
| 4 | Сначала повторим основные результаты. | 首先,我们要重复基本的结果. |
| 5 | Теперь рассмотрим новый пример. | 现在,我们来看一个新的例子. |
| 6 | Обратите внимание на это условие. | 请注意这个条件. |
| 7 | Если есть вопросы | 如果有任何问题 |
| 8 | Затайте их, Боже. | 住他们,上帝啊. |
| 9 | Перейдём к следующему слайду. | 我们再转到下一个幻灯片. |
| 10 | Спасибо за внимание. | 谢谢您的注意. |
| 11 | До свидания. | 见面. |

Segments 7–8 show an ordinary recognition/segmentation quality error, not a
pipeline failure; both were processed and displayed in order. GUI events were
16/16, queue HWM/final/capacity 2/0/256, overflow 0, displayed/failed 11/0,
render latency average/median/P95 0.033/0.029/0.055 seconds, and maximum
heartbeat delay 0.019 seconds. The 120.018-second session processed 3,749/3,749
blocks. Audio/segment queue HWMs were 1/320 and 1/8. Dropped blocks, sequence
gaps, PortAudio statuses, backlog failures, and queue wait were zero.

Processing average/median/P95 was 0.483/0.470/0.860 seconds; RTF was
0.184/0.179/0.291; RU latency was 0.600/0.599/0.626 seconds; ZH latency was
0.989/0.974/1.369 seconds. Model counts were 1/1/1/1, VAD/ASR/translation loads
were 0.118/2.106/4.071 seconds, and CUDA peak allocation was 1,189.4 MiB.
Process-tree working set/private memory was 5,327.1/8,594.6 MiB at 16:38:09
and 5,328.2/8,595.3 MiB at 16:39:04, a late stable-window change of only
+1.1/+0.7 MiB. Eleven temporary WAVs were created and deleted with zero
residue; both workers and the microphone released, and no child remained.

The known Transformers `max_new_tokens`/`max_length` warning remained. There
was no Tk crash, Tcl error, traceback, PortAudio overflow, queue accumulation,
or cleanup failure. Combining the previously accepted interaction/PowerPoint
checks, the interaction operations observed during the first stability run, and
the final passing technical run, the documented status is:

**GUI overlay prototype accepted for packaging evaluation.**

This is not a production-ready claim. The application remains a VAD-segmented,
short-WAV offline ASR and offline translation overlay prototype, not native
streaming ASR, a PowerPoint/Acrobat plugin, a packaged product, click-through
overlay, or subtitle-history service.

## Frozen onedir follow-up

The subsequent PyInstaller 6.21.0 onedir spike preserved the same parent-Tk and
spawned-worker boundary. A real cache-only frozen GUI run produced 5/5 ordered
subtitles, GUI events 10/10, render P95 0.060 seconds, heartbeat maximum 0.019
seconds, RTF P95 0.286, and RU/ZH latency P95 0.698/1.656 seconds. It processed
1,875/1,875 audio blocks with audio/segment queue HWMs 1/320 and 1/8. Loss,
gaps, PortAudio statuses, backlog, temporary residue, and residual processes
were all zero; model counts remained 1/1/1/1 and CUDA peak was 1,189.6 MiB.

The frozen entry called `multiprocessing.freeze_support()` before importing the
GUI or model stack. Process inspection showed one main executable and one
expected `--multiprocessing-fork` child, with no recursive GUI. The exact frozen
captions, build footprint, logs, warning analysis, and security boundary are in
`windows-packaging-spike.md`. The resulting status is **Onedir GUI build
validated on development machine**, not a clean-machine, signed, installer, or
production-ready claim.

## Microphone selector follow-up (2026-07-28)

Live Settings now begins with a readonly `ttk.Combobox`, Refresh button, and
selection status. `System default` resolves at each Start; explicit entries show
index, name, input channels, sample rate, and the default marker. Internally the
combobox uses index-bearing choices and never infers identity from label text.
Refresh preserves a surviving index and marks a disappeared selection
unavailable instead of choosing another specific endpoint.

Preparing, Listening, Stopping, closing, or an alive process disables both
controls and displays `Stop subtitles before changing the microphone.` Stop,
worker exit, selection change, and a new Start are required. Invalid startup
selection is rejected before Preparing or child-process creation. The panel is
still one lazy persistent Toplevel closed with `withdraw()` and does not hold
the controller. `overlay-demo` receives no microphone callbacks, does not show
the region, and does not enumerate or open audio devices.

Screen testing exercised first enumeration, System default, explicit indexes 1
and 2, Refresh retention, running lockout, Stop re-enable, and Stop -> change ->
Start. Listening used the actual HyperX and Realtek names. Source, CPU onedir,
and GPU onedir displayed real RU/ZH captions. Render P95 was
0.035/0.039/0.041 s and heartbeat maximum 0.177/0.123/0.147 s for
source/CPU/GPU. GPU RTF P95 was at most 0.906 with RU/ZH P95 at most
0.614/1.431 s. All runs had zero loss, gaps, PortAudio status, backlog, GUI
overflow, temporary WAV residue, and residual process. One CPU first-session
ASR segment failed during Stop; the second CPU session and both GPU sessions had
no failed caption.

These are development-machine validations. This revision was not revalidated
in VMware or another clean environment, and no selector persistence or hot
switching was introduced.

## Installer model-assets state

The installed shortcut opens the same overlay in CPU, offline, no-auto-start
mode. After the root exists, a lightweight preflight sets the persistent status
to Ready or Model setup required. The compact handle remains visible in both
states. Settings contains a Model assets region with Recheck, Open model folder,
and Open model setup instructions. These callbacks run on the existing GUI
thread and do not add a second Tk, modal grab, focus force, or polling loop.

Start repeats the preflight. If any pinned Silero/GigaAM/NLLB asset is missing,
Start remains blocked before process, model, or microphone creation and offline
mode performs no download. Once assets pass, microphone selection and the
existing Stop -> change -> Start lifecycle are unchanged.
