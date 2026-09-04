"""Announcing a context's death, and the caches that listen for it.

The keying half of the problem -- a cache answering with another context's GL
names -- is covered per cache.  What is checked here is the other half: that
each cache holding this context's names is told when the context goes, and that
a backend makes the announcement while the context is still current.
"""
import pytest

from OpenGLContext import contextresources
# At module scope, so each cache registers its callback while this file is being
# collected.  A cache imported for the first time inside a test registers itself
# after ``restore_callbacks`` has taken its snapshot, and the teardown then hands
# back a registration the whole session needed.
from OpenGLContext.passes import renderpass, shaderpass
from OpenGLContext.scenegraph.teapot import Teapot
from OpenGLContext.scenegraph.text import shadertext


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
        from OpenGLContext.testing.glcontext import gl_available, hidden_window

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
        keep = lambda: called.append('keep')          # noqa: E731
        drop = lambda: called.append('drop')          # noqa: E731
        contextresources.on_context_lost(keep)
        contextresources.on_context_lost(drop)
        contextresources.forget_context_lost(drop)
        contextresources.context_lost()
        assert called == ['keep']

if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
