"""Transient progress for one GUI recording session, independent of Tk."""
from dataclasses import dataclass

from .state import SubtitleViewState


@dataclass
class SessionProgress:
    started_at: float
    stage: str = "Preparing models"
    stop_requested_at: float | None = None

    def preparing(self, state: SubtitleViewState, message: str, closing: bool) -> None:
        if not closing and not state.stopping:
            self.stage = message
            state.set_status(message)

    def request_stop(self, state: SubtitleViewState, now: float) -> None:
        if self.stop_requested_at is None:
            self.stop_requested_at = now
        state.set_status("Stopping...")

    def refresh(self, state: SubtitleViewState, now: float) -> None:
        if state.preparing:
            state.set_status(f"{self.stage} · {int(now - self.started_at)}s")
        elif state.stopping and self.stop_requested_at is not None:
            elapsed = int(now - self.stop_requested_at)
            state.set_status(f"Stopping... waiting for engine · {elapsed}s")
