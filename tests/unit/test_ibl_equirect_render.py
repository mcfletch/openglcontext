"""In-process GL test: an equirect HDR panorama becomes the IBL env cube.

Registers a distinctive equirectangular environment (red sky at the top, blue
ground at the bottom, green band at the equator) and builds an IBLProbe, then
reads back the env-cube faces to confirm the panorama is projected onto the cube
right-way-up: +Y face reads red, -Y reads blue, the side faces read green.

This validates ibl_equirect.frag and IBLProbe._render_equirect_env without the
full viewer. Skips cleanly when a GL context can't be created.
"""
import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")


@pytest.fixture
def gl_context():
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        pytest.skip("glfw init failed")
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    win = glfw.create_window(96, 96, "ibl-equirect", None, None)
    if not win:
        pytest.skip("no GL window")
    glfw.make_context_current(win)
    yield win
    glfw.destroy_window(win)


def _striped_equirect(h=64, w=128):
    """Red top third, green middle third, blue bottom third (HDR values > 1)."""
    env = np.zeros((h, w, 3), dtype=np.float32)
    third = h // 3
    env[:third] = (4.0, 0.0, 0.0)          # sky (+Y)
    env[third:2 * third] = (0.0, 3.0, 0.0)  # horizon
    env[2 * third:] = (0.0, 0.0, 4.0)       # ground (-Y)
    return env


def _read_cube_face(tex, face_offset, size):
    from OpenGL.GL import (
        glBindTexture, glGetTexImage, GL_TEXTURE_CUBE_MAP,
        GL_TEXTURE_CUBE_MAP_POSITIVE_X, GL_RGB, GL_FLOAT,
    )
    glBindTexture(GL_TEXTURE_CUBE_MAP, tex)
    raw = glGetTexImage(GL_TEXTURE_CUBE_MAP_POSITIVE_X + face_offset, 0,
                        GL_RGB, GL_FLOAT)
    arr = np.asarray(raw, dtype=np.float32).reshape(size, size, 3)
    return arr


def test_equirect_panorama_projected_onto_env_cube(gl_context):
    from OpenGLContext.passes import ibl

    ibl.set_equirect_env(_striped_equirect())
    try:
        probe = ibl.IBLProbe()
        if not probe.ensure_built():
            pytest.skip("IBL probe build failed on this driver")

        size = ibl.IBLProbe.ENV_SIZE
        py = _read_cube_face(probe.env, 2, size).mean(axis=(0, 1))   # +Y (up)
        ny = _read_cube_face(probe.env, 3, size).mean(axis=(0, 1))   # -Y (down)
        px = _read_cube_face(probe.env, 0, size).mean(axis=(0, 1))   # +X (side)

        # +Y face should be dominantly red (the sky band).
        assert py[0] > py[1] and py[0] > py[2], "up face not red: %s" % py.tolist()
        # -Y face should be dominantly blue (the ground band).
        assert ny[2] > ny[0] and ny[2] > ny[1], "down face not blue: %s" % ny.tolist()
        # side face straddles the equator -> green dominates.
        assert px[1] > px[0] and px[1] > px[2], "side face not green: %s" % px.tolist()
        # HDR range preserved (float cube, values well above 1).
        assert py[0] > 1.0, "HDR range lost in env cube (%s)" % py.tolist()
    finally:
        probe.release()
        ibl.set_equirect_env(None)


def test_irradiance_carries_the_environment_hue(gl_context):
    """The convolved irradiance for an up-facing normal must pick up the red sky."""
    from OpenGLContext.passes import ibl

    ibl.set_equirect_env(_striped_equirect())
    try:
        probe = ibl.IBLProbe()
        if not probe.ensure_built():
            pytest.skip("IBL probe build failed on this driver")
        size = ibl.IBLProbe.IRR_SIZE
        up = _read_cube_face(probe.irradiance, 2, size).mean(axis=(0, 1))
        # Diffuse irradiance integrates the whole hemisphere, but an up-facing
        # normal weights the red sky most, so red should lead.
        assert up[0] > up[2], "irradiance up-face lost the red sky bias: %s" % up.tolist()
    finally:
        probe.release()
        ibl.set_equirect_env(None)


def test_shared_include_compiles_both_shaders(gl_context):
    """Both hdr_background.frag (skybox) and ibl_equirect.frag (reflection) compile
    through the shared _cubemap_inc.glsl dirToEquirect, so they can't desync."""
    from OpenGLContext.passes.ibl import _compile
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground

    HDRBackground._shader = None
    HDRBackground._shader_locations = None
    try:
        reflection = _compile('ibl_equirect.frag')
        assert reflection, "reflection env shader failed to compile"
        program, locations = HDRBackground._compile_shader()
        assert program, "skybox shader failed to compile"
        assert locations['equirectMap'] != -1
    finally:
        HDRBackground._shader = None
        HDRBackground._shader_locations = None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v', '-s']))
