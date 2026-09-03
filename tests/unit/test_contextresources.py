"""Announcing a context's death, and the caches that listen for it.

The keying half of the problem -- a cache answering with another context's GL
names -- is covered per cache.  What is checked here is the other half: that
each cache holding this context's names is told when the context goes, and that
a backend makes the announcement while the context is still current.
"""
import pytest

from OpenGLContext import contextresources


@pytest.fixture(autouse=True)
def restore_callbacks():
    """Leave the registry exactly as it was found.

    It is process-wide and populated at import time, so a test that adds to it
    would otherwise leak a callback into every test that follows.
    """
    saved = list(contextresources._callbacks)
    yield
    contextresources._callbacks[:] = saved


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
    from OpenGLContext.passes.shaderpass import gl_context_key

    return gl_context_key()


@pytest.fixture
def restore_caches():
    """Put every cache back as it was, whatever the test did to it.

    These are module and class globals the whole session renders through, so a
    sentinel left in one is a failure in some later test rather than in this one.
    """
    from OpenGLContext.passes import renderpass, shaderpass
    from OpenGLContext.scenegraph.teapot import Teapot
    from OpenGLContext.scenegraph.text import shadertext

    saved = (dict(shadertext._renderers), dict(Teapot._buffers),
             shaderpass._shader_program, shaderpass._shader_program_context,
             renderpass.FLAT, renderpass.FLAT_CONTEXT)
    yield
    (shadertext._renderers, Teapot._buffers) = ({}, {})
    shadertext._renderers.update(saved[0])
    Teapot._buffers.update(saved[1])
    (shaderpass._shader_program, shaderpass._shader_program_context,
     renderpass.FLAT, renderpass.FLAT_CONTEXT) = saved[2:]


@pytest.mark.usefixtures('restore_caches')
class TestTheEnginesCachesListen:
    """Every cache keyed on the GL context is told when one goes.

    Seeding a cache under the key the current context would be given, then
    announcing the loss, runs the same code a closing window runs.
    """

    def test_the_text_renderers_are_dropped(self, current_context):
        from OpenGLContext.scenegraph.text import shadertext

        shadertext._renderers[(current_context, 32)] = object()
        contextresources.context_lost()
        assert (current_context, 32) not in shadertext._renderers

    def test_the_teapots_vertex_arrays_are_dropped(self, current_context):
        from OpenGLContext.scenegraph.teapot import Teapot

        Teapot._buffers[(current_context, 4)] = object()
        contextresources.context_lost()
        assert (current_context, 4) not in Teapot._buffers

    def test_the_vrml97_programs_are_dropped(self, current_context):
        from OpenGLContext.passes import shaderpass

        shaderpass._shader_program = object()
        shaderpass._shader_program_context = current_context
        contextresources.context_lost()
        assert shaderpass._shader_program is None

    def test_the_render_pass_is_dropped(self, current_context):
        from OpenGLContext.passes import renderpass

        renderpass.FLAT = object()
        renderpass.FLAT_CONTEXT = current_context
        contextresources.context_lost()
        assert renderpass.FLAT is None

    def test_another_contexts_entries_are_left_alone(self):
        """Only the dying context's names go; a second window keeps its own."""
        from OpenGLContext.passes import renderpass, shaderpass
        from OpenGLContext.scenegraph.teapot import Teapot
        from OpenGLContext.scenegraph.text import shadertext

        other = object()                      # stands in for a second context
        shadertext._renderers[(other, 32)] = object()
        Teapot._buffers[(other, 4)] = object()
        shaderpass._shader_program = object()
        shaderpass._shader_program_context = other
        renderpass.FLAT = object()
        renderpass.FLAT_CONTEXT = other

        contextresources.context_lost()

        assert (other, 32) in shadertext._renderers
        assert (other, 4) in Teapot._buffers
        assert shaderpass._shader_program is not None
        assert renderpass.FLAT is not None


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


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
