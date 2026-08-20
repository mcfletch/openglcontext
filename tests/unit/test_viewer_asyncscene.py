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
import json
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


class _RecordedHost(_Host):
    """A host with the two things a session recording asks of a context.

    A ``Context`` has both already: ``OnDraw`` is what a frame is counted by,
    and ``mark`` is how anything says what it did.
    """

    telemetry = None

    def __init__(self):
        super(_RecordedHost, self).__init__()
        self.drawn = 0

    def OnDraw(self, force=1):
        self.drawn += 1
        return 1

    def mark(self, name, /, **fields):
        if self.telemetry is not None:
            self.telemetry.mark(name, **fields)

    def reachedMark(self, name):
        session = self.telemetry
        return True if session is None else session.reached(name)

    def overdueMark(self, name):
        session = self.telemetry
        return False if session is None else session.overdue(name)


def _load(host, scene='SCENE', label='a level'):
    """Ask for a scene and wait until the worker has posted it."""
    host.requestScene(lambda: scene, label=label)
    deadline = time.time() + 5.0
    while host.sceneLoading and time.time() < deadline:
        time.sleep(0.005)


class TestMountingASceneAgain:
    """A level arrives when the disk and the decoder are finished with it,
    which is not the same frame twice.

    That is enough to take a session out of a replay on its own: the recorded
    input from then on is input the player gave to a world that had *already*
    started, and delivering it to one that started three frames earlier plays
    a different game.  So the frame a scene was mounted on is recorded, and a
    replay puts it back on that frame.
    """

    def test_mounting_one_is_marked(self, tmp_path):
        from OpenGLContext import telemetry
        host = _RecordedHost()
        session = telemetry.start(host, tmp_path / 'session.jsonl')
        try:
            host.OnDraw()
            _load(host, label='maps/ztn3dm1.bsp')
            assert host.pollPendingScene()
        finally:
            session.close()
        marks = [json.loads(line) for line in
                 (tmp_path / 'session.jsonl').read_text().splitlines()
                 if json.loads(line).get('kind') == 'mark']
        assert marks[0]['name'] == 'scene-mounted'
        assert marks[0]['fields'] == {'label': 'maps/ztn3dm1.bsp',
                                      'loaded': True}
        assert marks[0]['frame'] == 1

    def test_a_replay_holds_it_until_the_frame_it_was_mounted_on(self, tmp_path):
        from OpenGLContext import telemetry
        recorded = _RecordedHost()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')
        for _each in range(3):
            recorded.OnDraw()
        _load(recorded)
        recorded.pollPendingScene()
        session.close()

        playing = _RecordedHost()
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            _load(playing)
            assert not playing.pollPendingScene()   # ready, and not due yet
            playing.OnDraw()
            playing.OnDraw()
            assert not playing.pollPendingScene()
            playing.OnDraw()
            assert playing.pollPendingScene()
            assert playing.applied == ['SCENE']
        finally:
            driver.close()

    def test_a_failure_is_marked_and_held_the_same_way(self, tmp_path):
        """A level that would not load left the window on the menu at a
        particular frame, and the input after it was given to that menu."""
        from OpenGLContext import telemetry
        recorded = _RecordedHost()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')

        def broken():
            raise ValueError('no such map')

        recorded.OnDraw()
        recorded.requestScene(broken, label='maps/nope.bsp')
        deadline = time.time() + 5.0
        while recorded.sceneLoading and time.time() < deadline:
            time.sleep(0.005)
        recorded.pollPendingScene()
        session.close()

        playing = _RecordedHost()
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            playing.requestScene(broken, label='maps/nope.bsp')
            deadline = time.time() + 5.0
            while playing.sceneLoading and time.time() < deadline:
                time.sleep(0.005)
            assert not playing.pollPendingScene()
            playing.OnDraw()
            assert playing.pollPendingScene()
            assert len(playing.failures) == 1
        finally:
            driver.close()

    def test_a_recording_that_mounted_nothing_holds_nothing_up(self, tmp_path):
        """A replay must never wait for something the recording never did."""
        from OpenGLContext import telemetry
        recorded = _RecordedHost()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')
        recorded.OnDraw()
        session.close()

        playing = _RecordedHost()
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            _load(playing)
            assert playing.pollPendingScene()
        finally:
            driver.close()

    def test_a_host_nobody_is_recording_mounts_it_at_once(self):
        host = _RecordedHost()
        _load(host)
        assert host.pollPendingScene()


class TestWaitingForASceneARecordingAlreadyHad:
    """Holding a mount back is only half of putting it on the right frame.

    A load takes as long as the disk and the decoder take, and the frames drawn
    meanwhile are whatever the machine managed: the same session recorded at 57
    frames of loading replays at 66 of them, and everything the recording says
    after that is then nine frames out of step.  So a replay that has reached
    the frame a scene was mounted on *waits* for the scene.
    """

    def recorded(self, tmp_path, frames=3):
        from OpenGLContext import telemetry
        host = _RecordedHost()
        session = telemetry.start(host, tmp_path / 'session.jsonl')
        for _each in range(frames):
            host.OnDraw()
        _load(host)
        host.pollPendingScene()
        session.close()
        return tmp_path / 'session.jsonl'

    def test_a_replay_past_the_frame_waits_for_the_load(self, tmp_path):
        from OpenGLContext import telemetry
        journal = self.recorded(tmp_path)
        playing = _RecordedHost()
        driver = telemetry.start_replay(playing, journal)
        try:
            held = threading.Event()

            def slowly():
                held.wait(5.0)
                return 'SCENE'

            playing.requestScene(slowly, label='a level')
            for _each in range(6):              # past the recorded frame
                playing.OnDraw()
            threading.Timer(0.05, held.set).start()
            assert playing.pollPendingScene()   # waited rather than missing it
            assert playing.applied == ['SCENE']
        finally:
            driver.close()

    def test_a_load_that_never_arrives_gives_the_frame_back(self, tmp_path):
        """A replay is diagnostic equipment: it may not hang on one."""
        from OpenGLContext import telemetry
        journal = self.recorded(tmp_path)
        playing = _RecordedHost()
        playing.sceneWaitSeconds = 0.05
        driver = telemetry.start_replay(playing, journal)
        try:
            playing.requestScene(lambda: threading.Event().wait(30.0),
                                 label='a level')
            for _each in range(6):
                playing.OnDraw()
            assert not playing.pollPendingScene()
        finally:
            driver.close()

    def test_a_session_nobody_recorded_never_waits(self):
        """The ordinary case: a window that keeps drawing while a level loads."""
        host = _RecordedHost()
        host.requestScene(lambda: threading.Event().wait(30.0), label='a level')
        assert not host.pollPendingScene()
