"""A procedural surface as it is drawn (GL, PBR core).

The maps say row 0 is the top of the texture and a height map is relief; on a
wall built from :mod:`OpenGLContext.scenegraph.surfaces` geometry, the top row
is at the top of the wall and relief rising up the wall is lit as a slope
facing down.
"""
import numpy as np
import pytest

pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes, surfaces
from tests.unit.glrender import base_env, frames_of

SIZE = (160, 120)


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    return monkeypatch


def _maps(base, height):
    size = len(height)
    return surfaces.Maps(base=np.asarray(base, 'd'), roughness=np.full((size, size), 0.9),
                         metallic=np.zeros((size, size)), height=np.asarray(height, 'd'))


def _wall(maps, x=0.0, relief=2.0):
    material = surfaces.pbr_material(maps, relief=relief, roughness=1.0, metallic=0.0)
    return surfaces.shape(surfaces.panel(1.6, 1.6, repeat=1.6), material,
                          translation=(x, 0.0, 0.0))


def _scene(*walls, light=(0.0, -1.0, -1.0)):
    return [basenodes.Viewpoint(position=(0.0, 0.0, 3.0)),
            basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=light, intensity=1.0)] + list(walls)


def test_the_top_row_of_a_surface_is_the_top_of_the_wall(render_scene, env):
    size = 32
    base = np.zeros((size, size, 3))
    base[:size // 2] = (1.0, 0.0, 0.0)          # row 0 onwards: the top
    base[size // 2:] = (0.0, 0.0, 1.0)
    frame = frames_of(render_scene, _scene(_wall(_maps(base, np.zeros((size, size)))),
                                           light=(0.0, 0.0, -1.0)),
                      frames=3, size=SIZE)[-1].astype(int)
    height, width = frame.shape[:2]
    top = frame[height // 2 - 25:height // 2 - 10, width // 2 - 10:width // 2 + 10]
    bottom = frame[height // 2 + 10:height // 2 + 25, width // 2 - 10:width // 2 + 10]
    # read_back_buffer answers rows top first.
    assert top[..., 0].mean() > top[..., 2].mean() + 30
    assert bottom[..., 2].mean() > bottom[..., 0].mean() + 30


def test_relief_rising_up_a_wall_faces_down_and_falling_faces_up(render_scene, env):
    """Lit from above and in front, the relief that faces up is the brighter."""
    size = 64
    grey = np.full((size, size, 3), 0.6)
    rows = np.linspace(0.0, 1.0, size)[:, None] * np.ones((1, size))
    rising = _maps(grey, rows[::-1])        # row 0, the top, is the highest
    falling = _maps(grey, rows)
    frame = frames_of(render_scene, _scene(_wall(rising, x=-0.9, relief=30.0),
                                           _wall(falling, x=0.9, relief=30.0)),
                      frames=3, size=SIZE)[-1].astype(int)
    height, width = frame.shape[:2]
    middle = slice(height // 2 - 10, height // 2 + 10)
    faces_down = frame[middle, width // 4 - 8:width // 4 + 8].mean()
    faces_up = frame[middle, 3 * width // 4 - 8:3 * width // 4 + 8].mean()
    assert faces_up > faces_down + 10
