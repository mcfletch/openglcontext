"""Work a camera-following field needs, done on a worker thread.

A request names what to compute; the worker computes the newest one; the
render thread applies the newest result once a frame. A request that arrives
before the one before it has started replaces it, merged with it where the
caller says how.
"""
import threading

from OpenGLContext.scenegraph.vegetation.streaming import BackgroundCompute


def _pair():
    applied = []
    work = BackgroundCompute(lambda *args: ('done', args), applied.append)
    return work, applied


class TestComputingAside:
    def test_a_result_is_applied_when_drained(self):
        work, applied = _pair()
        try:
            work.request(1, 2)
            assert work.wait(5.0)
            assert work.drain()
            assert applied == [('done', (1, 2))]
        finally:
            work.stop()

    def test_nothing_to_drain_is_nothing_applied(self):
        work, applied = _pair()
        try:
            assert not work.drain()
            assert applied == []
        finally:
            work.stop()

    def test_an_unstarted_request_is_merged_into_the_next(self):
        gate = threading.Event()
        seen = []

        def compute(*args):
            gate.wait(5.0)
            seen.append(args)
            return args
        work = BackgroundCompute(compute, lambda payload: None,
                                 merge=lambda old, new: (old[0] or new[0], old[1] or new[1]))
        try:
            work.request(True, False)          # started, and held at the gate
            while not work.busy:
                pass
            work.request(False, True)
            work.request(False, False)         # merged with the one before
            gate.set()
            assert work.wait(5.0)
            assert seen == [(True, False), (False, True)]
        finally:
            work.stop()

    def test_a_failure_is_logged_and_the_worker_carries_on(self, caplog):
        calls = []

        def compute(value):
            calls.append(value)
            if value == 'bad':
                raise ValueError('no')
            return value
        applied = []
        work = BackgroundCompute(compute, applied.append)
        try:
            work.request('bad')
            assert work.wait(5.0)
            work.request('good')
            assert work.wait(5.0)
            work.drain()
            assert applied == ['good']
            assert 'recompute failed' in caplog.text
        finally:
            work.stop()

    def test_stopping_ends_the_thread(self):
        work, _applied = _pair()
        work.stop()
        assert not work.alive


class TestAFailedRequest:
    def test_is_handed_back_on_the_render_thread(self):
        failed = []

        def compute(value):
            raise ValueError(value)
        work = BackgroundCompute(compute, lambda payload: None,
                                 failed=lambda args, error: failed.append(
                                     (args, str(error), threading.current_thread())))
        try:
            work.request('bad')
            assert work.wait(5.0)
            assert failed == []                      # not on the worker
            assert work.drain()
            assert failed == [(('bad',), 'bad', threading.current_thread())]
        finally:
            work.stop()

    def test_stopping_from_the_worker_itself_does_not_raise(self):
        stopped = []
        work = None

        def compute():
            work.stop()
            stopped.append(True)
        work = BackgroundCompute(compute, lambda payload: None)
        work.request()
        work._thread.join(5.0)
        assert stopped == [True] and not work.alive
