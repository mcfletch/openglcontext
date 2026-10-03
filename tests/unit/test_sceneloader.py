"""Loading scenes in the background (:mod:`OpenGLContext.loaders.sceneloader`).

A :class:`SceneLoader` reads a source on a worker and hands the result back on
the thread that polls it.  Nothing here is about a window: the owner below is
the least a context has to be, and the sources are strings, bytes and callables.

What is held: the producer runs off the polling thread, its result is delivered
*on* the polling thread, a failure is reported rather than raised into the
worker, and requests are independent -- any number in flight, each delivered
once, a cancelled one never.  The format comes from a registry a third party
adds to, and what comes back is the format's own result.
"""
import json
import os
import threading
import time

import pytest
from pydispatch import dispatcher

from OpenGLContext import plugins, telemetry
from OpenGLContext.events.renderqueue import RenderQueue
from OpenGLContext.loaders import sceneloader
from OpenGLContext.loaders.formats import UnknownSourceType
from OpenGLContext.loaders.sceneloader import (
    SCENE_FAILED, SCENE_LOADED, SCENE_LOADING, SceneLoader,
)
from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

WRLS = os.path.join(str(tests_root(__file__)), 'wrls')
GLTF_MODEL = os.path.join(WRLS, 'instanced_lattice.gltf')
VRML_WORLD = os.path.join(WRLS, '3shapes.wrl')


class _Owner:
    """What a loader asks of the context it serves: a redraw, and nothing else."""

    def __init__(self):
        self.redraws = 0

    def triggerRedraw(self, count=1):
        self.redraws += count


def _settled(loader, timeout=5.0):
    """Poll until something is delivered, and say how many were."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        delivered = loader.poll()
        if delivered:
            return delivered
        time.sleep(0.005)
    return 0


class TestTheHandover:
    def test_a_scene_is_produced_off_this_thread(self):
        """The producer must not run on the caller's thread -- that is the point."""
        loader = SceneLoader()
        where = {}

        def produce():
            where['thread'] = threading.current_thread().name
            return 'SCENE'

        request = loader.submit(produce)
        assert _settled(loader) == 1
        assert request.result == 'SCENE'
        assert where['thread'] != threading.current_thread().name

    def test_the_callback_runs_on_the_polling_thread(self):
        """Building the scenegraph is a GL upload, so it happens where GL is."""
        seen = {}
        loader = SceneLoader()
        loader.submit(lambda: 'SCENE', on_loaded=lambda request: seen.update(
            thread=threading.current_thread().name, result=request.result))
        assert _settled(loader)
        assert seen == {'thread': threading.current_thread().name,
                        'result': 'SCENE'}

    def test_nothing_finished_delivers_nothing(self):
        loader = SceneLoader()
        assert loader.poll() == 0
        release = threading.Event()
        loader.submit(lambda: release.wait(5.0))
        assert loader.poll() == 0
        release.set()
        assert _settled(loader) == 1

    def test_a_request_is_delivered_once(self):
        loader = SceneLoader()
        loader.submit(lambda: 'SCENE')
        assert _settled(loader) == 1
        assert loader.poll() == 0

    def test_a_request_says_where_it_stands(self):
        loader = SceneLoader()
        release = threading.Event()
        request = loader.submit(lambda: release.wait(5.0) and 'SCENE', label='a level')
        assert (request.state, request.done, request.delivered) == ('loading', False, False)
        assert loader.loading and loader.pending == (request,)
        release.set()
        assert request.wait(5.0)
        assert (request.state, request.delivered) == ('loaded', False)
        assert loader.poll() == 1
        assert (request.state, request.delivered) == ('loaded', True)
        assert not loader.loading and loader.pending == ()
        assert 'a level' in repr(request)

    def test_the_owner_is_asked_to_redraw_at_both_ends(self):
        owner = _Owner()
        loader = SceneLoader(owner=owner)
        loader.submit(lambda: 'SCENE')
        assert owner.redraws >= 1
        before = owner.redraws
        assert _settled(loader)
        assert owner.redraws > before

    def test_a_loader_with_no_owner_needs_nothing_of_one(self):
        loader = SceneLoader()
        loader.submit(lambda: 'SCENE')
        assert _settled(loader)


