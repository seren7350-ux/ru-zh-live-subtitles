# Application settings and diagnostics

The subtitle window shows the current Russian and Chinese caption on separate
single lines. Only an overflowing line moves horizontally; no subtitle history
scroll is displayed. Bilingual timestamped SRT is saved automatically.

Settings has four pages, with Start/Stop, Clear display and Exit always in the
footer. General contains the microphone, session status, Russian visibility and
always-on-top switch. Appearance contains independent background/text opacity,
font sizes and black outline. More contains borderless/toolbar switches, SRT
folder, Move to top/bottom actions and Restore defaults. Diagnostics contains
model readiness, setup help, logs and Save thread diagnostics.

Move to top/bottom positions the window within its nearest monitor's usable
desktop area. Both placements remain freely draggable. There is no separate
Floating mode. Drag the subtitle/background area to move; use window edges to
resize. Double-click hides/shows the toolbar, right-click opens Settings.
Ctrl+Space starts/stops; Ctrl+Q exits. Reactivating an invisible or toolbar-hidden
window from the taskbar exposes Settings so it can be recovered.

Appearance, window geometry and microphone preference are saved atomically to
`preferences.json` in the application data directory. Explicit command-line
options override saved settings. Microphones are restored by an unambiguous name;
missing or duplicate names fall back to System default. Session status, caption
text and errors are not preferences. Demos do not write preferences. Restore
defaults changes display preferences and resets the microphone only when stopped.
Windows saved on a disconnected monitor are moved into an available work area.

Start reports voice detection (VAD), speech recognition (ASR) and translation
preparation stages with total elapsed time. Cancel signals the isolated engine;
an in-progress native model load must return before the next stage is skipped.
The UI shows the waiting time. Models are not kept resident between sessions.

Normal application/worker logs rotate and redact known subtitle text, tokens and
user directory paths. Save thread diagnostics records function/line locations
without frame locals, and requests the same from a running engine. Native fault
files `fault-gui-<pid>.log` / `fault-worker-<pid>.log` retain Python stack locations.
A GUI heartbeat delayed for 15 seconds produces a best-effort stack dump; silence
in the microphone is not treated as a hang. These fault files can contain source
paths and remain available for diagnosis. They are not complete native minidumps,
and cannot guarantee capture of power loss, hard process termination, or every
native/GIL deadlock. The logger's PID/session IDs correlate engine and UI events.

The crash implementation follows Python's [faulthandler documentation](https://docs.python.org/3.11/library/faulthandler.html):
the output handle stays open until the handler and watchdog are disabled.
