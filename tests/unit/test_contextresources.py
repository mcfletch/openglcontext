"""Announcing a context's death, and the caches that listen for it.

The keying half of the problem -- a cache answering with another context's GL
names -- is covered per cache.  What is checked here is the other half: that
each cache holding this context's names is told when the context goes, and that
a backend makes the announcement while the context is still current.
"""
import gc

import pytest
from OpenGL import contextdata, error

from OpenGLContext import contextresources, windowsystem
# At module scope, so each cache registers its callback while this file is being
# collected.  A cache imported for the first time inside a test registers itself
# after ``restore_callbacks`` has taken its snapshot, and the teardown then hands
# back a registration the whole session needed.
from OpenGLContext.passes import renderpass, shaderpass
from OpenGLContext.scenegraph.teapot import Teapot
from OpenGLContext.scenegraph.text import shadertext
from OpenGLContext.testing.glcontext import gl_available, hidden_window


@pytest.fixture(autouse=True)
def restore_callbacks():
    """Take back what this test registered, and nothing else.

    The registry is process-wide and populated at import time, so a test that
    adds to it would leak a callback into every test that follows.  Restoring a
    *snapshot* is the wrong way to stop that: a cache imported for the first
    time during a test registers itself while the test runs, and truncating to
    the snapshot deregisters it for the rest of the session -- which shows up as
    a later test finding that cache deaf.
    """
    before = list(contextresources._callbacks)
    yield
    for callback in list(contextresources._callbacks):
        if callback not in before:
            contextresources.forget_context_lost(callback)


class TestTheRegistry:
    def test_a_registered_callback_is_called(self):
        called = []
        contextresources.on_context_lost(lambda: called.append(True))
        contextresources.context_lost()
        assert called == [True]

    def test_registering_the_same_callable_twice_registers_it_once(self):
        called = []

        def drop():
            called.append(True)

        contextresources.on_context_lost(drop)
        contextresources.on_context_lost(drop)
        contextresources.context_lost()
        assert called == [True]

    def test_it_returns_the_callback_so_it_reads_as_a_decorator(self):
        called = []

        @contextresources.on_context_lost
        def drop():
            called.append(True)

        assert callable(drop)
        contextresources.context_lost()
        assert called == [True]

    def test_one_cache_raising_does_not_deny_the_rest_the_news(self, caplog):
        called = []

        def explodes():
            raise RuntimeError('the driver said no')

        contextresources.on_context_lost(explodes)
        contextresources.on_context_lost(lambda: called.append(True))
        contextresources.context_lost()
        assert called == [True]
        assert 'the driver said no' in caplog.text


@pytest.fixture
def current_context():
    """Whatever the caches would key an entry under right now.

    Not ``None``: a suite that has opened a window leaves PyOpenGL's idea of the
    current context set, so a test that assumed no context would seed its cache
    under a key the drop then rightly leaves alone.
    """
    return contextresources.context_key()


@pytest.fixture
def restore_caches():
    """Put every cache back as it was, whatever the test did to it.

    These are module and class globals the whole session renders through, so a
    sentinel left in one is a failure in some later test rather than in this one.
    """
    saved = (dict(shadertext._renderers), dict(Teapot._buffers),
             dict(shaderpass._shader_programs), dict(renderpass._passes),
             renderpass.FLAT)
    yield
    for cache, contents in (
        (shadertext._renderers, saved[0]),
        (Teapot._buffers, saved[1]),
        (shaderpass._shader_programs, saved[2]),
        (renderpass._passes, saved[3]),
    ):
        cache.clear()
        cache.update(contents)
    renderpass.FLAT = saved[4]


@pytest.mark.usefixtures('restore_caches')
class TestTheEnginesCachesListen:
    """Every cache keyed on the GL context is told when one goes.

    Seeding a cache under the key the current context would be given, then
    announcing the loss, runs the same code a closing window runs.
    """

    def test_the_text_renderers_are_dropped(self, current_context):
        shadertext._renderers[(current_context, 32)] = object()
        contextresources.context_lost()
        assert (current_context, 32) not in shadertext._renderers

    def test_the_teapots_vertex_arrays_are_dropped(self, current_context):
        Teapot._buffers[(current_context, 4)] = object()
        contextresources.context_lost()
        assert (current_context, 4) not in Teapot._buffers

    def test_the_vrml97_programs_are_dropped(self, current_context):
        shaderpass._shader_programs[current_context] = object()
        contextresources.context_lost()
        assert current_context not in shaderpass._shader_programs

    def test_the_render_pass_is_dropped(self, current_context):
        renderpass._passes[current_context] = object()
        contextresources.context_lost()
        assert current_context not in renderpass._passes

    def test_another_contexts_entries_are_left_alone(self):
        """Only the dying context's names go; a second window keeps its own."""
        other = object()                      # stands in for a second context
        shadertext._renderers[(other, 32)] = object()
        Teapot._buffers[(other, 4)] = object()
        shaderpass._shader_programs[other] = object()
        renderpass._passes[other] = object()

        contextresources.context_lost()

        assert (other, 32) in shadertext._renderers
        assert (other, 4) in Teapot._buffers
        assert other in shaderpass._shader_programs
        assert other in renderpass._passes


