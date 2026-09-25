"""What a background resource load may and may not do
(:mod:`OpenGLContext.loaders.background`).

A texture, a shader, a panorama or an inlined scene is fetched and decoded on a
worker while the world goes on being drawn.  These hold that work to the rules
that keep a loading scene from wedging the process it is loading into: the
workers are bounded and shared, they import nothing of their own, and they
hand back a decoded image rather than an open file.
"""
import contextlib
import importlib
import sys
import threading
import time

import pytest
from PIL import Image

from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import imagetexture, shaders, hdrbackground, inline
from OpenGLContext.scenegraph.imagetexture import ImageTexture

#: How long a test waits for a load that should take milliseconds.
PATIENCE = 20.0


@contextlib.contextmanager
def watching_imports():
    """Record every ``(thread, module)`` the import machinery is asked to find.

    A finder is consulted only for a name that is not already in
    :data:`sys.modules`, so what this collects is first-use imports and nothing
    else.
    """
    seen = []

    class Watcher:
        def find_spec(self, name, path=None, target=None):
            seen.append((threading.current_thread(), name))
            return None

    watcher = Watcher()
    sys.meta_path.insert(0, watcher)
    try:
        yield seen
    finally:
        sys.meta_path.remove(watcher)


@contextlib.contextmanager
def unimported(*names):
    """Hide ``names`` from :data:`sys.modules`, so importing one is work again."""
    saved = {name: sys.modules.pop(name) for name in names if name in sys.modules}
    try:
        yield
    finally:
        sys.modules.update(saved)


def until(predicate, patience=PATIENCE):
    """Whether ``predicate`` became true within ``patience`` seconds."""
    deadline = time.time() + patience
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _image(tmp_path, name, size=(2, 3)):
    """A real image file on disk, and its path as a string."""
    path = tmp_path / name
    Image.new('RGB', size, (10, 20, 30)).save(path)
    return str(path)


def _arrived(texture, size=(2, 3)):
    """Whether the background load has put the image on the texture yet."""
    return getattr(texture.image, 'size', None) == size


#: The name every pool a test builds is called, so a leftover worker from one
#: test cannot be mistaken for a worker of the pool the next one is watching.
POOL_NAME = 'test-pool'


@pytest.fixture
def make_pool():
    """A factory for pools that are shut down when the test ends."""
    built = []

    def build(workers=2):
        pool = background.LoadPool(workers=workers, name=POOL_NAME)
        built.append(pool)
        return pool

    yield build
    for pool in built:
        assert pool.shutdown(PATIENCE), 'a test pool would not stop'


def pool_threads():
    """Every worker thread belonging to a pool a test built."""
    return [thread for thread in threading.enumerate()
            if thread.name.startswith(POOL_NAME)]


@pytest.fixture
def unprepared_pool(monkeypatch):
    """Give the engine a pool that has prepared nothing yet.

    A pool runs each ``prepare`` once and remembers it, so a test that wants to
    watch the preparation happen needs one that has not seen it before.
    """
    pool = background.LoadPool()
    monkeypatch.setattr(background, '_pool', pool)
    yield pool
    assert pool.shutdown(PATIENCE), 'the test pool would not stop'


