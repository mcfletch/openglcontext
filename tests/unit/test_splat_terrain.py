"""SplatTerrain node — CPU-only construction and guarded render paths.

The GL draw path is covered by ``test_vegetation_gl_render``; these cover the
parts that need no context: the default material resolver, the bounding volume,
the shadow/invisible/disabled early-outs, and dispose-before-init.
"""
import types

import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.terrain.splat import SplatTerrain


def _hf():
    grid = np.linspace(0, 1, 8)[:, None] * np.ones((8, 8))
    return HeightField(grid, 100.0, 10.0)


def test_default_material_fn_falls_back_to_cc0():
    node = SplatTerrain(_hf(), ["floor"], "control.png")
    # No material_fn passed -> the cc0 loader's material function is used.
    assert node.material_fn.__module__.endswith("cc0")


def test_bounding_volume_spans_extent_and_triple_relief():
    node = SplatTerrain(_hf(), ["floor"], "control.png",
                        material_fn=lambda *a, **k: {})
    bv = node.boundingVolume(None)
    assert tuple(float(v) for v in bv.size) == (100.0, 30.0, 100.0)


def test_render_is_noop_in_shadow_pass():
    node = SplatTerrain(_hf(), ["floor"], "control.png",
                        material_fn=lambda *a, **k: {})
    assert node.render(types.SimpleNamespace(shadow_pass=True, visible=True)) == 1
    assert node._gl is None                        # never initialized GL


def test_render_is_noop_when_disabled():
    node = SplatTerrain(_hf(), ["floor"], "control.png",
                        material_fn=lambda *a, **k: {})
    node._disabled = True                          # a prior GL init failure
    assert node.render(types.SimpleNamespace(shadow_pass=False, visible=True)) == 1


def test_dispose_before_init_is_a_noop():
    node = SplatTerrain(_hf(), ["floor"], "control.png",
                        material_fn=lambda *a, **k: {})
    node.dispose()                                 # nothing allocated yet
    assert node._gl is None


def test_sun_direction_is_normalized():
    node = SplatTerrain(_hf(), ["floor"], "control.png", sun=(0.0, -2.0, 0.0),
                        material_fn=lambda *a, **k: {})
    assert np.isclose(np.linalg.norm(node.sun), 1.0)


glfw = pytest.importorskip("glfw")
from PIL import Image  # noqa: E402
from OpenGL.GL import glGetError, GL_NO_ERROR  # noqa: E402


@pytest.fixture
def gl():
    if not glfw.init():
        pytest.skip("glfw init failed (no GL)")
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    win = glfw.create_window(64, 64, "splat", None, None)
    if not win:
        glfw.terminate()
        pytest.skip("no core-profile GL context available")
    glfw.make_context_current(win)
    try:
        yield win
    finally:
        glfw.destroy_window(win)
        glfw.terminate()


def test_canopy_shadow_is_baked_into_the_sun_texture(gl, tmp_path):
    """With a canopy occlusion grid the terrain bakes a darkened sun-shadow
    texture (the tree-shadow path) rather than the bare sun term."""
    tex = tmp_path / "layer.png"
    Image.new("RGBA", (8, 8), (120, 110, 90, 255)).save(tex)
    ctl = tmp_path / "control.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(ctl)

    grid = np.linspace(0, 1, 8)[:, None] * np.ones((8, 8))
    hf = HeightField(grid, 100.0, 10.0)
    canopy = np.array([[10.0, 0.0, 3.0]], 'd')      # one canopy disc (x, z, radius)
    node = SplatTerrain(hf, ["floor"], str(ctl),
                        material_fn=lambda name, res: {"color": str(tex)},
                        canopy=canopy)
    mode = types.SimpleNamespace(matrix=np.eye(4, dtype='f4'),
                                 projection=np.eye(4, dtype='f4'),
                                 shadow_pass=False, visible=True)
    node.render(mode)
    assert glGetError() == GL_NO_ERROR
    assert node._gl is not None
    node.dispose()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestHowDeepTheShadeIs:
    """A forest floor is *dark*, and the default dappling is a light one. The
    depth of the canopy term is the world's to choose, because how much light
    reaches the ground is what makes a wood read as a wood."""

    def _hf(self):
        grid = np.zeros((32, 32))
        return HeightField(grid, 400.0, 10.0)

    def _lit(self, **named):
        field = self._hf()
        trees = np.stack([np.linspace(-150, 150, 400), np.zeros(400),
                          np.zeros(400)], axis=-1)
        node = SplatTerrain(field, ['grass'], 'control.png', **named)
        node.canopy = trees
        lit = field.sun_shadow(node.sun)
        return field.canopy_shadow(lit, trees, node.sun,
                                   spread=node.canopy_spread,
                                   darken=node.canopy_shade,
                                   cap=node.canopy_deepest)

    def test_the_ground_under_the_trees_is_darker(self) -> None:
        assert float(self._lit().min()) < 0.9

    def test_a_deeper_setting_is_darker(self) -> None:
        assert float(self._lit(canopy_deepest=0.9).min()) \
            < float(self._lit(canopy_deepest=0.2).min())

    def test_the_default_is_a_forest_rather_than_an_orchard(self) -> None:
        node = SplatTerrain(self._hf(), ['grass'], 'control.png')
        assert node.canopy_deepest >= 0.6

    def test_the_shadow_falls_away_from_the_sun(self) -> None:
        """Trees cast towards the ground, not straight down."""
        node = SplatTerrain(self._hf(), ['grass'], 'control.png')
        assert node.canopy_spread > 0.0