class TestSayingSoWhenItFails:
    def test_a_producer_that_raises_is_reported_not_lost(self):
        loader = SceneLoader()
        boom = ValueError('no such model')
        failed, loaded = [], []

        def produce():
            raise boom

        request = loader.submit(produce, on_loaded=loaded.append,
                                on_failed=failed.append)
        assert _settled(loader)
        assert failed == [request] and loaded == []
        assert request.error is boom and request.state == 'failed'

    def test_a_failure_does_not_kill_the_loader(self):
        """A bad model must leave the program able to load the next one."""
        loader = SceneLoader()
        loader.submit(lambda: 1 / 0)
        assert _settled(loader)
        recovered = loader.submit(lambda: 'RECOVERED')
        assert _settled(loader)
        assert recovered.result == 'RECOVERED'

    def test_a_request_with_no_callbacks_is_still_delivered(self):
        loader = SceneLoader()
        loader.submit(lambda: 1 / 0)
        assert _settled(loader) == 1

    def test_a_callback_that_raises_does_not_hold_back_the_next(self):
        """The exception reaches the caller of poll; the rest are not lost."""
        loader = SceneLoader()
        second = []

        def explode(request):
            raise RuntimeError('the callback broke')

        first = loader.submit(lambda: 'A', on_loaded=explode)
        assert first.wait(5.0)
        loader.submit(lambda: 'B', on_loaded=second.append).wait(5.0)
        with pytest.raises(RuntimeError, match='the callback broke'):
            loader.poll()
        assert _settled(loader) == 1
        assert second[0].result == 'B'


class TestIndependentRequests:
    """A world may be loaded more than once, and a program may load several."""

    def test_every_request_in_flight_is_delivered(self):
        loader = SceneLoader()
        arrived = []
        for name in 'abc':
            loader.submit(lambda name=name: name, label=name,
                          on_loaded=lambda request: arrived.append(request.result))
        deadline = time.time() + 5.0
        while len(arrived) < 3 and time.time() < deadline:
            loader.poll()
            time.sleep(0.005)
        assert sorted(arrived) == ['a', 'b', 'c']

    def test_one_failing_does_not_disturb_another(self):
        loader = SceneLoader()
        good, bad = [], []
        loader.submit(lambda: 1 / 0, on_failed=bad.append)
        loader.submit(lambda: 'OK', on_loaded=good.append)
        deadline = time.time() + 5.0
        while (not good or not bad) and time.time() < deadline:
            loader.poll()
            time.sleep(0.005)
        assert len(good) == 1 and len(bad) == 1

    def test_a_cancelled_request_is_never_delivered(self):
        """Page past a slow model and you get the one you stopped on."""
        loader = SceneLoader()
        arrived = []
        release = threading.Event()
        started = threading.Event()

        def slow():
            started.set()
            release.wait(5.0)
            return 'SLOW'

        stale = loader.submit(slow, on_loaded=arrived.append)
        assert started.wait(5.0)
        stale.cancel()
        loader.submit(lambda: 'FAST', on_loaded=arrived.append)
        assert _settled(loader) == 1
        release.set()
        time.sleep(0.05)
        assert loader.poll() == 0, 'the cancelled result was delivered'
        assert [request.result for request in arrived] == ['FAST']
        assert stale.cancelled

    def test_a_request_cancelled_after_it_finished_is_not_delivered(self):
        loader = SceneLoader()
        arrived = []
        request = loader.submit(lambda: 'SCENE', on_loaded=arrived.append)
        assert request.wait(5.0)
        request.cancel()
        assert loader.poll() == 0
        assert arrived == []

    def test_cancelling_a_delivered_request_changes_nothing(self):
        loader = SceneLoader()
        request = loader.submit(lambda: 'SCENE')
        assert _settled(loader)
        request.cancel()
        assert request.state == 'loaded'

    def test_cancel_all_drops_everything_pending(self):
        loader = SceneLoader()
        arrived = []
        requests = [loader.submit(lambda: 'x', on_loaded=arrived.append)
                    for _each in range(3)]
        loader.cancel_all()
        time.sleep(0.05)
        assert loader.poll() == 0 and arrived == []
        assert all(request.cancelled for request in requests)

    def test_a_closed_loader_delivers_nothing_and_takes_no_more(self):
        loader = SceneLoader(owner=_Owner())
        arrived = []
        loader.submit(lambda: 'x', on_loaded=arrived.append).wait(5.0)
        loader.close()
        assert loader.poll() == 0 and arrived == []
        with pytest.raises(RuntimeError, match='closed'):
            loader.submit(lambda: 'y')


