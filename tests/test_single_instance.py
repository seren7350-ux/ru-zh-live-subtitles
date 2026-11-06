from __future__ import annotations

import multiprocessing
import os
import time
import uuid
from contextlib import ExitStack, contextmanager

import pytest

from live_subtitles.gui import single_instance


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows kernel object IPC")
_CONTEXT = multiprocessing.get_context("spawn")


@pytest.fixture
def name() -> str:
    return f"ipc-test-{uuid.uuid4().hex}"


def _worker(name, channel, start, posting, timeout):
    # This hook signals that election found an owner and lets a test pause
    # precisely between that decision and posting the reveal request.
    api = single_instance._windows_api()
    allow = api.allow_foreground

    def announce_request(pid):
        allow(pid)
        channel.send(("posting", pid))
        if posting is not None and not posting.wait(20):
            raise AssertionError("Test did not release the launch transaction")

    api.allow_foreground = announce_request
    lease = None
    try:
        if start is not None:
            channel.send(("ready", os.getpid()))
            assert start.wait(20)
        lease = single_instance.acquire_instance(name, timeout=timeout)
        channel.send(("primary" if lease.primary else "secondary", os.getpid()))
        while lease.primary:
            command = channel.recv()
            if command == "close":
                break
            assert command == "poll"
            channel.send(("polled", lease.take_activation()))
    except TimeoutError as exc:
        channel.send(("timeout", str(exc)))
    except EOFError:
        pass
    finally:
        if lease is not None:
            lease.close()
        channel.close()


@contextmanager
def _launch(name, *, start=None, posting=None, timeout=20.0):
    channel, child = _CONTEXT.Pipe()
    process = _CONTEXT.Process(target=_worker, args=(name, child, start, posting, timeout))
    process.start()
    child.close()
    try:
        yield channel, process
    finally:
        channel.close()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join(10)
        process.close()


def _message(channel):
    assert channel.poll(15), "No response from test launcher"
    return channel.recv()


def _consume_batch(channel):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        channel.send("poll")
        if _message(channel) == ("polled", True):
            return
        time.sleep(0.01)
    pytest.fail("The primary did not consume the pending activation")


def test_simultaneous_launches_coalesce_through_gui_startup(name):
    start = _CONTEXT.Event()
    with ExitStack() as stack:
        launchers = [stack.enter_context(_launch(name, start=start)) for _ in range(5)]
        for channel, process in launchers:
            assert _message(channel) == ("ready", process.pid)
        start.set()
        initial = [_message(channel) for channel, _ in launchers]
        assert [kind for kind, _ in initial].count("primary") == 1
        primary_index = next(i for i, (kind, _) in enumerate(initial) if kind == "primary")
        primary, owner = launchers[primary_index]
        for i, (channel, _) in enumerate(launchers):
            if i != primary_index:
                assert initial[i] == ("posting", owner.pid)
                assert not channel.poll(), "Launcher exited before the first GUI poll"
        _consume_batch(primary)
        for i, (channel, process) in enumerate(launchers):
            if i != primary_index:
                assert _message(channel) == ("secondary", process.pid)
        primary.send("poll")
        assert _message(primary) == ("polled", False)
        # A new launch after the batch receives its own acknowledgement.
        with _launch(name) as (channel, process):
            assert _message(channel) == ("posting", owner.pid)
            _consume_batch(primary)
            assert _message(channel) == ("secondary", process.pid)


def test_shutdown_during_post_hands_off_without_blocking_tk(name):
    lease = single_instance.acquire_instance(name)
    posting = _CONTEXT.Event()
    try:
        with ExitStack() as stack:
            first, _ = stack.enter_context(_launch(name))
            assert _message(first) == ("posting", os.getpid())
            second, _ = stack.enter_context(_launch(name, posting=posting))
            # Both launches observed the original process. One is still
            # inside its transaction and will post after begin_close().
            assert _message(second) == ("posting", os.getpid())
            assert not lease.take_activation()
            lease.begin_close()
            posting.set()
            assert not lease.take_activation()
            lease.close()
            events = [_message(first), _message(second)]
            assert sorted(kind for kind, _ in events) == ["posting", "primary"]
            leader, follower = (first, second) if events[0][0] == "primary" else (second, first)
            _consume_batch(leader)
            assert _message(follower)[0] == "secondary"
    finally:
        posting.set()
        lease.close()


def test_unacknowledged_launch_recovers_after_primary_crashes(name):
    with _launch(name) as (primary, owner):
        assert _message(primary) == ("primary", owner.pid)
        with _launch(name) as (waiting, replacement):
            assert _message(waiting) == ("posting", owner.pid)
            owner.kill()
            owner.join(10)
            assert not owner.is_alive()
            assert _message(waiting) == ("primary", replacement.pid)


def test_distinct_names_have_independent_primaries(name):
    lease = single_instance.acquire_instance(name)
    try:
        assert lease.primary
        with _launch(name + "-other") as (channel, process):
            assert _message(channel) == ("primary", process.pid)
            assert not lease.take_activation()
    finally:
        lease.close()


def test_timeout_does_not_claim_success_or_start_another_primary(name):
    lease = single_instance.acquire_instance(name)
    try:
        with _launch(name, timeout=0.15) as (channel, _):
            assert _message(channel) == ("posting", os.getpid())
            kind, detail = _message(channel)
            assert kind == "timeout" and "did not respond" in detail
        lease.begin_close()
        with _launch(name, timeout=0.15) as (channel, _):
            kind, detail = _message(channel)
            assert kind == "timeout" and "still closing" in detail
    finally:
        lease.close()
