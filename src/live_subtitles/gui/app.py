"""CLI wiring and main-thread Tk event consumption for subtitle overlays."""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..audio.recording import AudioDeviceError
from ..diagnostic_logging import diagnostic_logger
from ..model_assets import (
    ModelAssetsModel,
    ModelAssetsReport,
    configure_offline_environment,
    display_path,
)
from ..runtime_paths import bundled_resource_path, is_frozen, subtitle_directory
from ..subtitles import SrtSession
from ..preferences import Preferences, BOOL_FIELDS, NUM_FIELDS
from ..config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRANSLATION_DEVICE,
    DEFAULT_TRANSLATION_ENGINE,
)
from ..translation.factory import TRANSLATION_ENGINES
from .controller import DemoOverlayController, GuiMetricsSnapshot, sanitize_message
from .events import (
    FatalErrorEvent,
    ListeningEvent,
    ModelsReadyEvent,
    PreparingEvent,
    SegmentErrorEvent,
    SessionFinishedEvent,
    StoppedEvent,
    SubtitleEvent,
)
from .microphone_selector import MicrophoneSelectorModel, MicrophoneSelectorSnapshot
from .overlay import ModelPanelCallbacks, MicrophonePanelCallbacks, SubtitleOverlay
from .process_controller import (
    LiveProcessOverlayController,
    LiveWorkerConfig,
    LiveWorkerSummary,
)
from .session_progress import SessionProgress
from .shutdown import ShutdownProgress
from .state import SubtitleViewState
from .session_view import apply_session_event

if TYPE_CHECKING:
    from .single_instance import InstanceLease




def _bounded_float(minimum: float, maximum: float, label: str) -> Callable[[str], float]:
    def parse(value: str) -> float:
        try:
            number = float(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be a number.") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {minimum:g} and {maximum:g}."
            )
        return number

    return parse


def _bounded_int(minimum: int, maximum: int, label: str) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"{label} must be an integer.") from exc
        if not minimum <= number <= maximum:
            raise argparse.ArgumentTypeError(
                f"{label} must be between {minimum} and {maximum}."
            )
        return number

    return parse


