from types import SimpleNamespace

import pytest

from live_subtitles.gui.shutdown import ShutdownProgress


def test_shutdown_escalates_once_and_only_while_worker_is_alive():
    progress = ShutdownProgress()
    calls = []
    controller = SimpleNamespace(terminate=lambda: calls.append("terminate"),
                                 kill=lambda: calls.append("kill"))
    progress.begin(10)
    progress.begin(20)
    assert progress.started_at == 10
    assert progress.action_due(running=True, now=44.9) is None
    assert progress.action_due(running=False, now=45) is None
    assert progress.action_due(running=True, now=45) == "terminate"
    progress.execute(controller, "terminate", 45)
    assert progress.action_due(running=True, now=47.9) is None
    assert progress.action_due(running=True, now=48) == "kill"
    progress.execute(controller, "kill", 48)
    assert progress.action_due(running=True, now=100) is None
    assert calls == ["terminate", "kill"]


def test_failed_termination_is_retryable():
    def fail():
        raise OSError("native failure")

    progress = ShutdownProgress(started_at=0)
    with pytest.raises(OSError):
        progress.execute(SimpleNamespace(terminate=fail), "terminate", 35)
    assert progress.action_due(running=True, now=36) == "terminate"
    assert progress.terminate_started_at is None
