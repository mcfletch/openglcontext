"""A textured scene draws under a core profile.

``glEnable(GL_TEXTURE_2D)`` switches on a fixed-function texture unit.  A core
context has none, so the call is ``GLError(1280, 'invalid enumerant')`` -- and it
sits on the path every VRML97 ``ImageTexture`` takes, which puts the whole
remainder of the frame's geometry behind it.  A shader samples from a bound
texture and needs no enable at all.

The same applies to the wrap mode: ``GL_CLAMP`` was the fixed-function pipeline's
border-sampling clamp and is not a core wrap mode.  ``GL_CLAMP_TO_EDGE`` is,
and it is what ``GL_CLAMP`` did for a texture with no border set.
"""

import numpy as np
import pytest
from OpenGL import GL as gl

pytest.importorskip("glfw")
PIL = pytest.importorskip("PIL.Image")

from OpenGLContext.scenegraph import basenodes
from OpenGLContext import texture
from OpenGLContext.context import Context
from OpenGLContext.capture import read_back_buffer
from OpenGLContext.passes import renderpass
from tests.unit.glrender import base_env



@pytest.fixture(autouse=True)
def shader_paths(monkeypatch):
    """The VRML97 flat pass, which is what ``ImageTexture`` renders through.

    The PBR renderer binds its own material textures and never reaches
    ``_Texture.render``, so the path under test here is the flat core one.
    """
    base_env(monkeypatch)
    monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)


def checkerboard(size=8):
    """A texture with something in it, so a blank frame is distinguishable."""
    data = np.zeros((size, size, 3), dtype='B')
    data[::2, ::2] = 255
    data[1::2, 1::2] = (255, 32, 32)
    return PIL.fromarray(data, 'RGB')


def textured_scene(repeat=True):
    return [
        basenodes.Transform(translation=(0, 0, -6), children=[basenodes.Shape(
            geometry=basenodes.Box(size=(4, 4, 4)),
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=(1, 1, 1)),
                texture=basenodes.ImageTexture(
                    image=checkerboard(), repeatS=repeat, repeatT=repeat),
            ),
        )]),
        basenodes.PointLight(location=(0, 4, 6), intensity=1.0),
    ]


class TestAnImageTextureDrawsUnderCore:
    def test_the_frame_is_not_black(self, render_scene, monkeypatch):
        frames = []
        original = Context.SwapBuffers

        def capturing(self):
            frames.append(read_back_buffer()[0])
            return original(self)

        monkeypatch.setattr(Context, 'SwapBuffers', capturing)
        render_scene(textured_scene(), frames=4)
        assert frames, 'nothing was rendered'
        assert np.asarray(frames[-1]).max() > 0

    def test_nothing_failed_to_render(self, render_scene):
        render_scene(textured_scene(), frames=3)
        assert renderpass.FLAT.failures.summary() == []

    def test_a_clamped_texture_renders_too(self, render_scene):
        """``repeatS``/``repeatT`` off asks for the clamp core actually has."""
        render_scene(textured_scene(repeat=False), frames=3)
        assert renderpass.FLAT.failures.summary() == []


class TestBindingIsSeparateFromEnabling:
    @pytest.mark.usefixtures('gl_context')
    def test_bind_touches_no_fixed_function_state(self):
        """A shader needs the texture bound; the enable is a compatibility call."""

        tex = texture.Texture()
        tex.store(3, gl.GL_RGB, 2, 2, b'\xff' * 12)
        assert gl.glGetError() == gl.GL_NO_ERROR
        tex.bind()
        assert gl.glGetError() == gl.GL_NO_ERROR
        assert gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D) == tex.texture

    @pytest.mark.usefixtures('gl_context_compat')
    def test_enabling_is_what_a_compatibility_caller_asks_for(self):
        tex = texture.Texture()
        tex.store(3, gl.GL_RGB, 2, 2, b'\xff' * 12)
        tex()
        assert gl.glGetError() == gl.GL_NO_ERROR
        assert gl.glIsEnabled(gl.GL_TEXTURE_2D)
        tex.__exit__(None, None, None)
        assert not gl.glIsEnabled(gl.GL_TEXTURE_2D)
