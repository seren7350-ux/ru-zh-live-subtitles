"""CLI wiring and main-thread Tk event consumption for subtitle overlays."""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from typing import Any, Callable

from ..config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PROVIDER,
    DEFAULT_TRANSLATION_DEVICE,
    DEFAULT_TRANSLATION_ENGINE,
)
from ..pipeline.offline_file import OfflineAudioTranslationPipeline
from ..realtime.live_subtitles import LiveTerminalSession
from ..realtime.vad_model import SileroOnnxVad
from ..translation.factory import TRANSLATION_ENGINES
from .controller import DemoOverlayController, GuiMetricsSnapshot, LiveOverlayController
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
from .overlay import SubtitleOverlay
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
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.root = root
        self.state = state
        self.controller = controller
        self.ui_poll_ms = ui_poll_ms
        self.clock = clock
        self.exit_code = 0
        self.closing = False
        self.close_started_at: float | None = None
        self._last_heartbeat = self.clock()
        self._queue_fatal_seen = False
        self.overlay = SubtitleOverlay(
            root,
            state,
            on_start=self.start,
            on_stop=self.stop,
            on_clear=self.clear,
            on_exit=self.close,
        )
        self.root.report_callback_exception = self._handle_tk_callback_exception

    def _handle_tk_callback_exception(
        self,
        exception_type: type[BaseException],
        exception: BaseException,
        traceback_object: Any,
    ) -> None:
        """Print developer details and request a normal background stop."""

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
            traceback.print_exc(file=sys.stderr)
        self.controller.request_stop("GUI callback error")

    def start(self) -> None:
        if self.closing or self.controller.running:
            return
        self.state.begin_session()
        self.overlay.set_running(True)
        self.overlay.render()
        if not self.controller.start():
            self.state.latest_error = "A subtitle session is already running."
            self.overlay.render()

    def stop(self) -> None:
        if not self.controller.running:
            return
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
            self.state.set_status("Preparing...")
        elif isinstance(event, ModelsReadyEvent):
            self.state.set_status("Models ready")
        elif isinstance(event, ListeningEvent):
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
            self.controller.metrics.failed_segments += 1
            self.state.set_segment_error(
                f"Segment {event.index}: {event.stage} failed — {event.message}"
            )
        elif isinstance(event, SessionFinishedEvent):
            self.state.set_status("Stopped")
            self.overlay.set_running(False, closing=self.closing)
        elif isinstance(event, StoppedEvent):
            self.state.set_status("Stopped")
            self.overlay.set_running(False, closing=self.closing)
        elif isinstance(event, FatalErrorEvent):
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
        self.root.after(self.ui_poll_ms, self.poll)
        if auto_start:
            self.root.after(0, self.start)
        self.root.mainloop()
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


def _run_tk(state: SubtitleViewState, controller: Any, args: argparse.Namespace) -> int:
    import tkinter as tk

    root = tk.Tk()
    runtime = GuiRuntime(root, state, controller, ui_poll_ms=args.ui_poll_ms)
    exit_code = runtime.run(auto_start=args.auto_start)
    _print_gui_summary(controller.metrics.snapshot())
    return exit_code


def _overlay_demo(args: argparse.Namespace) -> int:
    args.auto_start = True
    state = _state_from_args(args)
    controller = DemoOverlayController(duration=args.duration)
    return _run_tk(state, controller, args)


def _live_overlay(args: argparse.Namespace) -> int:
    shared: dict[str, Any] = {}

    def session_factory(on_result: Any, on_listening: Any) -> LiveTerminalSession:
        if "pipeline" not in shared:
            shared["pipeline"] = OfflineAudioTranslationPipeline(
                asr_model=DEFAULT_ASR_MODEL,
                asr_provider=DEFAULT_PROVIDER,
                translation_engine=args.translation_engine,
                translation_model=args.translation_model,
                device=args.translation_device,
                num_beams=args.num_beams,
                max_new_tokens=args.max_new_tokens,
            )
        if "vad" not in shared:
            shared["vad"] = SileroOnnxVad()
        return LiveTerminalSession(
            device_index=args.device,
            duration=args.duration,
            audio_queue_size=args.audio_queue_size,
            segment_queue_size=args.segment_queue_size,
            threshold=args.vad_threshold,
            negative_threshold=args.negative_threshold,
            min_silence_ms=args.min_silence_ms,
            speech_pad_ms=args.speech_pad_ms,
            pre_roll_ms=args.pre_roll_ms,
            min_segment_ms=args.min_segment_ms,
            max_segment_seconds=args.max_segment_seconds,
            on_result=on_result,
            on_listening=on_listening,
            pipeline=shared["pipeline"],
            vad=shared["vad"],
        )

    state = _state_from_args(args)
    controller = LiveOverlayController(session_factory)
    exit_code = _run_tk(state, controller, args)
    result = controller.last_result
    if result is not None:
        vad = result.vad.metrics
        subtitles = result.subtitle_metrics
        print("Live pipeline summary")
        print(f"  Stop reason: {result.vad.stop_reason}")
        print(f"  Successful/failed subtitles: {subtitles.successful_segments}/{subtitles.failed_segments}")
        print(
            f"  Audio queue high-water/capacity: {vad.queue_high_watermark}/{vad.queue_capacity}"
        )
        print(
            f"  Segment queue high-water/capacity: "
            f"{subtitles.queue_high_watermark}/{subtitles.queue_capacity}"
        )
        print(f"  Dropped blocks/sequence gaps: {vad.dropped_blocks}/{vad.sequence_gaps}")
        print(f"  PortAudio status events: {vad.portaudio_status_count}")
        print(f"  Segment backlog failures: {subtitles.backlog_failures}")
        print(
            f"  RU latency average/median/P95: "
            f"{subtitles.average_russian_latency_seconds:.3f}/"
            f"{subtitles.median_russian_latency_seconds:.3f}/"
            f"{subtitles.p95_russian_latency_seconds:.3f} s"
        )
        print(
            f"  ZH latency average/median/P95: "
            f"{subtitles.average_chinese_latency_seconds:.3f}/"
            f"{subtitles.median_chinese_latency_seconds:.3f}/"
            f"{subtitles.p95_chinese_latency_seconds:.3f} s"
        )
        print(
            f"  Temporary WAV created/deleted/remaining: "
            f"{subtitles.temp_files_created}/{subtitles.temp_files_deleted}/"
            f"{subtitles.temp_files_remaining}"
        )
        print(
            f"  Workers exited (VAD/subtitle): {vad.worker_exited}/"
            f"{subtitles.worker_exited}"
        )
        print(f"  Microphone released: {vad.microphone_closed}")
        translator = shared.get("pipeline").translator if shared.get("pipeline") else None
        if translator is not None:
            print(
                f"  CUDA peak memory: "
                f"{getattr(translator, 'peak_cuda_memory_bytes', 0) / (1024 ** 2):.1f} MiB"
            )
    return max(exit_code, 2 if result is not None and result.errors else 0)
