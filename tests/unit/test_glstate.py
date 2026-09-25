"""The GL state managers put back what they changed, however the block ends.

Each is tried twice against a real context: a block that finishes, and a block
that raises, since a draw that raises part way is what leaves state behind for
the next view, the next pass or the next frame.
"""
import numpy as np
import pytest
from OpenGL import GL
from OpenGL.GL.shaders import compileProgram, compileShader

from OpenGLContext.passes import glstate


class Boom(Exception):
    """What the block raises."""


def run(manager, raising):
    """Enter ``manager``, and raise inside it if ``raising``."""
    if raising:
        with pytest.raises(Boom), manager:
            raise Boom()
    else:
        with manager:
            pass


def enabled(capability):
    return bool(GL.glIsEnabled(capability))


def integer(name):
    return int(np.asarray(GL.glGetIntegerv(name)).ravel()[0])


@pytest.fixture
def framebuffer(gl_context):
    """A complete framebuffer to bind, deleted afterwards."""
    fbo = int(GL.glGenFramebuffers(1))
    rbo = int(GL.glGenRenderbuffers(1))
    GL.glBindRenderbuffer(GL.GL_RENDERBUFFER, rbo)
    GL.glRenderbufferStorage(GL.GL_RENDERBUFFER, GL.GL_RGBA8, 4, 4)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, fbo)
    GL.glFramebufferRenderbuffer(GL.GL_FRAMEBUFFER, GL.GL_COLOR_ATTACHMENT0,
                                 GL.GL_RENDERBUFFER, rbo)
    GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
    yield fbo
    GL.glDeleteFramebuffers(1, [fbo])
    GL.glDeleteRenderbuffers(1, [rbo])


@pytest.mark.parametrize('raising', [False, True], ids=['finishes', 'raises'])
class TestTheManagersPutStateBack:
    @pytest.mark.usefixtures('gl_context')
    def test_enabled(self, raising):
        GL.glDisable(GL.GL_BLEND)
        GL.glEnable(GL.GL_DEPTH_TEST)
        run(glstate.enabled(GL.GL_BLEND, GL.GL_DEPTH_TEST), raising)
        assert not enabled(GL.GL_BLEND)
        assert enabled(GL.GL_DEPTH_TEST)

    @pytest.mark.usefixtures('gl_context')
    def test_disabled(self, raising):
        GL.glEnable(GL.GL_CULL_FACE)
        run(glstate.disabled(GL.GL_CULL_FACE), raising)
        assert enabled(GL.GL_CULL_FACE)

    @pytest.mark.usefixtures('gl_context')
    def test_switched(self, raising):
        GL.glDisable(GL.GL_BLEND)
        GL.glEnable(GL.GL_DEPTH_TEST)
        run(glstate.switched(enable=(GL.GL_BLEND,), disable=(GL.GL_DEPTH_TEST,)),
            raising)
        assert not enabled(GL.GL_BLEND)
        assert enabled(GL.GL_DEPTH_TEST)

    def test_bound_framebuffer(self, raising, framebuffer):
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        seen = []
        manager = glstate.bound_framebuffer(framebuffer)
        if raising:
            with pytest.raises(Boom), manager:
                seen.append(integer(GL.GL_DRAW_FRAMEBUFFER_BINDING))
                raise Boom()
        else:
            with manager:
                seen.append(integer(GL.GL_DRAW_FRAMEBUFFER_BINDING))
        assert seen == [framebuffer]
        assert integer(GL.GL_DRAW_FRAMEBUFFER_BINDING) == 0
        assert integer(GL.GL_READ_FRAMEBUFFER_BINDING) == 0

    def test_bound_framebuffer_for_one_target(self, raising, framebuffer):
        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
        run(glstate.bound_framebuffer(framebuffer, GL.GL_READ_FRAMEBUFFER), raising)
        assert integer(GL.GL_READ_FRAMEBUFFER_BINDING) == 0

    @pytest.mark.usefixtures('gl_context')
    def test_program(self, raising):
        made = int(compileProgram(
            compileShader('#version 330 core\nvoid main(){gl_Position=vec4(0);}',
                          GL.GL_VERTEX_SHADER),
            compileShader('#version 330 core\nout vec4 c;void main(){c=vec4(1);}',
                          GL.GL_FRAGMENT_SHADER),
            validate=False))
        GL.glUseProgram(0)
        try:
            run(glstate.program(made), raising)
            assert integer(GL.GL_CURRENT_PROGRAM) == 0
        finally:
            GL.glDeleteProgram(made)

    @pytest.mark.usefixtures('gl_context')
    def test_scissor(self, raising):
        GL.glDisable(GL.GL_SCISSOR_TEST)
        GL.glScissor(1, 2, 3, 4)
        run(glstate.scissor(5, 6, 7, 8), raising)
        assert not enabled(GL.GL_SCISSOR_TEST)
        assert list(np.asarray(GL.glGetIntegerv(GL.GL_SCISSOR_BOX)).ravel()) == [1, 2, 3, 4]

    @pytest.mark.usefixtures('gl_context')
    def test_cull_face(self, raising):
        GL.glCullFace(GL.GL_BACK)
        run(glstate.cull_face(GL.GL_FRONT), raising)
        assert integer(GL.GL_CULL_FACE_MODE) == GL.GL_BACK


@pytest.mark.usefixtures('gl_context')
class TestInside:
    def test_capabilities_asked_for_hold_inside(self):
        GL.glDisable(GL.GL_BLEND)
        with glstate.enabled(GL.GL_BLEND):
            assert enabled(GL.GL_BLEND)
        with glstate.switched(enable=(GL.GL_BLEND,), disable=(GL.GL_DEPTH_TEST,)):
            assert enabled(GL.GL_BLEND) and not enabled(GL.GL_DEPTH_TEST)

    def test_the_state_asked_for_holds_inside(self):
        GL.glEnable(GL.GL_SCISSOR_TEST)
        with glstate.scissor(5, 6, 7, 8):
            assert enabled(GL.GL_SCISSOR_TEST)
            assert list(np.asarray(GL.glGetIntegerv(GL.GL_SCISSOR_BOX)).ravel()) == [5, 6, 7, 8]
        assert enabled(GL.GL_SCISSOR_TEST)

    def test_a_program_known_to_be_bound_is_restored_without_asking(self, monkeypatch):
        asked = []
        real = glstate.glGetIntegerv
        monkeypatch.setattr(glstate, 'glGetIntegerv',
                            lambda name: asked.append(name) or real(name))
        with glstate.program(0, restore=0):
            pass
        assert asked == []


@pytest.mark.usefixtures('gl_context')
class TestTheFrameBaseline:
    def test_it_sets_what_it_is_given_and_leaves_the_rest(self):
        GL.glEnable(GL.GL_BLEND)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_SCISSOR_TEST)
        glstate.frame_baseline(enable=(GL.GL_DEPTH_TEST,), disable=(GL.GL_SCISSOR_TEST,),
                               cull_face=GL.GL_FRONT)
        assert enabled(GL.GL_DEPTH_TEST)
        assert not enabled(GL.GL_SCISSOR_TEST)
        assert enabled(GL.GL_BLEND)
        assert integer(GL.GL_CULL_FACE_MODE) == GL.GL_FRONT
        GL.glCullFace(GL.GL_BACK)
        GL.glDisable(GL.GL_BLEND)
