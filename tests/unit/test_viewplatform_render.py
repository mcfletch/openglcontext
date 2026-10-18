"""ViewPlatform.render loads the platform's own matrices into the fixed-function stacks.

The compatibility profile's camera is the GL projection and model-view
matrices; what render() puts there is what viewMatrix() and modelMatrix()
compute for a core-profile pass.
"""
import numpy as np
import pytest
from OpenGL import GL as gl

from OpenGLContext.move.viewplatform import ViewPlatform


def _platform():
    return ViewPlatform(position=(1.0, 2.0, 8.0), orientation=(0, 1, 0, 0.4),
                        aspect=1.5, near=0.5, far=200.0)


def _loaded(stack):
    return np.asarray(gl.glGetFloatv(stack), 'd').reshape(4, 4)


@pytest.mark.usefixtures('gl_context_compat')
def test_the_projection_is_the_platforms_view_matrix():
    platform = _platform()
    platform.render(identity=True)
    assert _loaded(gl.GL_PROJECTION_MATRIX) == pytest.approx(
        np.asarray(platform.viewMatrix(), 'd'), abs=1e-5)


@pytest.mark.usefixtures('gl_context_compat')
def test_the_model_view_is_the_platforms_model_matrix():
    platform = _platform()
    platform.render(identity=True)
    assert _loaded(gl.GL_MODELVIEW_MATRIX) == pytest.approx(
        np.asarray(platform.modelMatrix(), 'd'), abs=1e-5)


@pytest.mark.usefixtures('gl_context_compat')
def test_without_identity_it_multiplies_what_is_loaded():
    platform = _platform()
    gl.glMatrixMode(gl.GL_PROJECTION)
    gl.glLoadIdentity()
    gl.glScaled(2.0, 2.0, 2.0)
    platform.render()
    scale = np.diag([2.0, 2.0, 2.0, 1.0])
    assert _loaded(gl.GL_PROJECTION_MATRIX) == pytest.approx(
        np.asarray(platform.viewMatrix(), 'd') @ scale, abs=1e-5)
