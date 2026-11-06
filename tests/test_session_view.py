from live_subtitles.gui.events import ListeningEvent, StoppedEvent, SubtitleEvent
from live_subtitles.gui.session_progress import SessionProgress
from live_subtitles.gui.session_view import apply_session_event
from live_subtitles.gui.state import SubtitleViewState


def test_cancel_ignores_late_listening_until_worker_exits():
    state = SubtitleViewState()
    progress = SessionProgress(0)
    state.begin_session()
    progress.request_stop(state, 1)
    for event in (ListeningEvent("microphone", 2), StoppedEvent("cancelled", 3)):
        apply_session_event(state, progress, event, running=True,
                            closing=False, fatal_message="")
        assert state.stopping
        assert not state.listening
    apply_session_event(state, progress, StoppedEvent("cancelled", 4),
                        running=False, closing=False, fatal_message="")
    assert state.status == "Stopped"


def test_fatal_tail_caption_is_saved_once_without_erasing_failure():
    state = SubtitleViewState()
    progress = SessionProgress(0)
    event = SubtitleEvent(1, "Привет", "你好", 1, None, None, 1)
    for expected in (True, False):
        assert apply_session_event(state, progress, event, running=False,
                                   closing=True, fatal_message="worker died") is expected
        assert state.status == "Fatal error"
        assert state.latest_error == "worker died"
    assert state.visible_entries[0].chinese_text == "你好"
