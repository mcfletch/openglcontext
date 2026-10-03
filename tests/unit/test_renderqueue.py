"""Calls made on the render thread for other threads
(:mod:`OpenGLContext.events.renderqueue`).

A background thread queues a call; the thread that owns GL makes it, in order,
when it runs the queue.  No window is involved.
"""
import threading

import pytest

from OpenGLContext.events.renderqueue import DEFER, RenderQueue


class TestMakingCalls:
    def test_a_call_is_made_by_the_thread_that_runs_the_queue(self):
        queue = RenderQueue()
        seen = []
        worker = threading.Thread(target=lambda: queue.call(
            lambda: seen.append(threading.current_thread())))
        worker.start()
        worker.join()
        assert seen == []
        assert queue.run() == 1
        assert seen == [threading.current_thread()]

    def test_arguments_are_passed_through(self):
        queue = RenderQueue()
        got = []
        queue.call(lambda a, b, *, c: got.append((a, b, c)), 1, 2, c=3)
        queue.run()
        assert got == [(1, 2, 3)]

    def test_calls_are_made_in_the_order_they_were_queued(self):
        queue = RenderQueue()
        got = []
        for each in range(5):
            queue.call(got.append, each)
        assert queue.run() == 5
        assert got == [0, 1, 2, 3, 4]

    def test_an_empty_queue_makes_no_calls(self):
        queue = RenderQueue()
        assert queue.run() == 0 and len(queue) == 0

    def test_a_call_is_made_once(self):
        queue = RenderQueue()
        got = []
        queue.call(got.append, 'x')
        queue.run()
        queue.run()
        assert got == ['x']

    def test_a_call_queued_from_a_call_waits_for_the_next_run(self):
        """A callback that keeps re-queueing itself cannot hold up a frame."""
        queue = RenderQueue()
        got = []

        def again():
            got.append('again')
            queue.call(again)

        queue.call(again)
        assert queue.run() == 1
        assert got == ['again']
        assert len(queue) == 1

    def test_queueing_wakes_the_loop(self):
        woken = []
        queue = RenderQueue(wake=lambda: woken.append(True))
        queue.call(lambda: None)
        assert woken == [True]

    def test_many_threads_may_queue_at_once(self):
        queue = RenderQueue()
        got = []
        threads = [threading.Thread(target=lambda n=n: [queue.call(got.append, (n, i))
                                                       for i in range(50)])
                   for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert queue.run() == 400
        assert len(set(got)) == 400
        for n in range(8):
            assert [i for (m, i) in got if m == n] == list(range(50))


class TestACallThatIsNotReady:
    def test_deferring_makes_it_again_on_the_next_run(self):
        queue = RenderQueue()
        ready = []
        queue.call(lambda: None if ready else DEFER)
        assert queue.run() == 0 and len(queue) == 1
        ready.append(True)
        assert queue.run() == 1 and len(queue) == 0

    def test_a_deferred_call_keeps_its_place_ahead_of_later_ones(self):
        queue = RenderQueue()
        got = []
        gate = []

        def first():
            if not gate:
                return DEFER
            got.append('first')

        queue.call(first)
        queue.call(got.append, 'second')
        queue.run()
        assert got == ['second']
        gate.append(True)
        queue.call(got.append, 'third')
        queue.run()
        assert got == ['second', 'first', 'third']


class TestACallThatRaises:
    def test_the_error_reaches_the_runner_and_the_rest_wait(self):
        queue = RenderQueue()
        got = []

        def broken():
            raise RuntimeError('broken')

        queue.call(broken)
        queue.call(got.append, 'after')
        with pytest.raises(RuntimeError, match='broken'):
            queue.run()
        assert got == []
        assert queue.run() == 1
        assert got == ['after']


class TestBeforeEachRun:
    def test_a_hook_runs_at_the_start_of_every_run_even_when_nothing_is_queued(self):
        queue = RenderQueue()
        runs = []
        queue.before_run(lambda: runs.append(len(queue)))
        queue.run()
        queue.call(lambda: None)
        queue.run()
        assert runs == [0, 1]