class TestTheBackendsAnnounceIt:
    def test_a_closing_test_window_announces_the_loss(self):
        """The window the test fixtures open says so as it goes.

        Hundreds of them open and close in one suite run, which is exactly the
        setting in which a driver hands the same address out again.
        """
        if not gl_available():
            pytest.skip('no GL context can be created in this process')

        called = []
        contextresources.on_context_lost(lambda: called.append(True))
        with hidden_window('context-lost'):
            assert called == []
        assert called == [True]


class TestUnregistering:
    """A callback bound to something that does not live as long as the process
    has to be able to hand itself back."""

    def test_a_forgotten_callback_is_not_called(self):
        called = []

        def drop():
            called.append(True)

        contextresources.on_context_lost(drop)
        assert contextresources.forget_context_lost(drop) is True
        contextresources.context_lost()
        assert called == []

    def test_forgetting_one_never_registered_is_not_an_error(self):
        assert contextresources.forget_context_lost(lambda: None) is False

    def test_the_others_are_left_alone(self):
        called = []

        def keep():
            called.append('keep')

        def drop():
            called.append('drop')

        contextresources.on_context_lost(keep)
        contextresources.on_context_lost(drop)
        contextresources.forget_context_lost(drop)
        contextresources.context_lost()
        assert called == ['keep']


class _Owner:
    """Something holding GL names of its own."""


class TestContextNames:
    """An owner's names, per context, deleted in the context that issued them."""

    @pytest.fixture
    def names(self, monkeypatch):
        """A ContextNames deleting into a list, with the current context settable."""
        deleted = []
        current = {'context': 'first'}
        monkeypatch.setattr(contextresources, 'context_key', lambda: current['context'])
        kept = contextresources.ContextNames(
            '_names', deleted.append, names=lambda entry: [entry[0]] if entry[0] else [])
        return kept, deleted, current

    def test_an_owner_holds_its_entries_per_context(self, names):
        kept, _deleted, current = names
        owner = _Owner()
        kept.entries(owner)['a'] = (1, 'metrics')
        current['context'] = 'second'
        assert kept.entries(owner) == {}
        current['context'] = 'first'
        assert kept.entries(owner) == {'a': (1, 'metrics')}

    def test_a_collected_owner_s_names_wait_for_their_own_context(self, names):
        kept, deleted, current = names
        owner = _Owner()
        kept.entries(owner).update({'a': (1, None), 'b': (None, None)})
        current['context'] = 'second'
        kept.entries(owner)['a'] = (2, None)
        del owner
        gc.collect()
        assert deleted == []
        kept.collect()
        assert deleted == [2]
        current['context'] = 'first'
        kept.entries(_Owner())
        assert deleted == [2, 1]

    def test_a_lost_context_s_names_are_deleted_and_forgotten(self, names):
        kept, deleted, current = names
        owner = _Owner()
        kept.entries(owner)['a'] = (1, None)
        current['context'] = 'second'
        kept.entries(owner)['a'] = (2, None)
        contextresources.context_lost()
        assert deleted == [2]
        assert kept.entries(owner) == {}
        current['context'] = 'first'
        assert kept.entries(owner) == {'a': (1, None)}

    def test_an_owner_that_cannot_hold_them_is_answered_none(self, names):
        kept, _deleted, _current = names
        assert kept.entries(object()) is None

    def test_by_default_an_entry_is_a_name(self, monkeypatch):
        deleted = []
        monkeypatch.setattr(contextresources, 'context_key', lambda: 'only')
        kept = contextresources.ContextNames('_names', deleted.append)
        owner = _Owner()
        kept.entries(owner)['a'] = 7
        contextresources.context_lost()
        assert deleted == [7]