class TestSignals:
    """The same three events, for code that was not the one that asked."""

    def _heard(self, loader, signal):
        heard = []

        def receiver(request):
            heard.append(request)

        dispatcher.connect(receiver, signal=signal, sender=loader, weak=False)
        return heard

    def test_loading_and_loaded_are_sent_with_the_request(self):
        loader = SceneLoader()
        loading = self._heard(loader, SCENE_LOADING)
        loaded = self._heard(loader, SCENE_LOADED)
        request = loader.submit(lambda: 'SCENE')
        assert loading == [request] and loaded == []
        assert _settled(loader)
        assert loaded == [request]

    def test_failed_is_sent_for_a_request_that_raised(self):
        loader = SceneLoader()
        failed = self._heard(loader, SCENE_FAILED)
        loaded = self._heard(loader, SCENE_LOADED)
        request = loader.submit(lambda: 1 / 0)
        assert _settled(loader)
        assert failed == [request] and loaded == []

    def test_a_signal_for_one_loader_is_not_heard_from_another(self):
        mine, other = SceneLoader(), SceneLoader()
        heard = self._heard(other, SCENE_LOADED)
        mine.submit(lambda: 'SCENE')
        assert _settled(mine)
        assert heard == []


class _Opens(SceneAdapter):
    """A format registered after the engine was imported: ``.thing``."""

    name = 'thing'
    accepts_content = True
    configured = None

    def configure(self, options):
        type(self).configured = options

    def read(self, source):
        return {'thing-from': source}

    def read_content(self, data, name=''):
        return {'thing-bytes': data, 'named': name}


@pytest.fixture
def thing_format():
    entry = plugins.Adapter('test-thing', 'nowhere.Opens',
                            ['.thing', 'model/x-thing'])
    entry.load = lambda: _Opens
    _Opens.configured = None
    yield entry
    plugins.Adapter.registry.remove(entry)


