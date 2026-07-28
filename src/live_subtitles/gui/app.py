"""CLI wiring and main-thread Tk event consumption for subtitle overlays."""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from ..audio.recording import AudioDeviceError
from ..diagnostic_logging import diagnostic_logger
from ..model_assets import (
    ModelAssetsModel,
    ModelAssetsReport,
    configure_offline_environment,
    display_path,
)
from ..runtime_paths import bundled_resource_path, is_frozen
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
from .state import SubtitleEntry, SubtitleViewState


CLOSE_TIMEOUT_SECONDS = 35.0


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
    parser.add_argument("--opacity", type=_bounded_float(0.5, 1.0, "Opacity"), default=0.88)
    parser.add_argument(
        "--history-lines", type=_bounded_int(1, 100, "History lines"), default=20
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
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.root = root
        self.state = state
        self.controller = controller
        self.microphone_selector = microphone_selector
        self.model_assets = model_assets
        self.offline = offline
        self.ui_poll_ms = ui_poll_ms
        self.clock = clock
        self.exit_code = 0
        self.closing = False
        self.close_started_at: float | None = None
        self._last_heartbeat = self.clock()
        self._queue_fatal_seen = False
        self._logger = diagnostic_logger()
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
            microphone=microphone_callbacks,
            models=model_callbacks,
        )
        self.root.report_callback_exception = self._handle_tk_callback_exception
        if model_assets is not None:
            self.refresh_model_assets()

    def _handle_tk_callback_exception(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: Any,
    ) -> None:
        """Print developer details and request a normal background stop."""

        self._logger.error("Tk callback failed; type=%s", exception_type.__name__)
        if sys.stderr is not None:
            traceback.print_exception(
                exception_type,
                exception,
                traceback_object,
                file=sys.stderr,
            )
        self.exit_code = 2
        self.state.set_status("Fatal error")
        self.state.latest_error = f"GUI error: {type(exception).__name__}: {exception}"
        try:
            self.overlay.set_running(self.controller.running, closing=self.closing)
            self.overlay.render()
        except Exception:
            self._logger.error("Tk error recovery failed")
            if sys.stderr is not None:
                traceback.print_exc(file=sys.stderr)
        self.controller.request_stop("GUI callback error")

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
            f"{display_path(report.model_root)}. Model assets are not included in the "
            "installer. Offline mode will not download them. Prepare the assets and "
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

    def open_model_instructions(self) -> None:
        path = (
            bundled_resource_path("MODEL_SETUP.txt")
            if is_frozen()
            else Path(__file__).resolve().parents[3] / "docs" / "model-assets-setup.md"
        )
        self._open_path(path)

    def start(self) -> None:
        if self.closing or self.controller.running:
            return
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
        self.state.begin_session()
        self.overlay.set_running(True)
        self.overlay.render()
        if not self.controller.start():
            self.state.latest_error = "A subtitle session is already running."
            self.overlay.render()

    def stop(self) -> None:
        if not self.controller.running:
            return
        self._logger.info("Subtitle session stop requested")
        self.state.set_status("Stopping...")
        self.overlay.set_running(True)
        self.overlay.render()
        self.controller.request_stop("user requested stop")

    def clear(self) -> None:
        self.state.clear()
        self.overlay.render()

    def close(self) -> None:
        if self.closing:
            return
        self._logger.info("Application close requested")
        self.closing = True
        self.close_started_at = self.clock()
        self.state.set_status("Stopping...")
        self.overlay.set_running(self.controller.running, closing=True)
        close_popover = getattr(self.overlay, "close_popover", None)
        if callable(close_popover):
            close_popover()
        self.overlay.render()
        self.controller.close()
        self.root.after(self.ui_poll_ms, self._poll_close)

    def _poll_close(self) -> None:
        self._consume_events()
        if not self.controller.running:
            self._logger.info("Background session stopped; destroying GUI")
            self.root.destroy()
            return
        assert self.close_started_at is not None
        if self.clock() - self.close_started_at >= CLOSE_TIMEOUT_SECONDS:
            self.exit_code = 2
            self.state.status = "Fatal error"
            self.state.latest_error = "Shutdown timed out after 35 seconds."
            self.overlay.render()
            self.root.after(250, self.root.destroy)
            return
        self.root.after(self.ui_poll_ms, self._poll_close)

    def _consume_event(self, event: Any) -> bool:
        subtitle_added = False
        if isinstance(event, PreparingEvent):
            self._logger.info("Model preparation started")
            self.state.set_status("Preparing...")
        elif isinstance(event, ModelsReadyEvent):
            self._logger.info("Models ready")
            self.state.set_status("Models ready")
        elif isinstance(event, ListeningEvent):
            self._logger.info("Microphone listening started")
            self.state.set_status(f"Listening... {event.device_name}")
        elif isinstance(event, SubtitleEvent):
            added = self.state.add_subtitle(
                SubtitleEntry(
                    index=event.index,
                    russian_text=event.russian_text,
                    chinese_text=event.chinese_text,
                    received_at=event.created_at,
                    russian_latency_seconds=event.russian_latency_seconds,
                    chinese_latency_seconds=event.chinese_latency_seconds,
                )
            )
            if added:
                self.controller.metrics.displayed_subtitles += 1
                subtitle_added = True
        elif isinstance(event, SegmentErrorEvent):
            self._logger.warning("Segment infrastructure failure; stage=%s", event.stage)
            self.controller.metrics.failed_segments += 1
            self.state.set_segment_error(
                f"Segment {event.index}: {event.stage} failed — {event.message}"
            )
        elif isinstance(event, SessionFinishedEvent):
            self._logger.info("Subtitle session finished")
            self.state.set_status("Stopped")
            self.overlay.set_running(False, closing=self.closing)
        elif isinstance(event, StoppedEvent):
            self._logger.info("Subtitle session stopped")
            self.state.set_status("Stopped")
            self.overlay.set_running(False, closing=self.closing)
        elif isinstance(event, FatalErrorEvent):
            self._logger.error("Background session reported a fatal error")
            self.exit_code = 2
            self.state.set_status("Fatal error")
            self.state.latest_error = event.message
            self.overlay.set_running(False, closing=self.closing)
        return subtitle_added

    def _consume_events(self) -> None:
        rendered_subtitle_events: list[SubtitleEvent] = []
        for event in self.controller.events.drain():
            if self._consume_event(event) and isinstance(event, SubtitleEvent):
                rendered_subtitle_events.append(event)
        fatal_message = self.controller.events.fatal_message
        if fatal_message and not self._queue_fatal_seen:
            self._logger.error("GUI event queue overflow")
            self._queue_fatal_seen = True
            self.exit_code = 2
            self.state.set_status("Fatal error")
            self.state.latest_error = fatal_message
            self.controller.request_stop("GUI event queue overflow")
        self.overlay.render()
        rendered_at = self.clock()
        for event in rendered_subtitle_events:
            self.controller.metrics.render_latencies.add(
                max(0.0, rendered_at - event.created_at)
            )

    def poll(self) -> None:
        if self.closing:
            return
        now = self.clock()
        expected = self.ui_poll_ms / 1_000.0
        self.controller.metrics.mainloop_delays.add(
            max(0.0, now - self._last_heartbeat - expected)
        )
        self._last_heartbeat = now
        self._consume_events()
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
    state = _state_from_args(args)
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
        microphone_selector=MicrophoneSelectorModel(args.device),
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
