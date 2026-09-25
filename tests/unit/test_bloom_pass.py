"""In-process GL test of the bloom post-process (no subprocess/viewer).

Renders a small bright square into the bloom pass's HDR target and composites; the
glow must bleed a soft halo around the square (which a no-bloom copy would not).
Skips cleanly when a GL context can't be created.
"""

import numpy as np
import pytest
from OpenGL.GL import (
    glViewport, glEnable, glDisable, glScissor, glClear, glClearColor,
    glReadPixels, GL_SCISSOR_TEST, GL_COLOR_BUFFER_BIT,
    GL_RGB, GL_UNSIGNED_BYTE, glBindFramebuffer, GL_FRAMEBUFFER,
)

from OpenGLContext.passes import bloom
from OpenGLContext.passes.bloom import BloomPass, bloom_enabled, scaled_rect, tile_uniforms


@pytest.fixture
def gl_context(gl_window):
    return gl_window('bloom', size=(96, 96))


@pytest.mark.usefixtures('gl_context')
def test_bloom_spreads_a_halo(gl_context):
    W = H = 96
    bp = BloomPass()

    # render a bright HDR square into the scene target (begin() binds + clears it)
    bp.begin(W, H)
    glEnable(GL_SCISSOR_TEST)
    cx0, cy0, s = 40, 40, 16
    glScissor(cx0, cy0, s, s)
    glClearColor(6.0, 6.0, 6.0, 1.0)          # HDR bright (>1, blooms)
    glClear(GL_COLOR_BUFFER_BIT)
    glDisable(GL_SCISSOR_TEST)

    bp.composite()                             # -> back to the default framebuffer

    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glViewport(0, 0, W, H)
    raw = glReadPixels(0, 0, W, H, GL_RGB, GL_UNSIGNED_BYTE)
    img = np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 3).astype(int)

    lum = img.max(axis=2)
    # the square (core) should be bright
    core = lum[cy0 + 2:cy0 + s - 2, cx0 + 2:cx0 + s - 2]
    assert core.mean() > 150, "bright square did not render (%.0f)" % core.mean()

    # a ring OUTSIDE the square must pick up the bloom halo (mid-bright), which a
    # plain copy would leave black.
    ring = np.ones((H, W), bool)
    ring[cy0 - 8:cy0 + s + 8, cx0 - 8:cx0 + s + 8] = False   # exclude core+near
    halo = np.zeros((H, W), bool)
    halo[cy0 - 8:cy0 + s + 8, cx0 - 8:cx0 + s + 8] = True
    halo[cy0 - 2:cy0 + s + 2, cx0 - 2:cx0 + s + 2] = False   # exclude the core
    halo_pixels = lum[halo]
    assert (halo_pixels > 15).mean() > 0.3, (
        "bloom did not spread a halo around the bright square "
        "(lit halo fraction %.2f)" % (halo_pixels > 15).mean())


def test_bloom_enabled_reads_env(monkeypatch):
    for val in ('1', 'on', 'true', 'YES'):
        monkeypatch.setenv('OPENGLCONTEXT_BLOOM', val)
        assert bloom_enabled() is True
    for val in ('', '0', 'off', 'no'):
        monkeypatch.setenv('OPENGLCONTEXT_BLOOM', val)
        assert bloom_enabled() is False


@pytest.mark.usefixtures('gl_context')
def test_same_size_begin_reuses_targets(gl_context):
    """A second begin() at the same size must not reallocate the scene target."""
    bp = BloomPass()
    bp.begin(64, 64)
    first_fbo = bp._targets.scene_fbo
    first_tex = bp._targets.scene_tex
    bp.begin(64, 64)                     # size unchanged -> early return in _ensure
    assert bp._targets.scene_fbo == first_fbo
    assert bp._targets.scene_tex == first_tex
    assert bp.size == (64, 64)


@pytest.mark.usefixtures('gl_context')
def test_resize_reallocates_targets(gl_context):
    """begin() at a new size releases the old targets and allocates fresh ones."""
    bp = BloomPass()
    bp.begin(64, 64)
    old_tex = bp._targets.scene_tex
    assert old_tex is not None
    bp.begin(96, 48)                     # different size -> _release_targets + realloc
    # The driver may recycle the freed texture name, so the id is not a reliable
    # witness -- the new dimensions are.
    assert bp.size == (96, 48)
    assert bp.bloom_size == (48, 24)
    assert bp._targets.scene_tex is not None


@pytest.mark.usefixtures('gl_context')
def test_release_targets_swallows_delete_errors(monkeypatch):
    """A GL failure while freeing any target must not escape _release_targets."""
    bp = BloomPass()
    bp.begin(32, 32)

    def boom(*_args, **_named):
        raise RuntimeError("simulated driver delete failure")

    monkeypatch.setattr(bloom, 'glDeleteFramebuffers', boom)
    monkeypatch.setattr(bloom, 'glDeleteTextures', boom)
    monkeypatch.setattr(bloom, 'glDeleteRenderbuffers', boom)
    bp._release_targets()                # every delete throws; must still reset
    assert bp._targets is None
    assert bp.size is None


class TestTiles:
    """Where each view's part of the glow is drawn and how far its samples reach."""

    def test_a_tile_of_the_window_is_the_same_tile_at_half_size(self):
        assert scaled_rect((100, 0, 100, 100), (200, 100), (100, 50)) == (50, 0, 50, 50)

    def test_tiles_that_meet_still_meet_at_half_size(self):
        left = scaled_rect((0, 0, 67, 101), (201, 101), (100, 50))
        right = scaled_rect((67, 0, 134, 101), (201, 101), (100, 50))
        assert left[0] + left[2] == right[0]
        assert left[2] + right[2] == 100

    def test_the_whole_target_is_sampled_edge_to_edge(self):
        region, bounds = tile_uniforms((0, 0, 100, 50), (100, 50))
        assert region == (0.0, 0.0, 1.0, 1.0)
        # The first and last texel centres, which is where GL_CLAMP_TO_EDGE
        # stops a sample anyway.
        assert bounds == (0.005, 0.01, 0.995, 0.99)

    def test_a_tile_is_sampled_only_inside_itself(self):
        region, bounds = tile_uniforms((50, 0, 50, 50), (100, 50))
        assert region == (0.5, 0.0, 0.5, 1.0)
        assert bounds[0] == 0.505 and bounds[2] == 0.995
