"""The engine's GL caches hold N contexts, not the last one.

A GL object is a *name*, and the context that issued it is the only place that
name means anything -- so the render pass, the shader programs, the teapot's
vertex arrays and the text renderers are all keyed by context.

A key is not enough on its own.  A cache that keys correctly but holds one entry
answers the right question and then throws the answer away: two live contexts
alternating miss on every frame, so each one rebuilds what the other displaced,
and the displaced pass is dropped still holding GL objects in a context that is
alive and can never be told to let go of them.
"""

import pytest

from OpenGLContext import contextresources
from OpenGLContext.passes import renderpass, shaderpass
from OpenGLContext.testing import glcontext
from OpenGLContext.scenegraph import teapot
from OpenGLContext.scenegraph.text import shadertext


@pytest.fixture
def two_contexts(gl_window):
    """Two live GL contexts, and a way to make either current."""
    first = gl_window('cache-a', size=(32, 32))
    second = gl_window('cache-b', size=(32, 32))

    def current(handle):
        glcontext.make_current(handle)
        return contextresources.context_key()

    keys = (current(first), current(second))
    if keys[0] == keys[1] or not all(keys):
        pytest.skip('this platform cannot tell two contexts apart')
    yield first, second, current
    glcontext.release_current()


class TestTheShaderProgramsAreHeldPerContext:
    def test_each_context_keeps_its_own(self, two_contexts):
        first, second, current = two_contexts
        current(first)
        a = shaderpass.get_shader_program()
        current(second)
        b = shaderpass.get_shader_program()
        assert a is not b

    def test_going_back_finds_the_one_that_was_there(self, two_contexts):
        first, second, current = two_contexts
        current(first)
        a = shaderpass.get_shader_program()
        current(second)
        shaderpass.get_shader_program()
        current(first)
        assert shaderpass.get_shader_program() is a

    def test_alternating_does_not_recompile(self, two_contexts):
        """Twelve calls over two contexts must cost two compiles, not twelve.
        A VRML97ShaderProgram is six programs."""
        first, second, current = two_contexts
        built = []
        original = shaderpass.VRML97ShaderProgram.__init__

        def counting(self, *arguments, **named):
            built.append(1)
            return original(self, *arguments, **named)

        shaderpass.VRML97ShaderProgram.__init__ = counting
        try:
            for _frame in range(6):
                for window in (first, second):
                    current(window)
                    shaderpass.get_shader_program()
        finally:
            shaderpass.VRML97ShaderProgram.__init__ = original
        assert len(built) == 2, 'compiled %d times for two contexts' % (len(built),)

    def test_losing_one_context_leaves_the_other(self, two_contexts):
        first, second, current = two_contexts
        current(first)
        a = shaderpass.get_shader_program()
        current(second)
        b = shaderpass.get_shader_program()
        shaderpass.drop_shader_programs()          # second is current
        current(first)
        assert shaderpass.get_shader_program() is a
        current(second)
        assert shaderpass.get_shader_program() is not b


class _StandInPass:
    """What ``cached_pass`` stores and hands back.

    A real ``FlatPass`` needs a scenegraph and a context; what is under test is
    the caching rule, so this carries only the two things that rule reads --
    the scene it was built for, and whether its shadow maps were disposed of.
    """

    def __init__(self, scene):
        self.scene = scene
        self.disposed = 0

    def disposeShadowMaps(self):
        self.disposed += 1


class TestTheRenderPassIsHeldPerContext:
    def _pass_for(self, window, current, scene):
        current(window)
        return renderpass.cached_pass(scene, lambda: _StandInPass(scene))

    @pytest.fixture(autouse=True)
    def empty_cache(self):
        saved = dict(renderpass._passes)
        renderpass._passes.clear()
        yield
        renderpass._passes.clear()
        renderpass._passes.update(saved)

    def test_each_context_keeps_its_own(self, two_contexts):
        first, second, current = two_contexts
        scene = object()
        assert self._pass_for(first, current, scene) is not self._pass_for(
            second, current, scene
        )

    def test_going_back_finds_the_one_that_was_there(self, two_contexts):
        first, second, current = two_contexts
        scene = object()
        a = self._pass_for(first, current, scene)
        self._pass_for(second, current, scene)
        assert self._pass_for(first, current, scene) is a

    def test_a_new_scenegraph_replaces_this_contexts_pass_only(self, two_contexts):
        first, second, current = two_contexts
        one, two = object(), object()
        a = self._pass_for(first, current, one)
        b = self._pass_for(second, current, one)
        assert self._pass_for(first, current, two) is not a
        assert self._pass_for(second, current, one) is b

    def test_losing_a_context_drops_only_its_pass(self, two_contexts):
        first, second, current = two_contexts
        scene = object()
        a = self._pass_for(first, current, scene)
        self._pass_for(second, current, scene)
        current(second)
        renderpass.drop_pass()
        assert self._pass_for(first, current, scene) is a


class TestEveryCacheKeysTheSameWay:
    """Four caches, one question.  A fifth added later should not have to
    reinvent the answer."""

    def test_the_key_lives_in_contextresources(self):
        assert callable(contextresources.context_key)

    @pytest.mark.parametrize(
        'module,name',
        [
            (shaderpass, 'gl_context_key'),
            (teapot.Teapot, '_gl_context'),
            (shadertext, '_gl_context'),
        ],
    )
    def test_nothing_keeps_a_copy_of_it(self, module, name):
        assert getattr(module, name, None) in (
            None,
            contextresources.context_key,
        ), '%s.%s is a second implementation' % (module, name)


class TestReplacingAPassLetsGoOfItsShadowMaps:
    """The pass being replaced belongs to the context that is current, so its
    FBOs and textures can be deleted rather than left in a live context with
    nothing able to reach them."""

    @pytest.fixture(autouse=True)
    def empty_cache(self):
        saved = dict(renderpass._passes)
        renderpass._passes.clear()
        yield
        renderpass._passes.clear()
        renderpass._passes.update(saved)

    def test_a_scenegraph_swap_disposes_the_outgoing_pass(self, gl_context):
        one, two = object(), object()
        first = renderpass.cached_pass(one, lambda: _StandInPass(one))
        renderpass.cached_pass(two, lambda: _StandInPass(two))
        assert first.disposed == 1

    def test_losing_the_context_disposes_it(self, gl_context):
        scene = object()
        only = renderpass.cached_pass(scene, lambda: _StandInPass(scene))
        renderpass.drop_pass()
        assert only.disposed == 1
        assert renderpass._passes == {}

    def test_a_pass_that_raises_does_not_stop_the_replacement(self, gl_context):
        class Awkward(_StandInPass):
            def disposeShadowMaps(self):
                raise RuntimeError('the driver said no')

        one, two = object(), object()
        renderpass.cached_pass(one, lambda: Awkward(one))
        replacement = renderpass.cached_pass(two, lambda: _StandInPass(two))
        assert replacement.scene is two