class TestReadingASource:
    def test_a_glb_comes_back_as_the_gltf_scene(self):
        from OpenGLContext.loaders.gltf.scene import GLTFScene
        loader = SceneLoader()
        request = loader.load(GLTF_MODEL)
        assert _settled(loader)
        assert isinstance(request.result, GLTFScene)
        assert request.reader.name == 'gltf'

    def test_a_world_comes_back_as_the_scenegraph_not_a_viewer_scene(self):
        """The native result: what to do with it is the caller's business."""
        from OpenGLContext.scenegraph.scenegraph import SceneGraph
        loader = SceneLoader()
        request = loader.load(VRML_WORLD)
        assert _settled(loader)
        assert isinstance(request.result, SceneGraph)
        assert not isinstance(request.result, ViewerScene)

    def test_the_reader_presents_what_was_read_for_a_viewer(self):
        loader = SceneLoader()
        request = loader.load(VRML_WORLD)
        assert _settled(loader)
        shown = request.reader.present(request.result)
        assert isinstance(shown, ViewerScene) and shown.radius > 0

    def test_a_path_object_is_a_source(self):
        import pathlib
        loader = SceneLoader()
        request = loader.load(pathlib.Path(VRML_WORLD))
        assert request.source == VRML_WORLD
        assert _settled(loader)

    def test_the_label_defaults_to_the_file_name(self):
        loader = SceneLoader()
        assert loader.load(VRML_WORLD).label == '3shapes.wrl'
        assert loader.load(VRML_WORLD, label='the three shapes').label \
            == 'the three shapes'

    def test_a_missing_file_fails_through_the_request(self):
        loader = SceneLoader()
        failed = []
        loader.load(os.path.join(WRLS, 'no-such-world.wrl'), on_failed=failed.append)
        assert _settled(loader)
        assert isinstance(failed[0].error, OSError)

    def test_format_names_the_adapter_whatever_the_file_is_called(self):
        loader = SceneLoader()
        request = loader.load(VRML_WORLD, format='vrml97')
        assert request.reader.name == 'vrml97'
        assert _settled(loader)

    def test_a_source_nothing_opens_is_refused_before_anything_starts(self):
        loader = SceneLoader()
        with pytest.raises(UnknownSourceType, match='recognised'):
            loader.load('picture.xyz')
        assert loader.pending == ()

    def test_an_unknown_format_name_is_refused(self):
        with pytest.raises(UnknownSourceType, match='no format named'):
            SceneLoader().load(VRML_WORLD, format='postscript')

    def test_options_reach_the_adapter_before_it_reads(self, thing_format):
        marker = object()
        SceneLoader().load('a.thing', options=marker)
        assert _Opens.configured is marker


class TestAFormatRegisteredLater:
    def test_it_loads_through_the_same_call(self, thing_format):
        loader = SceneLoader()
        request = loader.load('/data/a.thing')
        assert _settled(loader)
        assert request.result == {'thing-from': '/data/a.thing'}

    def test_a_served_resource_is_chosen_by_its_content_type(self, thing_format):
        loader = SceneLoader()
        request = loader.load('https://example.com/download?id=7',
                              content_type='model/x-thing; charset=utf-8')
        assert request.reader.name == 'thing'
        loader.cancel_all()


class TestAStreamedDataset:
    def test_the_native_result_is_the_streaming_terrain(self, tmp_path):
        """What is read is the node that streams; the viewer's scene is made of it."""
        import json
        from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
        path = tmp_path / 'tileset.json'
        path.write_text(json.dumps({
            'asset': {'version': '1.0'}, 'geometricError': 100.0,
            'root': {'boundingVolume': {'box': [0, 0, 0, 8, 0, 0, 0, 8, 0, 0, 0, 8]},
                     'geometricError': 0.0, 'refine': 'REPLACE'}}))
        loader = SceneLoader()
        request = loader.load(str(path))
        try:
            assert _settled(loader)
            assert isinstance(request.result, TilesTerrain)
            shown = request.reader.present(request.result)
            assert shown.group is request.result and shown.radius > 0
        finally:
            request.reader.shutdown()


class TestADocumentInMemory:
    def test_bytes_are_read_by_the_format_their_name_gives(self):
        with open(VRML_WORLD, 'rb') as handle:
            data = handle.read()
        loader = SceneLoader()
        request = loader.load(data, name='world.wrl')
        assert _settled(loader)
        assert request.result.children, 'the document was parsed'

    def test_a_gltf_in_memory_resolves_against_the_directory_it_names(self):
        from OpenGLContext.loaders.gltf.scene import GLTFScene
        with open(GLTF_MODEL, 'rb') as handle:
            data = handle.read()
        loader = SceneLoader()
        request = loader.load(data, name=GLTF_MODEL)
        assert _settled(loader)
        assert isinstance(request.result, GLTFScene)

    def test_bytes_with_a_format_need_no_name(self, thing_format):
        loader = SceneLoader()
        request = loader.load(b'abc', format='test-thing')
        assert _settled(loader)
        assert request.result == {'thing-bytes': b'abc', 'named': ''}

    def test_bytes_with_nothing_to_say_what_they_are_are_refused(self):
        with pytest.raises(UnknownSourceType, match='format= or a name='):
            SceneLoader().load(b'abc')

    def test_a_format_that_reads_only_from_where_it_is_refuses_bytes(self):
        with pytest.raises(UnknownSourceType, match='not from memory'):
            SceneLoader().load(b'{}', name='tileset.json')

    def test_the_base_adapter_has_no_content_reader(self):
        with pytest.raises(NotImplementedError, match='not from memory'):
            SceneAdapter().read_content(b'', 'x')