class TestThePool:
    """:class:`~OpenGLContext.loaders.background.LoadPool` itself."""

    def test_submitted_work_runs(self, make_pool):
        pool = make_pool()
        done = []
        pool.submit('a thing', done.append, 'ran')
        assert pool.wait_for_idle(PATIENCE)
        assert done == ['ran']

    def test_it_never_holds_more_workers_than_it_was_given(self, make_pool):
        """Twenty loads at once are still three threads."""
        pool = make_pool(workers=3)
        release = threading.Event()
        for index in range(20):
            pool.submit('thing %d' % index, release.wait, PATIENCE)
        try:
            assert len(pool_threads()) <= 3
        finally:
            release.set()
        assert pool.wait_for_idle(PATIENCE)

    def test_it_starts_no_thread_until_there_is_work(self, make_pool):
        """A pool nobody has asked anything of costs nothing."""
        make_pool(workers=4)
        assert not pool_threads()

    def test_work_that_raises_is_reported_and_the_worker_lives(self, make_pool,
                                                               caplog):
        """One bad url must not take the loader down with it."""
        pool = make_pool(workers=1)

        def explode():
            raise ValueError('no such thing')

        done = []
        pool.submit('a broken thing', explode)
        pool.submit('a good thing', done.append, 'ran')
        assert pool.wait_for_idle(PATIENCE)
        assert done == ['ran']
        assert 'a broken thing' in caplog.text

    @pytest.mark.parametrize('ending', [SystemExit, KeyboardInterrupt])
    def test_work_that_ends_its_thread_is_reported_and_the_worker_lives(
            self, make_pool, caplog, ending):
        """A callback's sys.exit() is not a reason to stop loading the world."""
        pool = make_pool(workers=1)

        def leave():
            raise ending()

        done = []
        pool.submit('a thing that exits', leave)
        pool.submit('a good thing', done.append, 'ran')
        assert pool.wait_for_idle(PATIENCE)
        assert done == ['ran']
        assert 'a thing that exits' in caplog.text
        assert len(pool_threads()) == 1

    def test_a_worker_that_died_is_replaced(self, make_pool):
        """However it went, the pool does not count a dead thread as a worker."""
        pool = make_pool(workers=1)
        pool.submit('a thing', lambda: None)
        assert pool.wait_for_idle(PATIENCE)
        pool._queue.put(None)                  # the worker's own way to stop
        for thread in pool_threads():
            thread.join(PATIENCE)
        done = []
        pool.submit('a later thing', done.append, 'ran')
        assert pool.wait_for_idle(PATIENCE)
        assert done == ['ran']

    def test_preparation_runs_on_the_thread_that_submits(self, make_pool):
        """Which is the whole point of it -- see the import rule below."""
        where = []
        pool = make_pool(workers=1)
        pool.submit('a thing', lambda: None,
                    prepare=lambda: where.append(threading.current_thread()))
        assert pool.wait_for_idle(PATIENCE)
        assert where == [threading.main_thread()]

    def test_preparation_runs_once_however_many_loads_follow(self, make_pool):
        counted = []
        pool = make_pool(workers=2)

        def prepare():
            counted.append(1)

        for index in range(5):
            pool.submit('thing %d' % index, lambda: None, prepare=prepare)
        assert pool.wait_for_idle(PATIENCE)
        assert counted == [1]

    def test_a_load_that_submits_loads_prepares_them_first(self, make_pool):
        """An inlined scene submits its textures from a worker; what those
        loads import is made before the scene's own load is handed over."""
        where = []
        pool = make_pool(workers=1)

        def texture_prepare():
            where.append(threading.current_thread())

        def scene():
            pool.submit('a texture', lambda: None, prepare=texture_prepare)
        pool.submit('a scene', scene,
                    prepare=lambda: pool.prepare(texture_prepare))
        assert pool.wait_for_idle(PATIENCE)
        assert where == [threading.main_thread()]

    def test_a_preparation_first_reached_on_a_worker_is_reported(
            self, make_pool, caplog):
        pool = make_pool(workers=1)

        def scene():
            pool.submit('a texture', lambda: None, prepare=lambda: None)
        with caplog.at_level('WARNING'):
            pool.submit('a scene', scene)
            assert pool.wait_for_idle(PATIENCE)
        assert 'a texture' in caplog.text and 'loader thread' in caplog.text

    def test_waiting_on_an_empty_pool_answers_at_once(self, make_pool):
        assert make_pool(workers=1).wait_for_idle(0)

    def test_a_wait_that_expires_says_so(self, make_pool):
        pool = make_pool(workers=1)
        release = threading.Event()
        pool.submit('a slow thing', release.wait, PATIENCE)
        try:
            assert not pool.wait_for_idle(0.05)
            assert pool.pending() == 1
        finally:
            release.set()
        assert pool.wait_for_idle(PATIENCE)


class TestWhatALoaderThreadMayDo:
    def test_an_image_load_imports_nothing_of_its_own(self, tmp_path,
                                                      unprepared_pool):
        """A module imported for the first time on a loader thread is imported
        under CPython's import lock, which is held with the GIL released: a
        thread waiting for it answers to no signal, no ``KeyboardInterrupt``
        and no test runner's timeout.  So the imports a load needs are made by
        the thread that asks for the load."""
        path = _image(tmp_path, 'one.png')
        with unimported('OpenGLContext.loaders.loader'):
            with watching_imports() as seen:
                texture = ImageTexture(url=[path])
                assert until(lambda: _arrived(texture)), 'the image never arrived'
        off_thread = sorted({name for thread, name in seen
                             if thread is not threading.main_thread()})
        assert not off_thread, (
            'imported on a loader thread: %s' % (', '.join(off_thread),))

    def test_a_scene_prepares_every_kind_of_load_its_nodes_make(
            self, unprepared_pool):
        """An Inline's scene is read on a worker, and its textures, shaders
        and panoramas submit their loads from there."""
        inline.prepare_scene_loading()
        assert {imagetexture.prepare_image_loading,
                shaders.prepare_shader_loading,
                hdrbackground.prepare_panorama_loading} <= unprepared_pool._prepared

    @pytest.mark.parametrize('node,suffix', [
        ('OpenGLContext.scenegraph.imagetexture:ImageTexture', '.png'),
        ('OpenGLContext.scenegraph.inline:Inline', '.wrl'),
        ('OpenGLContext.scenegraph.shaders:GLSLShader', '.frag'),
        ('OpenGLContext.scenegraph.hdrbackground:HDRBackground', '.hdr'),
    ])
    def test_every_url_field_loads_on_the_shared_pool(self, tmp_path, node, suffix):
        """One thread per url is one per cubemap face and one per texture in a
        scene.  Every field that loads in the background shares the pool."""
        module, name = node.split(':')
        cls = getattr(importlib.import_module(module), name)
        before = {id(thread) for thread in threading.enumerate()}
        cls(url=[str(tmp_path / ('missing' + suffix))])
        assert background.wait_for_idle(PATIENCE)
        started = [thread for thread in threading.enumerate()
                   if id(thread) not in before]
        assert all(thread.name.startswith('oglc-load') for thread in started), (
            'threads outside the pool: %s'
            % ([thread.name for thread in started],))

    def test_a_finished_image_load_leaves_no_file_open(self, tmp_path):
        """PIL reads lazily, so an image nobody has looked at yet holds the
        file it came from open for as long as the texture lives -- six of them
        for a cubemap.  The decode belongs on the loader thread anyway."""
        psutil = pytest.importorskip('psutil')
        path = _image(tmp_path, 'two.png')
        texture = ImageTexture(url=[path])
        assert until(lambda: _arrived(texture)), 'the image never arrived'
        assert until(lambda: path not in [open_file.path for open_file
                                          in psutil.Process().open_files()]), (
            'the loaded image is still holding %s open' % (path,))
