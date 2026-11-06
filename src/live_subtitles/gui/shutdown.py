"""Shutdown escalation policy, independent of the Tk polling loop."""

from dataclasses import dataclass
from typing import Any


CLOSE_TIMEOUT_SECONDS = 35.0
FORCE_STOP_GRACE_SECONDS = 3.0


@dataclass
class ShutdownProgress:
    started_at: float | None = None
    terminate_started_at: float | None = None
    kill_requested: bool = False

    def begin(self, now: float) -> None:
        if self.started_at is None:
            self.started_at = now

    def action_due(self, *, running: bool, now: float) -> str | None:
        if (not running or self.started_at is None
                or now - self.started_at < CLOSE_TIMEOUT_SECONDS):
            return None
        if self.terminate_started_at is None:
            return "terminate"
        if not self.kill_requested and now - self.terminate_started_at >= FORCE_STOP_GRACE_SECONDS:
            return "kill"
        return None

    def execute(self, controller: Any, action: str, now: float) -> None:
        """Record escalation only after the controller call succeeds.

        A failed native terminate/kill call must remain retryable on the next
        tick. Neither requesting termination nor receiving Stopped proves that
        worker resources have been released; the controller owns that check.
        """
        if action not in {"terminate", "kill"}:
            raise ValueError(f"Unknown shutdown action: {action}")
        operation = getattr(controller, action, None)
        if callable(operation):
            operation()
        if action == "terminate":
            self.terminate_started_at = now
        else:
            self.kill_requested = True
