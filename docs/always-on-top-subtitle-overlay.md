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
does not replace that missing visual check. No 60/120-second live test,
PowerPoint test, or Acrobat test was performed.

## Remaining human acceptance

Use `python -m live_subtitles overlay-demo --duration 0`. Report every item as
pass/fail and include a screenshot plus terminal error for any failure.

### A. Visual and interaction

- A1: Confirm Start/Stop, Pinned/Unpinned, Settings, and Exit are immediately
  understandable; identify any unclear button.
- A2: Open/hide Settings and confirm its position and labels feel natural and it
  does not unexpectedly resize or obscure the subtitle area.
- A3: Judge Chinese/Russian font sizes, line spacing, wrapping, opacity, dark
  background comfort, and control-bar height; state preferred values.
- A4: Turn Borderless off and on, repeat ten round trips, and confirm the window
  stays on screen, preserves opacity/topmost/position, never duplicates the
  panel, and prints no traceback; state the preferred default mode.
- A5: Start, then stop directly from the main bar without opening Settings;
  confirm Stop is prominent and easy to find.

### B. PowerPoint compatibility

- B1: In slide show mode with Pinned enabled, confirm subtitles remain visible.
- B2: Click PowerPoint and confirm the overlay does not repeatedly take keyboard
  focus.
- B3: Confirm Unpinned is easy to use and PowerPoint becomes unobstructed.
- B4: Repin, open Settings, and confirm the panel is not covered by the subtitle
  root.
- B5: Confirm PowerPoint context menus and slide-show controls remain usable.

### C. Acrobat compatibility

- C1: In reading/full-screen mode with Pinned enabled, confirm subtitles remain
  visible.
- C2: Click Acrobat and confirm the overlay does not repeatedly take focus.
- C3: Drag the subtitle window and confirm movement is predictable.
- C4: Open Settings and confirm it remains visible and usable.
- C5: Unpin and confirm Acrobat can be operated normally, then repin and confirm
  no new subtitle session starts.

These checks are not complete until the user reports results. They are not a
claim of final GUI, PowerPoint, or Acrobat acceptance.
