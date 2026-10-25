"""Tests for the hand-off between a service's worker and the render thread.

``Inbox`` carries commands from any thread to one worker. ``Updates`` carries
scene changes from a worker to the render thread, one write per field.
"""
import threading
import time

import pytest

from OpenGLContext.events.handoff import Inbox, Updates


class SimpleNamespace:
    """A hashable stand-in for a scenegraph node: fields are attributes."""

    def __init__(self, **fields: object) -> None:
        self.__dict__.update(fields)


def test_inbox_gives_commands_back_in_the_order_they_were_posted():
    inbox = Inbox()
    for number in range(5):
        inbox.post(('move', number))
    assert inbox.drain() == [('move', number) for number in range(5)]
    assert inbox.drain() == []


def test_inbox_takes_posts_from_many_threads_without_losing_any():
    inbox = Inbox()

    def post(first: int) -> None:
        for number in range(first, first + 200):
            inbox.post(number)

    threads = [threading.Thread(target=post, args=(start,)) for start in (0, 200, 400, 600)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(inbox.drain()) == list(range(800))


def test_inbox_calls_wake_from_the_posting_thread():
    woken: list[int] = []
    inbox = Inbox(wake=lambda: woken.append(threading.get_ident()))
    inbox.post('x')
    assert woken == [threading.get_ident()]


def test_inbox_wait_returns_at_once_when_a_command_is_waiting():
    inbox = Inbox()
    inbox.post('x')
    started = time.monotonic()
    assert inbox.wait(5.0) is True
    assert time.monotonic() - started < 1.0


def test_inbox_wait_times_out_when_nothing_arrives():
    assert Inbox().wait(0.02) is False


def test_inbox_wait_is_woken_by_a_post_from_another_thread():
    inbox = Inbox()
    threading.Timer(0.05, inbox.post, args=('late',)).start()
    started = time.monotonic()
    assert inbox.wait(5.0) is True
    assert time.monotonic() - started < 2.0
    assert inbox.drain() == ['late']


def test_inbox_wait_does_not_return_for_a_command_it_has_already_given_out():
    inbox = Inbox()
    inbox.post('x')
    inbox.drain()
    assert inbox.wait(0.02) is False


def test_inbox_length_counts_waiting_commands():
    inbox = Inbox()
    inbox.post(1)
    inbox.post(2)
    assert len(inbox) == 2
    inbox.drain()
    assert len(inbox) == 0


def _as_worker(update: Updates, action) -> None:
    """Run ``action`` on a thread that is not the one ``update`` was made on."""
    thread = threading.Thread(target=action)
    thread.start()
    thread.join()


def test_updates_assigns_at_once_on_the_thread_that_owns_the_scene():
    updates = Updates()
    node = SimpleNamespace(colour=(1, 1, 1))
    updates.set(node, colour=(1, 0, 0))
    assert node.colour == (1, 0, 0)
    assert updates.apply() == 0


def test_updates_holds_a_write_from_another_thread_until_applied():
    updates = Updates()
    node = SimpleNamespace(colour=(1, 1, 1))
    _as_worker(updates, lambda: updates.set(node, colour=(0, 1, 0)))
    assert node.colour == (1, 1, 1)
    assert updates.apply() == 1
    assert node.colour == (0, 1, 0)
    assert updates.apply() == 0


def test_updates_keeps_the_last_write_to_each_field():
    updates = Updates()
    node = SimpleNamespace(colour=0, size=0)

    def writes() -> None:
        updates.set(node, colour=1)
        updates.set(node, colour=2, size=5)
        updates.set(node, colour=3)

    _as_worker(updates, writes)
    assert updates.pending() == 2
    updates.apply()
    assert (node.colour, node.size) == (3, 5)


def test_updates_writes_to_different_nodes_do_not_merge():
    updates = Updates()
    first, second = SimpleNamespace(value=0), SimpleNamespace(value=0)

    def writes() -> None:
        updates.set(first, value=1)
        updates.set(second, value=2)

    _as_worker(updates, writes)
    updates.apply()
    assert (first.value, second.value) == (1, 2)


def test_updates_makes_queued_calls_in_order_after_the_writes():
    updates = Updates()
    seen: list[object] = []
    node = SimpleNamespace(value=0)

    def work() -> None:
        updates.call(lambda: seen.append(('call', node.value)))
        updates.set(node, value=9)
        updates.call(seen.append, 'second')

    _as_worker(updates, work)
    assert updates.apply() == 3
    assert seen == [('call', 9), 'second']


def test_updates_runs_a_call_made_on_the_render_thread_when_applied():
    updates = Updates()
    seen: list[int] = []
    updates.call(seen.append, 1)
    assert seen == []
    updates.apply()
    assert seen == [1]


def test_updates_goes_on_past_a_write_that_fails():
    updates = Updates()
    good = SimpleNamespace(value=0)

    class Refuses:
        @property
        def value(self) -> int:
            return 0

    def work() -> None:
        updates.set(Refuses(), value=1)
        updates.set(good, value=2)

    _as_worker(updates, work)
    assert updates.apply() == 1
    assert good.value == 2


def test_updates_goes_on_past_a_call_that_raises():
    updates = Updates()
    seen: list[int] = []

    def fails() -> None:
        raise ValueError('refused')

    updates.call(fails)
    updates.call(seen.append, 1)
    assert updates.apply() == 1
    assert seen == [1]


def test_updates_wake_is_called_when_a_worker_queues_work():
    woken: list[int] = []
    updates = Updates(wake=lambda: woken.append(1))
    node = SimpleNamespace(value=0)
    _as_worker(updates, lambda: updates.set(node, value=1))
    assert woken == [1]


def test_updates_bind_moves_ownership_of_the_scene_to_another_thread():
    updates = Updates()
    node = SimpleNamespace(value=0)
    done = threading.Event()

    def owner() -> None:
        updates.bind()
        updates.set(node, value=7)
        done.set()

    thread = threading.Thread(target=owner)
    thread.start()
    thread.join()
    assert done.is_set()
    assert node.value == 7


@pytest.mark.parametrize('field', ['colour', 'size'])
def test_updates_set_names_the_field_it_could_not_write(field, caplog):
    updates = Updates()

    class Frozen:
        __slots__ = ()

    _as_worker(updates, lambda: updates.set(Frozen(), **{field: 1}))
    with caplog.at_level('ERROR'):
        updates.apply()
    assert field in caplog.text