class TestTheDefaultAdapterContract:
    def test_reading_must_be_implemented(self):
        with pytest.raises(NotImplementedError):
            SceneAdapter().read('x')

    def test_load_is_read_then_present(self):
        class Plain(SceneAdapter):
            def read(self, source):
                return 'read:' + source

            def present(self, native):
                return 'presented:' + native

        assert Plain().load('x') == 'presented:read:x'

    def test_a_result_already_viewable_is_presented_as_it_is(self):
        scene = ViewerScene(group=object())
        assert SceneAdapter().present(scene) is scene


# -- a session recording ---------------------------------------------------


class _RecordedOwner(_Owner):
    """An owner with the three things a session recording asks of a context.

    ``OnDraw`` is what a frame is counted by, and ``mark`` is how anything says
    what it did; a ``Context`` has both already.
    """

    telemetry = None

    def __init__(self):
        super().__init__()
        self.drawn = 0

    def OnDraw(self, force=1):  # noqa: ARG002 the signature of the OnDraw it stands in for
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


def _load(loader, scene='SCENE', label='a level', **named):
    request = loader.submit(lambda: scene, label=label, **named)
    assert request.wait(5.0)
    return request


class TestMountingASceneAgain:
    """A level arrives when the disk and the decoder are finished with it,
    which is not the same frame twice.

    That is enough to take a session out of a replay on its own: the recorded
    input from then on is input the player gave to a world that had *already*
    started, and delivering it to one that started three frames earlier plays
    a different game.  So the frame a scene was delivered on is recorded, and a
    replay puts it back on that frame.
    """

    def test_delivering_one_is_marked(self, tmp_path):
        owner = _RecordedOwner()
        loader = SceneLoader(owner=owner)
        session = telemetry.start(owner, tmp_path / 'session.jsonl')
        try:
            owner.OnDraw()
            _load(loader, label='maps/ztn3dm1.bsp')
            assert loader.poll() == 1
        finally:
            session.close()
        marks = [json.loads(line) for line in
                 (tmp_path / 'session.jsonl').read_text().splitlines()
                 if json.loads(line).get('kind') == 'mark']
        assert marks[0]['name'] == sceneloader.SCENE_MARK == 'scene-mounted'
        assert marks[0]['fields'] == {'label': 'maps/ztn3dm1.bsp', 'loaded': True}
        assert marks[0]['frame'] == 1

    def test_a_replay_holds_it_until_the_frame_it_was_delivered_on(self, tmp_path):
        recorded = _RecordedOwner()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')
        for _each in range(3):
            recorded.OnDraw()
        recorded_loader = SceneLoader(owner=recorded)
        _load(recorded_loader)
        recorded_loader.poll()
        session.close()

        playing = _RecordedOwner()
        loader = SceneLoader(owner=playing)
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            arrived = []
            _load(loader, on_loaded=arrived.append)
            assert not loader.poll()            # ready, and not due yet
            playing.OnDraw()
            playing.OnDraw()
            assert not loader.poll()
            playing.OnDraw()
            assert loader.poll()
            assert [request.result for request in arrived] == ['SCENE']
        finally:
            driver.close()

    def test_a_failure_is_marked_and_held_the_same_way(self, tmp_path):
        """A level that would not load left the window on the menu at a
        particular frame, and the input after it was given to that menu."""
        recorded = _RecordedOwner()
        loader = SceneLoader(owner=recorded)
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')

        def broken():
            raise ValueError('no such map')

        recorded.OnDraw()
        loader.submit(broken, label='maps/nope.bsp').wait(5.0)
        loader.poll()
        session.close()

        playing = _RecordedOwner()
        playing_loader = SceneLoader(owner=playing)
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            failed = []
            playing_loader.submit(broken, label='maps/nope.bsp',
                                  on_failed=failed.append).wait(5.0)
            assert not playing_loader.poll()
            playing.OnDraw()
            assert playing_loader.poll()
            assert len(failed) == 1
        finally:
            driver.close()

    def test_a_recording_that_delivered_nothing_holds_nothing_up(self, tmp_path):
        """A replay must never wait for something the recording never did."""
        recorded = _RecordedOwner()
        session = telemetry.start(recorded, tmp_path / 'session.jsonl')
        recorded.OnDraw()
        session.close()

        playing = _RecordedOwner()
        loader = SceneLoader(owner=playing)
        driver = telemetry.start_replay(playing, tmp_path / 'session.jsonl')
        try:
            _load(loader)
            assert loader.poll()
        finally:
            driver.close()

    def test_an_owner_nobody_is_recording_delivers_at_once(self):
        owner = _RecordedOwner()
        loader = SceneLoader(owner=owner)
        _load(loader)
        assert loader.poll()


