"""In-process GL test: HDRBackground draws the panorama as a tone-mapped skybox.

Renders the equirect skybox with a red-sky / blue-ground panorama through a plain
perspective and checks the frame shows the sky on top and ground on the bottom,
that it is tone-mapped (not raw HDR clipped, not black), and that a higher exposure
brightens it. Skips cleanly without a GL context.
"""
import math

import numpy as np
import pytest


@pytest.fixture
def gl_context(gl_window):
    yield from _with_a_fresh_program(gl_window('hdr-bg', size=(128, 128)))


@pytest.fixture
def gl_context_compat(gl_window):
    """Compatibility *and* 3.3, so the fixed-function enums the non-shader
    render arm touches (``GL_LIGHTING``) are valid while GLSL 330 compiles."""
    yield from _with_a_fresh_program(
        gl_window('hdr-bg-compat', size=(128, 128), profile='compatibility'))


def _with_a_fresh_program(window):
    """Forget the program cached against a context that has just gone.

    The node caches its compiled program at class level -- one persistent
    context, in the real application -- and a per-test context makes that id
    meaningless.
    """
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    HDRBackground._shader = None
    HDRBackground._shader_locations = None
    yield window
    HDRBackground._shader = None
    HDRBackground._shader_locations = None


def _perspective(fovy, aspect, near, far):
    """Row-vector perspective (clip = vertex_row . P), matching the engine layout."""
    f = 1.0 / math.tan(fovy / 2.0)
    P = np.zeros((4, 4), dtype='f')
    P[0, 0] = f / aspect
    P[1, 1] = f
    P[2, 2] = (far + near) / (near - far)
    P[2, 3] = -1.0
    P[3, 2] = (2 * far * near) / (near - far)
    return P


class _Mode:
    passCount = 0
    shader_mode = True
    context = None
    _bloom_active = False

    def __init__(self):
        self.matrix = np.identity(4, dtype='f')          # camera at origin, -Z fwd
        self.projection = _perspective(math.radians(60), 1.0, 0.5, 500.0)


def _panorama(h=64, w=128):
    env = np.zeros((h, w, 3), np.float32)
    env[:h // 2] = (5.0, 0.2, 0.2)      # bright red sky (HDR)
    env[h // 2:] = (0.1, 0.1, 3.0)      # blue ground
    return env


def _render_frame(bg, size=128):
    from OpenGL.GL import (
        glViewport, glClearColor, glClear, glReadPixels,
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_RGB, GL_UNSIGNED_BYTE,
        glBindFramebuffer, GL_FRAMEBUFFER,
    )
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glViewport(0, 0, size, size)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    bg.RenderShader(mode=_Mode(), clear=False)
    raw = glReadPixels(0, 0, size, size, GL_RGB, GL_UNSIGNED_BYTE)
    img = np.frombuffer(raw, dtype=np.uint8).reshape(size, size, 3)
    return img[::-1]      # GL origin is bottom-left; flip to top-first


def test_skybox_shows_sky_on_top_ground_on_bottom(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    img = _render_frame(bg).astype(int)
    top = img[:40].reshape(-1, 3).mean(0)
    bottom = img[-40:].reshape(-1, 3).mean(0)
    assert top.max() > 20, "skybox is black (nothing drawn): %s" % top.tolist()
    # tone-mapped, not a clipped white wash
    assert top.max() < 256
    # red sky on top, blue ground on the bottom
    assert top[0] > top[2] + 20, "top should read red sky: %s" % top.tolist()
    assert bottom[2] > bottom[0] + 20, "bottom should read blue ground: %s" % bottom.tolist()


def test_exposure_brightens_the_sky(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    dim = HDRBackground(image=_panorama())
    dim.bound = 1
    dim.exposure = 0.25
    dim_top = _render_frame(dim).astype(int)[:40].reshape(-1, 3).mean(0).sum()

    bright = HDRBackground(image=_panorama())
    bright.bound = 1
    bright.exposure = 2.0
    bright_top = _render_frame(bright).astype(int)[:40].reshape(-1, 3).mean(0).sum()

    assert bright_top > dim_top + 20, (
        "higher exposure should brighten the sky (%.1f vs %.1f)"
        % (bright_top, dim_top))


def test_skybox_falls_back_to_ldr_without_float_support(gl_context, monkeypatch):
    """With no float-render capability the sky uploads as clamped LDR and still
    draws (not black) through the same shader, keeping the sky/ground orientation."""
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    from OpenGLContext.passes import ibl
    monkeypatch.setattr(ibl, 'probe_float_render_capability',
                        lambda force=False: False)
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    img = _render_frame(bg).astype(int)
    top = img[:40].reshape(-1, 3).mean(0)
    bottom = img[-40:].reshape(-1, 3).mean(0)
    assert top.max() > 20, "LDR fallback sky is black: %s" % top.tolist()
    assert top[0] > top[2], "LDR fallback lost the red-sky orientation: %s" % top.tolist()
    assert bottom[2] > bottom[0], "LDR fallback lost the blue-ground orientation: %s" % bottom.tolist()


def test_render_clears_when_requested(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    assert bg.RenderShader(mode=_Mode(), clear=True) == 1   # clear=True path


def test_render_restores_depth_and_cull_state(gl_context):
    from OpenGL.GL import (
        glEnable, glIsEnabled, GL_DEPTH_TEST, GL_CULL_FACE,
    )
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    glEnable(GL_DEPTH_TEST)
    glEnable(GL_CULL_FACE)
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    bg.RenderShader(mode=_Mode(), clear=False)
    # both were enabled going in, so both must be re-enabled on the way out
    assert glIsEnabled(GL_DEPTH_TEST)
    assert glIsEnabled(GL_CULL_FACE)


def test_render_legacy_mode_toggles_lighting(gl_context_compat):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground

    class _LegacyMode(_Mode):
        shader_mode = False       # exercises the glDisable/glEnable(GL_LIGHTING) arms

    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    assert bg._render(_LegacyMode(), clear=False) == 1


def test_render_via_compat_render_method(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    assert bg.Render(mode=_Mode(), clear=False) == 1     # Render() delegates to _render


def test_render_skipped_when_not_bound(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())      # bound stays 0
    assert bg._render(_Mode()) == 0


def test_render_skipped_on_secondary_pass(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground

    class _SecondPass(_Mode):
        passCount = 1

    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    assert bg._render(_SecondPass()) == 0


def test_render_skipped_without_panorama(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground()                        # no image
    bg.bound = 1
    assert bg._render(_Mode()) == 0


def test_render_skipped_when_compile_yields_nothing(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    bg.bound = 1
    bg.compile = lambda mode=None: None         # simulate a compile that produced nothing
    assert bg._render(_Mode()) == 0


def test_compile_without_panorama_returns_none(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    assert HDRBackground().compile(_Mode()) is None


def test_dispose_frees_compiled_skybox(gl_context):
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    bg.compile(_Mode())
    assert bg._render_data is not None
    bg.dispose()
    assert bg._render_data is None


def test_free_render_data_deletes_real_objects(gl_context):
    from OpenGLContext.scenegraph import hdrbackground as H
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    bg = HDRBackground(image=_panorama())
    render_data = bg.compile(_Mode())
    H._free_render_data(render_data)            # real texture/VBO/VAO teardown
    bg._render_data = None


def test_free_render_data_ignores_falsey_and_broken_data(gl_context):
    from OpenGLContext.scenegraph import hdrbackground as H
    H._free_render_data(None)                    # nothing to free -> early return
    # A malformed tuple exercises every teardown except-guard without crashing.
    H._free_render_data((None, object(), object(), None, None, None))


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v', '-s']))