def _add_gui_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--background-opacity", "--opacity", dest="opacity",
        type=_bounded_float(0.0, 1.0, "Background opacity"), default=0.88,
    )
    parser.add_argument(
        "--text-opacity", type=_bounded_float(0.0, 1.0, "Text opacity"), default=1.0,
    )
    parser.add_argument("--text-outline", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument(
        "--history-lines", type=_bounded_int(1, 100, "History lines"), default=20,
        help="number of recent captions retained in memory; only the latest is displayed",
    )
    parser.add_argument(
        "--srt-dir", type=Path,
        help="folder for automatically saved bilingual SRT sessions (default: ~/ru-zh-live-subtitles/subtitles)",
    )
    parser.add_argument(
        "--show-russian", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--borderless", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--topmost", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--chinese-font-size",
        type=_bounded_int(16, 72, "Chinese font size"),
        default=34,
    )
    parser.add_argument(
        "--russian-font-size",
        type=_bounded_int(10, 48, "Russian font size"),
        default=20,
    )


def add_gui_subcommands(subparsers: Any) -> None:
    demo = subparsers.add_parser(
        "overlay-demo",
        help="show a model-free, microphone-free bilingual overlay demo",
    )
    demo.add_argument(
        "--duration", type=_bounded_float(0.0, 3_600, "Duration"), default=30.0
    )
    _add_gui_arguments(demo)
    demo.add_argument(
        "--ui-poll-ms", type=_bounded_int(20, 250, "UI poll interval"), default=50
    )
    demo.set_defaults(handler=_overlay_demo)

    live = subparsers.add_parser(
        "live-overlay",
        help="show offline VAD/ASR/translation in an always-on-top Tk overlay",
        description=(
            "VAD-segmented short-file offline ASR/translation overlay; this is not native "
            "streaming ASR."
        ),
    )
    live.add_argument("--device", type=int, help="input device number")
    live.add_argument(
        "--duration", type=_bounded_float(0.0, 3_600, "Duration"), default=0.0
    )
    live.add_argument(
        "--translation-engine", choices=TRANSLATION_ENGINES, default=DEFAULT_TRANSLATION_ENGINE
    )
    live.add_argument("--translation-model")
    live.add_argument(
        "--translation-device",
        choices=("auto", "cpu", "cuda"),
        default=DEFAULT_TRANSLATION_DEVICE,
    )
    live.add_argument("--num-beams", type=_bounded_int(1, 16, "Beam count"), default=1)
    live.add_argument(
        "--max-new-tokens", type=_bounded_int(1, 2_048, "Maximum new tokens"), default=256
    )
    live.add_argument(
        "--segment-queue-size",
        type=_bounded_int(1, 32, "Segment queue size"),
        default=8,
    )
    live.add_argument(
        "--audio-queue-size", type=_bounded_int(16, 2_000, "Audio queue size"), default=320
    )
    live.add_argument("--vad-threshold", type=_bounded_float(0.0, 1.0, "VAD threshold"), default=0.5)
    live.add_argument(
        "--negative-threshold",
        type=_bounded_float(0.0, 1.0, "Negative VAD threshold"),
        default=0.35,
    )
    live.add_argument("--min-silence-ms", type=int, default=600)
    live.add_argument("--speech-pad-ms", type=int, default=100)
    live.add_argument("--pre-roll-ms", type=int, default=250)
    live.add_argument("--min-segment-ms", type=int, default=300)
    live.add_argument("--max-segment-seconds", type=float, default=15.0)
    _add_gui_arguments(live)
    live.add_argument(
        "--ui-poll-ms", type=_bounded_int(20, 250, "UI poll interval"), default=50
    )
    live.add_argument(
        "--auto-start", action=argparse.BooleanOptionalAction, default=True
    )
    live.add_argument(
        "--offline",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="use local model assets only and block model downloads",
    )
    live.set_defaults(handler=_live_overlay)


class GuiRuntime:
    """Consume immutable events and update Tk only from the mainloop thread."""

    def __init__(
        self,
        root: Any,
        state: SubtitleViewState,
        controller: Any,
        *,
        ui_poll_ms: int,
        microphone_selector: MicrophoneSelectorModel | None = None,
        model_assets: ModelAssetsModel | None = None,
        offline: bool = False,
        instance_lease: InstanceLease | None = None,
        srt_directory: Path | None = None,
        clock: Callable[[], float] = time.perf_counter,
        preferences: Preferences | None = None,
        saved_preferences: dict[str, Any] | None = None,
    ) -> None:
        self.root = root
        self.state = state
        self.controller = controller
        self.microphone_selector = microphone_selector
        self.model_assets = model_assets
        self.offline = offline
        self.instance_lease = instance_lease
        self.srt_directory = (
            srt_directory.expanduser() if srt_directory is not None
            else subtitle_directory()
        )
        self._srt_session: SrtSession | None = None
        self.ui_poll_ms = ui_poll_ms
        self.clock = clock
        self.exit_code = 0
        self.closing = False
        self.shutdown = ShutdownProgress()
        self._destroyed = False
        self._fatal_message = ""
        self._last_heartbeat = self.clock()
        self._queue_fatal_seen = False
        self._logger = diagnostic_logger()
        self.preferences = preferences
        self._preference_snapshot: dict[str, Any] | None = None
        self._preference_check_at = self.clock()
        self.progress = SessionProgress(self.clock())
        microphone_callbacks = None
        if microphone_selector is not None:
            microphone_callbacks = MicrophonePanelCallbacks(
                refresh=self.refresh_microphones,
                select=self.select_microphone,
                snapshot=microphone_selector.snapshot,
                can_change=self.can_change_microphone,
            )
        model_callbacks = None
        if model_assets is not None:
            model_callbacks = ModelPanelCallbacks(
                recheck=self.refresh_model_assets,
                snapshot=model_assets.snapshot,
                open_folder=self.open_model_folder,
                open_instructions=self.open_model_instructions,
            )
        self.overlay = SubtitleOverlay(
            root,
            state,
            on_start=self.start,
            on_stop=self.stop,
            on_clear=self.clear,
            on_exit=self.close,
            on_open_subtitles=self.open_subtitles_folder,
            microphone=microphone_callbacks,
            models=model_callbacks,
        )
        self.root.report_callback_exception = self._handle_tk_callback_exception
        self.overlay.on_restore_defaults = self.restore_defaults
        self.overlay.on_open_logs = self.open_logs_folder
        self.overlay.on_dump_threads = self.dump_diagnostics
        if saved_preferences and "window_rect" in saved_preferences:
            self.overlay.restore_geometry(tuple(saved_preferences["window_rect"]))
        if model_assets is not None:
            self.refresh_model_assets()

    def _handle_tk_callback_exception(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: Any,
    ) -> None:
        """Persist the traceback even when the executable has no console."""

        self._logger.error(
            "Tk callback failed; type=%s", exception_type.__name__,
            exc_info=(exception_type, exception, traceback_object),
            extra={"sensitive_text": self._caption_texts()},
        )
        self.exit_code = 2
        self._fatal_message = f"GUI error: {type(exception).__name__}: {sanitize_message(exception)}"
        self.state.set_status("Fatal error")
        self.state.latest_error = self._fatal_message
        try:
            self.overlay.set_running(self.controller.running, closing=self.closing)
            self.overlay.render()
        except Exception:
            self._logger.exception(
                "Tk error display failed", extra={"sensitive_text": self._caption_texts()}
            )
        try:
            self.controller.request_stop("GUI callback error")
        except Exception:
            self._logger.exception("Unable to request stop after Tk callback failure")

    def _caption_texts(self) -> tuple[str, ...]:
        return tuple(
            text for entry in self.state.entries
            for text in (entry.russian_text, entry.chinese_text) if text
        )

    def save_preferences(self) -> None:
        if self.preferences is None or self._destroyed:
            return
        values = {key: getattr(self.state, key) for key in (*BOOL_FIELDS, *NUM_FIELDS)}
        values["window_rect"] = list(self.overlay.window_rectangle())
        if self.microphone_selector is not None:
            values["microphone_name"] = self.microphone_selector.preference_name()
        if values == self._preference_snapshot:
            return
        try:
            self.preferences.save(values)
        except OSError:
            self._logger.exception("Could not save preferences")
        else:
            self._preference_snapshot = values

    def restore_defaults(self) -> None:
        if self.preferences is None:
            self.preferences = Preferences()
        defaults = SubtitleViewState()
        overlay = self.overlay
        for key, toggle in (("borderless", overlay.toggle_borderless),
                            ("topmost", overlay.toggle_topmost)):
            if getattr(self.state, key) != getattr(defaults, key):
                toggle()
        for key in (*BOOL_FIELDS, *NUM_FIELDS):
            setattr(self.state, key, getattr(defaults, key))
        overlay.set_opacity(defaults.opacity)
        overlay._sync_toolbar()
        def reset_geometry() -> None:
            overlay.restore_geometry((self.root.winfo_x(), self.root.winfo_y(), 900, 280))
            overlay.set_position("bottom")
        self.root.after_idle(reset_geometry)
        if self.can_change_microphone() and self.microphone_selector is not None:
            self.select_microphone(None)
        panel = overlay.settings_panel
        if panel is not None:
            for scale, value in ((panel.opacity_scale, defaults.opacity * 100),
                                 (panel.text_opacity_scale, defaults.text_opacity * 100),
                                 (panel.chinese_scale, defaults.chinese_font_size),
                                 (panel.russian_scale, defaults.russian_font_size)):
                scale.set(value)
        overlay.render()
        # Frame changes finish at idle; save after their geometry reconciliation.
        self.root.after_idle(self.save_preferences)

    def can_change_microphone(self) -> bool:
        return not (
            self.closing
            or self.controller.running
            or self.state.preparing
            or self.state.stopping
        )

    def refresh_microphones(self) -> MicrophoneSelectorSnapshot:
        if self.microphone_selector is None:
            raise RuntimeError("Microphone selection is not available in this mode.")
        snapshot = self.microphone_selector.refresh()
        if snapshot.query_error_type is not None:
            self._logger.warning(
                "Input device enumeration failed; type=%s",
                snapshot.query_error_type,
            )
        return snapshot

    def select_microphone(self, device_index: int | None) -> MicrophoneSelectorSnapshot:
        if self.microphone_selector is None:
            raise RuntimeError("Microphone selection is not available in this mode.")
        if not self.can_change_microphone():
            return self.microphone_selector.snapshot()
        if not self.controller.set_device_index(device_index):
            return self.microphone_selector.snapshot()
        snapshot = self.microphone_selector.select(device_index)
        self._logger.info(
            "Input device selection changed; mode=%s; index=%s",
            "default" if device_index is None else "explicit",
            "none" if device_index is None else device_index,
        )
        return snapshot

    @staticmethod
    def _model_setup_message(report: ModelAssetsReport) -> str:
        missing = ", ".join(status.model_id for status in report.missing_models)
        return (
            f"Model setup required: {missing}. Model root: "
            f"{display_path(report.model_root)}. Required model files were not found "
            "or failed validation. Offline mode will not download them. Install the "
            "offline model bundle or follow Model setup instructions, then "
            "choose Recheck model assets in Settings."
        )

    def refresh_model_assets(self) -> ModelAssetsReport:
        if self.model_assets is None:
            raise RuntimeError("Model asset checks are not available in this mode.")
        report = self.model_assets.refresh()
        if self.offline:
            configure_offline_environment(report)
        if report.ready:
            if self.state.status == "Model setup required":
                self.state.set_status("Ready")
            if self.state.latest_error.startswith("Model setup required:"):
                self.state.latest_error = ""
        else:
            self.state.set_status("Model setup required")
            self.state.latest_error = self._model_setup_message(report)
        self.overlay.render()
        if self.overlay.settings_panel is not None:
            self.overlay.settings_panel.sync()
        return report

    def _open_path(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True) if not path.suffix else None
            opener = getattr(os, "startfile", None)
            if opener is None:
                raise OSError("Opening folders is supported only on Windows.")
            opener(str(path))
        except OSError as exc:
            self.state.latest_error = f"Unable to open {display_path(path)}: {exc}"
            self.overlay.render()

    def open_model_folder(self) -> None:
        if self.model_assets is not None:
            self._open_path(self.model_assets.snapshot().model_root)

    def open_logs_folder(self) -> None:
        from ..runtime_paths import log_directory
        directory = log_directory()
        directory.mkdir(parents=True, exist_ok=True)
        self._open_path(directory.resolve(strict=True))

    def dump_diagnostics(self) -> None:
        from ..fault_diagnostics import dump_threads
        dump_threads()
        request = getattr(self.controller, "request_diagnostics", None)
        if callable(request):
            request()
        self._logger.info("Thread diagnostics saved; active engine dump requested if available")

    def open_model_instructions(self) -> None:
        path = (
            bundled_resource_path("MODEL_SETUP.txt")
            if is_frozen()
            else Path(__file__).resolve().parents[3] / "docs" / "model-assets-setup.md"
        )
        self._open_path(path)

    def open_subtitles_folder(self) -> None:
        directory = Path(self.state.srt_path).parent if self.state.srt_path else self.srt_directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self._open_path(directory.resolve(strict=True))
        except OSError as exc:
            self.state.latest_error = f"Unable to open subtitles folder: {sanitize_message(exc)}"
            self.overlay.render()

    def _srt_failure(self) -> None:
        self._logger.exception(
            "SRT saving failed", extra={"sensitive_text": self._caption_texts()}
        )
        self._srt_session = None
        self.exit_code = 2
        self.state.srt_error = (
            "SRT saving failed. Earlier saved captions are retained; new captions are not being saved. "
            "Check the subtitles folder and diagnostic log, then Stop and Start to retry."
        )

    def _save_subtitle(self, event: SubtitleEvent) -> None:
        if self._srt_session is None:
            return
        try:
            self._srt_session.append(
                event.index, event.start_seconds, event.end_seconds,
                event.russian_text, event.chinese_text,
            )
        except (OSError, ValueError):
            # Saving failure must remain visible without discarding live captions
            # or replacing an engine error. Do not retry an ambiguous partial write.
            self._srt_failure()

    def start(self) -> None:
        if self.closing or self.controller.running:
            return
        # A finished demo/thread can still have queued tail captions. Save them
        # to the previous session before resetting indices and opening a new SRT.
        self._consume_events(limit=self.controller.events.capacity + 1)
        # An explicit retry may expose a newer preflight failure. Do not let a
        # previous session's fatal latch overwrite that actionable diagnosis.
        self._fatal_message = ""
        if self.model_assets is not None:
            report = self.refresh_model_assets()
            if not report.ready:
                self.overlay.set_running(False)
                self.overlay.render()
                return
        if self.microphone_selector is not None:
            try:
                self.microphone_selector.validate_selection()
            except AudioDeviceError as exc:
                self._logger.warning(
                    "Input device validation failed; type=%s", type(exc).__name__
                )
                self.state.set_status("Ready")
                self.state.latest_error = (
                    f"Unable to start with the selected microphone: {sanitize_message(exc)}"
                )
                self.overlay.set_running(False)
                self.overlay.render()
                return
            if not self.controller.set_device_index(
                self.microphone_selector.selected_index
            ):
                self.state.set_status("Ready")
                self.state.latest_error = (
                    "Unable to change the microphone while a subtitle session is running."
                )
                self.overlay.set_running(False)
                self.overlay.render()
                return
        self._logger.info("Subtitle session start requested")
        self.progress = SessionProgress(self.clock())
        try:
            started = self.controller.start()
        except Exception as exc:
            self._handle_tk_callback_exception(type(exc), exc, exc.__traceback__)
            return
        if not started:
            self.state.set_status("Stopping...")
            self.state.latest_error = "The previous subtitle session is still shutting down."
            self.overlay.set_running(self.controller.running)
            return
        self._queue_fatal_seen = False
        self.state.begin_session()
        self._srt_session = None
        try:
            self._srt_session = SrtSession.create(self.srt_directory)
            self.state.srt_path = str(self._srt_session.path)
        except OSError:
            self._srt_failure()
        self.overlay.set_running(True)
        self.overlay.render()

    def stop(self) -> None:
        if not self.controller.running:
            self._consume_events()
            return
        self._logger.info("Subtitle session stop requested")
        self.progress.request_stop(self.state, self.clock())
        self.overlay.set_running(True)
        self.overlay.render()
        self.controller.request_stop("user requested stop")

    def clear(self) -> None:
        self.state.clear()
        self.overlay.render()

    @property
    def close_started_at(self) -> float | None:
        return self.shutdown.started_at

    def close(self) -> None:
        if self.closing:
            return
        self._logger.info("Application close requested")
        self.save_preferences()
        self.closing = True
        self.shutdown.begin(self.clock())
        self.state.set_status("Stopping...")
        try:
            if self.instance_lease is not None:
                self.instance_lease.begin_close()
            self.overlay.set_running(self.controller.running, closing=True)
            close_popover = getattr(self.overlay, "close_popover", None)
            if callable(close_popover):
                close_popover()
        finally:
            try:
                self.controller.close()
            finally:
                self.root.after(self.ui_poll_ms, self._poll_close)

    def _poll_close(self) -> None:
        if self._destroyed:
            return
        if self.clock() - self._preference_check_at >= 1.0:
            self._preference_check_at = self.clock()
            from ..fault_diagnostics import arm_gui_watchdog
            arm_gui_watchdog()
        try:
            try:
                self._consume_events()
            except Exception as exc:
                self._handle_tk_callback_exception(type(exc), exc, exc.__traceback__)
            shutdown_complete = getattr(
                self.controller, "shutdown_complete", not self.controller.running
            )
            if shutdown_complete:
                dispose = getattr(self.controller, "dispose", None)
                if callable(dispose):
                    dispose()
                self._logger.info("Background session stopped; destroying GUI")
                self.root.destroy()
                self._destroyed = True
                return
            now = self.clock()
            action = self.shutdown.action_due(running=self.controller.running, now=now)
            if action is not None:
                self.exit_code = 2
                if action == "terminate":
                    self._fatal_message = "Shutdown timed out after 35 seconds; terminating the engine."
                    self._logger.error(self._fatal_message)
                else:
                    self._logger.error("Engine still alive after terminate; requesting kill")
                self.shutdown.execute(self.controller, action, now)
            if self.controller.running and self.shutdown.terminate_started_at is not None:
                self.state.set_status("Stopping...")
                self.state.latest_error = self._fatal_message
                self.overlay.render()
        finally:
            # Keep checking even if rendering or cleanup raises. Never hide the
            # window while its owned engine is still alive.
            if not self._destroyed:
                self.root.after(self.ui_poll_ms, self._poll_close)

    def _consume_event(self, event: Any) -> bool:
        if isinstance(event, PreparingEvent):
            self._logger.info("%s", event.message)
        elif isinstance(event, ModelsReadyEvent):
            self._logger.info(
                "Models ready; vad_seconds=%.3f; asr_seconds=%.3f; translation_seconds=%.3f; device=%s",
                event.vad_prepare_seconds, event.asr_prepare_seconds,
                event.translation_prepare_seconds, event.translation_device,
            )
        elif isinstance(event, ListeningEvent):
            self._logger.info("Microphone listening started")
        elif isinstance(event, SegmentErrorEvent):
            self._logger.warning(
                "Segment infrastructure failure; segment=%d; stage=%s; error=%s",
                event.index, event.stage, event.message,
                extra={"sensitive_text": self._caption_texts()},
            )
            self.controller.metrics.failed_segments += 1
        elif isinstance(event, SessionFinishedEvent):
            self._logger.info(
                "Subtitle session finished; succeeded=%s; reason=%s; successful=%d; failed=%d; metrics=%s",
                event.succeeded, event.stop_reason, event.successful_subtitles,
                event.failed_subtitles, event.metrics,
            )
        elif isinstance(event, StoppedEvent):
            self._logger.info("Subtitle session stopped; reason=%s", event.reason)
        elif isinstance(event, FatalErrorEvent):
            self._logger.error(
                "Background session reported a fatal error; error=%s", event.message,
                extra={"sensitive_text": self._caption_texts()},
            )
            self.exit_code = 2
            self._fatal_message = event.message
        subtitle_added = apply_session_event(
            self.state, self.progress, event,
            running=self.controller.running, closing=self.closing,
            fatal_message=self._fatal_message,
        )
        if subtitle_added:
            self._save_subtitle(event)
            self.controller.metrics.displayed_subtitles += 1
        return subtitle_added

    def _consume_events(self, *, limit: int = 128) -> None:
        rendered_subtitle_events: list[SubtitleEvent] = []
        for event in self.controller.events.drain(limit=limit):
            if self._consume_event(event) and isinstance(event, SubtitleEvent):
                rendered_subtitle_events.append(event)
        poll_process = getattr(self.controller, "poll_process", None)
        if callable(poll_process):
            for event in poll_process():
                if self._consume_event(event) and isinstance(event, SubtitleEvent):
                    rendered_subtitle_events.append(event)
        fatal_message = self.controller.events.fatal_message
        if not callable(poll_process) and fatal_message and not self._queue_fatal_seen:
            self._logger.error("GUI event transport failure; error=%s", fatal_message)
            self._queue_fatal_seen = True
            self.exit_code = 2
            self._fatal_message = fatal_message
            self.state.set_status("Fatal error")
            self.state.latest_error = fatal_message
            self.controller.request_stop("GUI event transport failure")
        if self._fatal_message:
            self.state.set_status("Fatal error")
            self.state.latest_error = self._fatal_message
        elif self.state.stopping and not self.controller.running:
            self.state.set_status("Stopped")
        self.overlay.set_running(self.controller.running, closing=self.closing)
        rendered_at = self.clock()
        for event in rendered_subtitle_events:
            self.controller.metrics.render_latencies.add(
                max(0.0, rendered_at - event.created_at)
            )

    def poll(self) -> None:
        if self.closing or self._destroyed:
            return
        now = self.clock()
        if now - self._preference_check_at >= 1.0:
            self._preference_check_at = now
            self.save_preferences()
            from ..fault_diagnostics import arm_gui_watchdog
            arm_gui_watchdog()
            self.progress.refresh(self.state, now)
        expected = self.ui_poll_ms / 1_000.0
        self.controller.metrics.mainloop_delays.add(
            max(0.0, now - self._last_heartbeat - expected)
        )
        self._last_heartbeat = now
        try:
            if self.instance_lease is not None:
                try:
                    if self.instance_lease.take_activation():
                        self.overlay.reveal()
                except Exception:
                    # A Windows activation failure must not stop live subtitles.
                    self._logger.exception("Unable to reveal the existing subtitle window")
            self._consume_events()
        finally:
            # Tk invokes report_callback_exception after a failure. Arrange the
            # next tick first so that stop/death events can still be consumed.
            if not self.closing and not self._destroyed:
                self.root.after(self.ui_poll_ms, self.poll)

    def run(self, *, auto_start: bool) -> int:
        self._logger.info("Tk mainloop starting")
        self.root.after(self.ui_poll_ms, self.poll)
        if auto_start:
            self.root.after(0, self.start)
        self.root.mainloop()
        self._logger.info("Tk mainloop exited")
        return self.exit_code


def _state_from_args(args: argparse.Namespace) -> SubtitleViewState:
    return SubtitleViewState(
        history_lines=args.history_lines,
        opacity=args.opacity,
        text_opacity=getattr(args, "text_opacity", 1.0),
        text_outline=bool(getattr(args, "text_outline", False)),
        chinese_font_size=args.chinese_font_size,
        russian_font_size=args.russian_font_size,
        show_russian=args.show_russian,
        topmost=args.topmost,
        borderless=args.borderless,
    )


def _print_gui_summary(snapshot: GuiMetricsSnapshot) -> None:
    print("GUI summary")
    print(f"  Events enqueued/dequeued: {snapshot.events_enqueued}/{snapshot.events_dequeued}")
    print(
        f"  Event queue high-water/final/capacity: "
        f"{snapshot.event_queue_high_watermark}/{snapshot.event_queue_final_depth}/"
        f"{snapshot.event_queue_capacity}"
    )
    print(f"  Event queue overflows: {snapshot.event_queue_overflows}")
    print(f"  Displayed/failed subtitles: {snapshot.displayed_subtitles}/{snapshot.failed_segments}")
    print(
        "  Render latency average/median/P95: "
        f"{snapshot.average_render_latency_seconds:.3f}/"
        f"{snapshot.median_render_latency_seconds:.3f}/"
        f"{snapshot.p95_render_latency_seconds:.3f} s"
    )
    print(
        f"  Mainloop maximum heartbeat delay: "
        f"{snapshot.maximum_mainloop_delay_seconds:.3f} s"
    )


def _run_tk(
    state: SubtitleViewState,
    controller: Any,
    args: argparse.Namespace,
    *,
    microphone_selector: MicrophoneSelectorModel | None = None,
    model_assets: ModelAssetsModel | None = None,
) -> int:
    import tkinter as tk

    root = tk.Tk()
    runtime = GuiRuntime(
        root,
        state,
        controller,
        ui_poll_ms=args.ui_poll_ms,
        microphone_selector=microphone_selector,
        model_assets=model_assets,
        offline=bool(getattr(args, "offline", False)),
        instance_lease=getattr(args, "instance_lease", None),
        srt_directory=getattr(args, "srt_dir", None),
        preferences=getattr(args, "preferences", None),
        saved_preferences=getattr(args, "saved_preferences", None),
    )
    exit_code = runtime.run(auto_start=args.auto_start)
    _print_gui_summary(controller.metrics.snapshot())
    return exit_code


def _overlay_demo(args: argparse.Namespace) -> int:
    args.auto_start = True
    state = _state_from_args(args)
    controller = DemoOverlayController(duration=args.duration)
    return _run_tk(state, controller, args)


def _live_overlay(args: argparse.Namespace) -> int:
    args.preferences = Preferences()
    try:
        saved = args.preferences.load()
    except (OSError, ValueError):
        diagnostic_logger().exception("Could not read preferences; using defaults")
        saved = {}
        # Preserve a malformed file for diagnosis until the user resets defaults.
        args.preferences = None
    args.saved_preferences = saved
    explicit = getattr(args, "explicit_options", set())
    for key in (*BOOL_FIELDS, *NUM_FIELDS):
        if key in saved and key not in explicit:
            setattr(args, key, saved[key])
    state = _state_from_args(args)
    state.toolbar_visible = getattr(args, "toolbar_visible", True)
    selector = MicrophoneSelectorModel(args.device)
    if "device" not in explicit and saved.get("microphone_name"):
        if not selector.restore_name(saved["microphone_name"]):
            diagnostic_logger().warning("Saved microphone missing or ambiguous; using system default")
        args.device = selector.selected_index
    controller = LiveProcessOverlayController(
        LiveWorkerConfig(
            device_index=args.device,
            duration=args.duration,
            audio_queue_size=args.audio_queue_size,
            segment_queue_size=args.segment_queue_size,
            vad_threshold=args.vad_threshold,
            negative_threshold=args.negative_threshold,
            min_silence_ms=args.min_silence_ms,
            speech_pad_ms=args.speech_pad_ms,
            pre_roll_ms=args.pre_roll_ms,
            min_segment_ms=args.min_segment_ms,
            max_segment_seconds=args.max_segment_seconds,
            asr_model=DEFAULT_ASR_MODEL,
            asr_provider=DEFAULT_PROVIDER,
            translation_engine=args.translation_engine,
            translation_model=args.translation_model,
            translation_device=args.translation_device,
            num_beams=args.num_beams,
            max_new_tokens=args.max_new_tokens,
        )
    )
    exit_code = _run_tk(
        state,
        controller,
        args,
        microphone_selector=selector,
        model_assets=ModelAssetsModel(),
    )
    _log_live_exit_metrics(controller)
    for index, summary in enumerate(controller.summaries, start=1):
        print(f"Live session {index}")
        _print_live_worker_summary(summary)
    result = controller.last_result
    return max(exit_code, 2 if result is not None and result.errors else 0)


def _log_live_exit_metrics(controller: LiveProcessOverlayController) -> None:
    """Log aggregate exit metrics without recording subtitle or audio content."""

    logger = diagnostic_logger()
    gui = controller.metrics.snapshot()
    logger.info(
        "Session exit metrics; gui_events=%d/%d; gui_queue=%d/%d; "
        "gui_overflow=%d; displayed_failed=%d/%d; render_p95=%.3f; heartbeat=%.3f",
        gui.events_enqueued,
        gui.events_dequeued,
        gui.event_queue_high_watermark,
        gui.event_queue_capacity,
        gui.event_queue_overflows,
        gui.displayed_subtitles,
        gui.failed_segments,
        gui.p95_render_latency_seconds,
        gui.maximum_mainloop_delay_seconds,
    )
    for index, summary in enumerate(controller.summaries, start=1):
        result = summary.result
        vad = result.vad.metrics
        metrics = result.subtitle_metrics
        logger.info(
            "Live session %d exit metrics; duration=%.3f; subtitles=%d/%d; "
            "audio_blocks=%d/%d; audio_queue=%d/%d; segment_queue=%d/%d; "
            "dropped_gaps_status_backlog=%d/%d/%d/%d; rtf_p95=%.3f; "
            "ru_latency_p95=%.3f; zh_latency_p95=%.3f; loads=%d/%d/%d/%d; "
            "cuda_peak_mib=%.1f; temp_wav=%d/%d/%d; workers=%s/%s; microphone=%s",
            index,
            vad.session_seconds,
            metrics.successful_segments,
            metrics.failed_segments,
            vad.captured_blocks,
            vad.processed_blocks,
            vad.queue_high_watermark,
            vad.queue_capacity,
            metrics.queue_high_watermark,
            metrics.queue_capacity,
            vad.dropped_blocks,
            vad.sequence_gaps,
            vad.portaudio_status_count,
            metrics.backlog_failures,
            metrics.p95_rtf,
            metrics.p95_russian_latency_seconds,
            metrics.p95_chinese_latency_seconds,
            summary.vad_session_creation_count,
            summary.asr_model_load_count,
            summary.translation_tokenizer_load_count,
            summary.translation_model_load_count,
            summary.cuda_peak_memory_bytes / (1024**2),
            metrics.temp_files_created,
            metrics.temp_files_deleted,
            metrics.temp_files_remaining,
            vad.worker_exited,
            metrics.worker_exited,
            vad.microphone_closed,
        )


def _print_live_worker_summary(summary: LiveWorkerSummary) -> None:
    result = summary.result
    vad = result.vad.metrics
    metrics = result.subtitle_metrics
    print("Live segment results")
    for segment in result.subtitles:
        print(f"  Segment {segment.index}: {'success' if segment.succeeded else 'failed'}")
        print(f"    RU: {segment.russian_text}")
        print(f"    ZH: {segment.chinese_text}")
        print(
            f"    Audio/VAD release/queue wait: {segment.audio_duration_seconds:.3f}/"
            f"{segment.vad_release_latency_seconds:.3f}/{segment.queue_wait_seconds:.3f} s"
        )
        print(
            f"    ASR/translation/processing: {float(segment.asr_seconds or 0):.3f}/"
            f"{float(segment.translation_seconds or 0):.3f}/{segment.processing_seconds:.3f} s"
        )
        print(
            f"    RTF/RU latency/ZH latency: {float(segment.rtf or 0):.3f}/"
            f"{float(segment.russian_latency_seconds or 0):.3f}/"
            f"{float(segment.chinese_latency_seconds or 0):.3f}"
        )
    print("Live pipeline summary")
    print(f"  Stop reason: {result.vad.stop_reason}")
    print(f"  Session duration: {vad.session_seconds:.3f} s")
    print(f"  Detected segments: {vad.detected_segments}")
    print(f"  Captured/processed blocks: {vad.captured_blocks}/{vad.processed_blocks}")
    print(f"  Successful/failed subtitles: {metrics.successful_segments}/{metrics.failed_segments}")
    print(f"  Audio queue high-water/capacity: {vad.queue_high_watermark}/{vad.queue_capacity}")
    print(f"  Segment queue high-water/capacity: {metrics.queue_high_watermark}/{metrics.queue_capacity}")
    print(f"  Dropped blocks/sequence gaps: {vad.dropped_blocks}/{vad.sequence_gaps}")
    print(f"  PortAudio status events: {vad.portaudio_status_count}")
    print(f"  Segment backlog failures: {metrics.backlog_failures}")
    print(
        f"  Queue wait average/median/P95: {metrics.average_queue_wait_seconds:.3f}/"
        f"{metrics.median_queue_wait_seconds:.3f}/{metrics.p95_queue_wait_seconds:.3f} s"
    )
    print(
        f"  Processing average/median/P95: {metrics.average_processing_seconds:.3f}/"
        f"{metrics.median_processing_seconds:.3f}/{metrics.p95_processing_seconds:.3f} s"
    )
    print(
        f"  RTF average/median/P95: {metrics.average_rtf:.3f}/"
        f"{metrics.median_rtf:.3f}/{metrics.p95_rtf:.3f}"
    )
    print(
        f"  RU latency average/median/P95: {metrics.average_russian_latency_seconds:.3f}/"
        f"{metrics.median_russian_latency_seconds:.3f}/{metrics.p95_russian_latency_seconds:.3f} s"
    )
    print(
        f"  ZH latency average/median/P95: {metrics.average_chinese_latency_seconds:.3f}/"
        f"{metrics.median_chinese_latency_seconds:.3f}/{metrics.p95_chinese_latency_seconds:.3f} s"
    )
    print(
        f"  Model load counts (VAD/ASR/tokenizer/translation): "
        f"{summary.vad_session_creation_count}/{summary.asr_model_load_count}/"
        f"{summary.translation_tokenizer_load_count}/{summary.translation_model_load_count}"
    )
    print(
        f"  Model load seconds (VAD/ASR/translation): {summary.vad_load_seconds:.3f}/"
        f"{summary.asr_load_seconds:.3f}/{summary.translation_load_seconds:.3f}"
    )
    print(f"  Translation runtime: {summary.translation_device}, {summary.translation_dtype}")
    print(f"  CUDA peak memory: {summary.cuda_peak_memory_bytes / (1024 ** 2):.1f} MiB")
    print(
        f"  Temporary WAV created/deleted/remaining: {metrics.temp_files_created}/"
        f"{metrics.temp_files_deleted}/{metrics.temp_files_remaining}"
    )
    print(f"  Workers exited (VAD/subtitle): {vad.worker_exited}/{metrics.worker_exited}")
    print(f"  Microphone released: {vad.microphone_closed}")