class TestWaitingForASceneARecordingAlreadyHad:
    """Holding a delivery back is only half of putting it on the right frame.

    A load takes as long as the disk and the decoder take, and the frames drawn
    meanwhile are whatever the machine managed: the same session recorded at 57
    frames of loading replays at 66 of them, and everything the recording says
    after that is then nine frames out of step.  So a replay that has reached
    the frame a scene was delivered on *waits* for the scene.
    """

    def recorded(self, tmp_path, frames=3):
        owner = _RecordedOwner()
        loader = SceneLoader(owner=owner)
        session = telemetry.start(owner, tmp_path / 'session.jsonl')
        for _each in range(frames):
            owner.OnDraw()
        _load(loader)
        loader.poll()
        session.close()
        return tmp_path / 'session.jsonl'

    def test_a_replay_past_the_frame_waits_for_the_load(self, tmp_path):
        journal = self.recorded(tmp_path)
        playing = _RecordedOwner()
        loader = SceneLoader(owner=playing)
        driver = telemetry.start_replay(playing, journal)
        try:
            held = threading.Event()
            arrived = []

            def slowly():
                held.wait(5.0)
                return 'SCENE'

            loader.submit(slowly, label='a level', on_loaded=arrived.append)
            for _each in range(6):              # past the recorded frame
                playing.OnDraw()
            threading.Timer(0.05, held.set).start()
            assert loader.poll()                # waited rather than missing it
            assert [request.result for request in arrived] == ['SCENE']
        finally:
            driver.close()

    def test_a_load_that_never_arrives_gives_the_frame_back(self, tmp_path):
        """A replay is diagnostic equipment: it may not hang on one."""
        journal = self.recorded(tmp_path)
        playing = _RecordedOwner()
        loader = SceneLoader(owner=playing)
        loader.sceneWaitSeconds = 0.05
        driver = telemetry.start_replay(playing, journal)
        try:
            never = threading.Event()
            loader.submit(lambda: never.wait(30.0), label='a level')
            for _each in range(6):
                playing.OnDraw()
            assert not loader.poll()
            never.set()
        finally:
            driver.close()

    def test_a_session_nobody_recorded_never_waits(self):
        """The ordinary case: a window that keeps drawing while a level loads."""
        owner = _RecordedOwner()
        loader = SceneLoader(owner=owner)
        never = threading.Event()
        loader.submit(lambda: never.wait(30.0), label='a level')
        assert not loader.poll()
        never.set()


