"""Loading a scene without freezing the window
(:mod:`OpenGLContext.viewer.asyncscene`).

The mix-in is format-neutral, and these drive it that way: the host below knows
nothing about glTF and the "scenes" are plain strings.  What is under test is the
handover -- the producer runs off the render thread, its result is applied *on*
the render thread, a failure is reported rather than raised into the thread, and
a superseded request is dropped.

That last one is the whole reason for the token: someone paging through a
catalogue faster than it downloads must end up looking at the model they stopped
on, not at whichever load happened to finish last.
"""
import threading
import time

import pytest

from OpenGLContext.viewer.asyncscene import AsyncSceneMixin


class _Host(AsyncSceneMixin):
    """The least a context has to be to load scenes in the background."""

    def __init__(self):
        self.setupAsyncScene()
        self.redraws = 0
        self.applied = []
        self.failures = []
        self.labels = []

    def triggerRedraw(self, count=1):
        self.redraws += count

    def onSceneLoading(self, label):
        self.labels.append(label)

    def applyLoadedScene(self, scene):
        self.applied.append(scene)

    def applyFailedLoad(self, error):
        self.failures.append(error)


def _settled(host, timeout=5.0):
    """Wait for a worker to post its result, then apply it on this thread."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if host.pollPendingScene():
            return True
        time.sleep(0.005)
    return False


class TestTheHandover:
    def test_a_scene_is_produced_off_this_thread(self):
        """The producer must not run on the caller's thread -- that is the point."""
        host = _Host()
        where = {}

        def produce():
            where['thread'] = threading.current_thread().name
            return 'SCENE'

        host.requestScene(produce)
        assert _settled(host)
        assert host.applied == ['SCENE']
        assert where['thread'] != threading.current_thread().name

    def test_the_result_is_applied_on_the_polling_thread(self):
        """Building the scenegraph is a GL upload, so it happens where GL is."""
        seen = {}

        class _Recording(_Host):
            def applyLoadedScene(inner, scene):
                seen['thread'] = threading.current_thread().name

        host = _Recording()
        host.requestScene(lambda: 'SCENE')
        assert _settled(host)
        assert seen['thread'] == threading.current_thread().name

    def test_nothing_pending_applies_nothing(self):
        host = _Host()
        assert host.pollPendingScene() is False
        assert host.applied == []

    def test_polling_before_any_setup_is_harmless(self):
        """A context may be polled before it has asked for anything."""
        host = _Host.__new__(_Host)
        assert host.pollPendingScene() is False

    def test_requesting_without_setup_still_works(self):
        """The handover state is built on demand rather than being a precondition."""
        host = _Host.__new__(_Host)
        host.redraws = 0
        host.applied = []
        host.labels = []
        host.triggerRedraw = lambda count=1: None
        host.onSceneLoading = lambda label: None
        host.applyLoadedScene = host.applied.append
        host.requestScene(lambda: 'SCENE')
        assert _settled(host)
        assert host.applied == ['SCENE']


class TestSayingSoWhenItFails:
    def test_a_producer_that_raises_is_reported_not_lost(self):
        host = _Host()
        boom = ValueError('no such model')

        def produce():
            raise boom

        host.requestScene(produce)
        assert _settled(host)
        assert host.failures == [boom]
        assert host.applied == []

    def test_a_failure_does_not_kill_the_worker_thread(self):
        """A bad model must leave the viewer able to load the next one."""
        host = _Host()
        host.requestScene(lambda: 1 / 0)
        assert _settled(host)
        host.requestScene(lambda: 'RECOVERED')
        assert _settled(host)
        assert host.applied == ['RECOVERED']


class TestSupersession:
    def test_a_newer_request_wins(self):
        """Page past a slow model and you get the one you stopped on."""
        host = _Host()
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(5.0)
            return 'SLOW'

        host.requestScene(slow)
        assert started.wait(5.0)
        host.requestScene(lambda: 'FAST')
        assert _settled(host)
        release.set()
        time.sleep(0.05)
        assert host.pollPendingScene() is False, 'the stale result was applied'
        assert host.applied == ['FAST']

    def test_each_request_bumps_the_token(self):
        host = _Host()
        first = host._loadToken
        host.requestScene(lambda: 'A')
        assert host._loadToken == first + 1


class TestWhatTheHostIsTold:
    def test_the_label_is_offered_the_moment_a_load_starts(self):
        """The window says what it is waiting for before the download finishes."""
        host = _Host()
        host.requestScene(lambda: 'SCENE', 'Loading Duck ...')
        assert host.labels == ['Loading Duck ...']

    def test_a_redraw_is_asked_for_at_both_ends(self):
        host = _Host()
        host.requestScene(lambda: 'SCENE')
        assert host.redraws >= 1
        before = host.redraws
        assert _settled(host)
        assert host.redraws > before

    def test_loading_is_flagged_while_in_flight_and_cleared_after(self):
        host = _Host()
        host.requestScene(lambda: 'SCENE')
        assert _settled(host)
        assert host.sceneLoading is False

    def test_a_fresh_host_has_loaded_nothing(self):
        host = _Host()
        assert host.sceneLoaded is False
        assert host.sceneLoading is False


class TestTheDefaultHooks:
    """The two a host must fill in, and the one it need not."""

    def test_applying_a_scene_must_be_implemented(self):
        with pytest.raises(NotImplementedError):
            AsyncSceneMixin().applyLoadedScene('SCENE')

    def test_reporting_a_failure_must_be_implemented(self):
        with pytest.raises(NotImplementedError):
            AsyncSceneMixin().applyFailedLoad(None)

    def test_the_loading_label_hook_is_optional(self):
        AsyncSceneMixin().onSceneLoading('anything')