if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestTheContextKey:
    """What every per-context table keys on: made only by ``context_key``."""

    @pytest.mark.usefixtures('gl_context')
    def test_the_current_context_has_one_key(self):
        key = contextresources.context_key()
        assert isinstance(key, contextresources.ContextKey)
        assert key == contextresources.context_key()
        assert hash(key) == hash(contextresources.context_key())
        assert {key: 1}[contextresources.context_key()] == 1

    @pytest.mark.usefixtures('gl_context')
    def test_a_key_is_not_its_raw_handle(self):
        key = contextresources.context_key()
        assert key != key.handle
        assert repr(key.handle) in repr(key)

    def test_a_key_is_not_made_directly(self):
        with pytest.raises(TypeError, match='context_key'):
            contextresources.ContextKey(1234, object())

    def test_no_current_context_has_no_key(self, monkeypatch):
        def none() -> None:
            raise error.Error('no context')

        monkeypatch.setattr(contextdata, 'getContext', none)
        assert contextresources.context_key() is None


@pytest.mark.usefixtures('gl_context')
def test_a_backend_names_the_context_to_pyopengl_by_its_handle():
    handle = contextresources.current_handle()
    assert not isinstance(handle, contextresources.ContextKey)
    assert handle == contextdata.getContext()
    assert handle == contextresources.context_key().handle


@pytest.mark.usefixtures('gl_context')
@pytest.mark.parametrize('name, toolkit', [
    ('glfw', 'glfw'),
    ('glut', 'OpenGL.GLUT'),
    ('pygame', 'pygame'),
    ('tk', 'tkinter'),
    ('wx', 'wx'),
    ('egl', 'OpenGL.EGL'),
    ('wgl', 'OpenGL.WGL.offscreen'),
])
def test_each_window_system_binds_pyopengl_to_the_platform_handle(name, toolkit):
    pytest.importorskip(toolkit)
    chosen = windowsystem.load(name)
    unopened = chosen.__new__(chosen)
    assert unopened.glHandle() == contextdata.getContext()


class TestAContextThatIsNotCurrent:
    """A window system that cannot make its context current as it closes.

    Its caches are told by the context's key: they forget its names, and delete
    none, since a GL name deleted now would be deleted in whatever context is
    current instead.
    """

    GONE = 'the-closed-windows-handle'

    @pytest.fixture
    def gone(self):
        return contextresources.key_for(self.GONE)

    def test_the_caches_forget_it_by_its_key(self, gone):
        shadertext._renderers[(gone, 32)] = object()
        Teapot._buffers[(gone, 4)] = object()
        shaderpass._shader_programs[gone] = object()
        contextresources.context_lost(gone)
        assert (gone, 32) not in shadertext._renderers
        assert (gone, 4) not in Teapot._buffers
        assert gone not in shaderpass._shader_programs

    def test_its_render_pass_is_forgotten_not_disposed(self, gone):
        disposed = []

        class Pass:
            def disposeResources(self):
                disposed.append(self)

        renderpass._passes[gone] = Pass()
        contextresources.context_lost(gone)
        assert gone not in renderpass._passes
        assert disposed == []

    def test_its_names_are_forgotten_not_deleted(self, gone, monkeypatch):
        deleted = []
        current = {'key': gone}
        monkeypatch.setattr(contextresources, '_current_key', lambda: current['key'])
        kept = contextresources.ContextNames('_names', deleted.append)
        owner = _Owner()
        kept.entries(owner)['a'] = 7
        current['key'] = 'another-window'
        contextresources.context_lost(gone)
        assert deleted == []
        current['key'] = gone
        assert kept.entries(owner) == {}

    def test_a_callback_is_told_which_context_and_that_it_may_not_delete(self, gone):
        told = []

        def listen():
            told.append((contextresources.context_key(), contextresources.deletable()))

        contextresources.on_context_lost(listen)
        try:
            contextresources.context_lost(gone)
        finally:
            contextresources.forget_context_lost(listen)
        assert told == [(gone, False)]
        assert contextresources.deletable()
        assert contextresources.context_key() != gone


class TestAContextSayingItIsGoing:
    """``Context.releaseContextResources`` names its own context."""

    def _context(self, own):
        from OpenGLContext.context import ContextCore
        made = ContextCore.__new__(ContextCore)
        made._ownContext = own
        return made

    def test_with_its_own_context_current_the_current_one_goes(self, monkeypatch):
        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda gone=None: told.append(gone))
        self._context('mine').releaseContextResources('mine')
        assert told == [None]

    @pytest.mark.parametrize('handle', [None, 'another-window'])
    def test_without_it_its_own_goes_by_key(self, monkeypatch, handle):
        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda gone=None: told.append(gone))
        self._context('mine').releaseContextResources(handle)
        assert told == [contextresources.key_for('mine')]

    def test_one_that_never_named_its_handle_tells_the_current_one(self, monkeypatch):
        told = []
        monkeypatch.setattr(contextresources, 'context_lost',
                            lambda gone=None: told.append(gone))
        self._context(None).releaseContextResources(None)
        assert told == [None]
