"""Project worker events onto GUI state without Tk, file I/O, or workers."""

from .events import (
    GuiEvent, PreparingEvent, ModelsReadyEvent, ListeningEvent, SubtitleEvent,
    SegmentErrorEvent, SessionFinishedEvent, StoppedEvent, FatalErrorEvent,
)
from .session_progress import SessionProgress
from .state import SubtitleEntry, SubtitleViewState


def apply_session_event(
    state: SubtitleViewState,
    progress: SessionProgress,
    event: GuiEvent,
    *,
    running: bool,
    closing: bool,
    fatal_message: str,
) -> bool:
    """Return whether a new caption needs persistence and render accounting.

    Shutdown messages may arrive before the process exits. Late readiness must
    not undo cancellation, and tail captions must not erase a fatal diagnosis.
    The caller owns the fatal latch, resetting it only on an explicit retry.
    """
    added = False
    if isinstance(event, PreparingEvent):
        progress.preparing(state, event.message, closing)
    elif isinstance(event, (ModelsReadyEvent, ListeningEvent)):
        if not state.stopping and not closing:
            state.set_status(
                f"Listening... {event.device_name}"
                if isinstance(event, ListeningEvent) else "Models ready"
            )
    elif isinstance(event, SubtitleEvent):
        added = state.add_subtitle(SubtitleEntry(
            index=event.index,
            russian_text=event.russian_text,
            chinese_text=event.chinese_text,
            received_at=event.created_at,
            russian_latency_seconds=event.russian_latency_seconds,
            chinese_latency_seconds=event.chinese_latency_seconds,
        ))
    elif isinstance(event, SegmentErrorEvent):
        state.set_segment_error(
            f"Segment {event.index}: {event.stage} failed — {event.message}"
        )
    elif isinstance(event, (SessionFinishedEvent, StoppedEvent)):
        state.set_status("Stopping..." if running else "Stopped")
    elif isinstance(event, FatalErrorEvent):
        state.set_status("Fatal error")
    if fatal_message:
        state.set_status("Fatal error")
        state.latest_error = fatal_message
    return added