# -- a context ----------------------------------------------------------------


@pytest.fixture
def empty_context():
    """A real context drawing nothing, as the suite's other scenes are drawn."""
    from OpenGLContext.testing.glcontext import profile_unavailable
    from OpenGLContext.testing.scenes import scene_context
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    with scene_context([]) as context:
        yield context


class TestEveryContextHasOne:
    def test_a_context_is_built_with_a_queue_and_a_loader_through_it(
            self, empty_context):
        assert isinstance(empty_context.renderQueue, RenderQueue)
        assert isinstance(empty_context.sceneLoader, SceneLoader)
        assert empty_context.sceneLoader._queue is empty_context.renderQueue

    def test_a_finished_load_asks_the_loop_for_a_frame(self, empty_context):
        empty_context.redrawRequest.clear()
        request = empty_context.sceneLoader.submit(lambda: 'SCENE')
        assert request.wait(5.0)
        deadline = time.time() + 5.0
        while len(empty_context.renderQueue) == 0 and time.time() < deadline:
            time.sleep(0.005)
        assert empty_context.redrawRequest.is_set()

    def test_the_loop_delivers_it_before_the_idle_hook(self, empty_context):
        """What the delivery builds is what the frame's idle hook sees."""
        order = []
        empty_context.OnIdle = lambda *_a: order.append('idle')
        request = empty_context.sceneLoader.submit(
            lambda: 'SCENE', on_loaded=lambda _request: order.append('delivered'))
        assert request.wait(5.0)
        deadline = time.time() + 5.0
        while len(empty_context.renderQueue) == 0 and time.time() < deadline:
            time.sleep(0.005)
        empty_context.loopIteration()
        assert order[:2] == ['delivered', 'idle']

    def test_a_delivery_asks_for_the_frame_that_shows_it(self, empty_context):
        request = empty_context.sceneLoader.submit(lambda: 'SCENE')
        assert request.wait(5.0)
        time.sleep(0.05)
        empty_context.redrawRequest.clear()
        assert empty_context.runRenderQueue() == 1
        assert empty_context.redrawRequest.is_set()

    def test_releasing_the_window_closes_the_loader(self, empty_context):
        arrived = []
        loader = empty_context.sceneLoader
        loader.submit(lambda: 'SCENE', on_loaded=arrived.append).wait(5.0)
        empty_context.releaseWindow()
        empty_context.runRenderQueue()
        assert arrived == []
        with pytest.raises(RuntimeError, match='closed'):
            loader.submit(lambda: 'again')

    def test_a_context_with_no_queue_makes_no_calls(self):
        from OpenGLContext.context import Context
        assert Context.__new__(Context).runRenderQueue() == 0


class TestABoundedRunWaitsForItsScene:
    """A capture counts frames of the scene it photographs, not of the wait."""

    def test_frames_are_not_counted_while_a_load_is_pending(self, empty_context):
        empty_context._autoExitFrames = 100
        empty_context._autoExitFrameCount = 0
        release = threading.Event()
        request = empty_context.sceneLoader.submit(lambda: release.wait(5.0))
        for _frame in range(4):
            empty_context.OnDraw(force=1)
        assert empty_context._autoExitFrameCount == 0
        assert empty_context.loadsPending()
        release.set()
        assert request.wait(5.0)
        empty_context.runRenderQueue()
        assert not empty_context.loadsPending()
        empty_context.OnDraw(force=1)
        assert empty_context._autoExitFrameCount == 1

    def test_a_cancelled_load_stops_holding_the_count(self, empty_context):
        empty_context._autoExitFrames = 100
        empty_context._autoExitFrameCount = 0
        release = threading.Event()
        empty_context.sceneLoader.submit(lambda: release.wait(5.0)).cancel()
        empty_context.OnDraw(force=1)
        release.set()
        assert empty_context._autoExitFrameCount == 1
