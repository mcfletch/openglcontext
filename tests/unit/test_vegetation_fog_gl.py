"""The scene's Fog node reaches the instanced vegetation, on a real driver.

Each node draws a green surface 20 m down -Z. Absolute colours depend on tone
mapping and the driver; the relations between renders of one scene do not, so each
test compares the middle of two frames.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from PIL import Image

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.fog import Fog
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.clumps import InstancedClumps
from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD
from tests.unit.glrender import base_env, frames_of
from tests.unit.test_fog_render_gl import middle

DISTANCE = 20.0
NEAR_RANGE = 25.0
FAR_RANGE = 400.0


@pytest.fixture(autouse=True)
def shader_paths(monkeypatch):
    base_env(monkeypatch)


def green(path):
    Image.new('RGBA', (4, 4), (40, 160, 40, 255)).save(path)
    return str(path)


def billboards(tmp_path):
    return InstancedBillboards(np.array([[0, -2, -DISTANCE]], 'f4'), np.zeros(1, 'f4'),
                               np.array([14.0], 'f4'), green(tmp_path / 'card.png'), width=1.0)


def triangle():
    positions = np.array([[-8, -2, 0], [8, -2, 0], [0, 14, 0]], 'f4')
    normals = np.tile(np.array([0, 0, 1], 'f4'), (3, 1))
    uvs = np.array([[0, 0], [1, 0], [0.5, 1]], 'f4')
    return positions, normals, uvs, np.array([0, 1, 2], np.uint32)


def clumps(tmp_path):
    node = InstancedClumps(*triangle(), Image.open(green(tmp_path / 'blade.png')))
    node.update_instances(np.array([[0, 0, -DISTANCE]], 'f4'), np.zeros(1, 'f4'),
                          np.ones(1, 'f4'))
    return node


def trees(tmp_path):
    positions, normals, uvs, indices = triangle()
    npz = tmp_path / 'tree.npz'
    np.savez(str(npz), P=positions, N=normals, U=uvs, I=indices)
    node = InstancedMeshLOD(
        np.array([[0, 0, -DISTANCE]], 'f4'), np.zeros(1, 'f4'), np.ones(1, 'f4'),
        [dict(npz=str(npz), o_keys=('P', 'N', 'U', 'I'), o_tex=green(tmp_path / 'bark.png'),
              b_keys=('P', 'N', 'U', 'I'), b_tex=green(tmp_path / 'leaf.png'))])
    node.update(0.0, -DISTANCE)
    return node


KINDS = pytest.mark.parametrize('make', [billboards, clumps, trees],
                                ids=['billboards', 'clumps', 'trees'])


def drawn(node):
    """The shape the pass reaches ``node`` through."""
    return basenodes.Shape(geometry=node, appearance=basenodes.Appearance(
        material=basenodes.Material()), castShadow=False)


def rendered(render_scene, make, tmp_path, *extra):
    children = [basenodes.Viewpoint(position=(0, 0, 0)), drawn(make(tmp_path)), *extra]
    return middle(frames_of(render_scene, children)[-1])


@KINDS
def test_vegetation_in_a_scene_with_no_fog_is_drawn_at_its_own_colour(
        render_scene, tmp_path, make):
    seen = rendered(render_scene, make, tmp_path)
    assert seen[1] > seen[2] + 40


@KINDS
def test_a_bound_fog_tints_vegetation_toward_its_colour(render_scene, tmp_path, make):
    plain = rendered(render_scene, make, tmp_path)
    fogged = rendered(render_scene, make, tmp_path, Fog(color=(0, 0, 1),
                                                         visibilityRange=NEAR_RANGE))
    assert fogged[2] > plain[2] + 40
    assert fogged[1] < plain[1] - 40


@KINDS
def test_a_shorter_visible_range_fogs_vegetation_more(render_scene, tmp_path, make):
    close = rendered(render_scene, make, tmp_path,
                     Fog(color=(0, 0, 1), visibilityRange=NEAR_RANGE))
    distant = rendered(render_scene, make, tmp_path,
                       Fog(color=(0, 0, 1), visibilityRange=FAR_RANGE))
    assert close[2] > distant[2] + 20


@KINDS
def test_vegetation_beyond_the_visible_range_is_the_fog_colour(render_scene, tmp_path, make):
    image = rendered(render_scene, make, tmp_path,
                     Fog(color=(1, 0, 0), visibilityRange=DISTANCE * 0.5))
    assert image[0] > 200 and image[1] < 60 and image[2] < 60


# -- the splat terrain, which shares the fog -------------------------------------------

def ground(tmp_path):
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField
    from OpenGLContext.scenegraph.terrain.splat import SplatTerrain
    Image.new('RGBA', (8, 8), (150, 120, 70, 255)).save(tmp_path / 'layer.png')
    Image.new('RGBA', (8, 8), (255, 0, 0, 0)).save(tmp_path / 'control.png')
    field = HeightField(np.zeros((8, 8)), 400.0, 10.0)
    return SplatTerrain(field, ['floor'], str(tmp_path / 'control.png'),
                        material_fn=lambda _name, _res: {'color': str(tmp_path / 'layer.png')})


def seen_ground(render_scene, tmp_path, *extra):
    """The mean colour of the ground between 18 and 36 m ahead of a viewpoint 3 m up."""
    children = [basenodes.Viewpoint(position=(0, 3, 0)), drawn(ground(tmp_path)), *extra]
    image = frames_of(render_scene, children)[-1]
    rows = image[int(image.shape[0] * 0.6):int(image.shape[0] * 0.7)]
    return rows.reshape(-1, 3).mean(axis=0)


def test_terrain_in_a_scene_with_no_fog_is_drawn_at_its_own_colour(render_scene, tmp_path):
    seen = seen_ground(render_scene, tmp_path)
    assert seen[0] > seen[2] + 20


def test_a_bound_fog_tints_the_terrain_toward_its_colour(render_scene, tmp_path):
    plain = seen_ground(render_scene, tmp_path)
    fogged = seen_ground(render_scene, tmp_path,
                         Fog(color=(0, 0, 1), visibilityRange=NEAR_RANGE))
    assert fogged[2] > plain[2] + 40
    assert fogged[0] < plain[0] - 40


def test_a_shorter_visible_range_fogs_the_terrain_more(render_scene, tmp_path):
    close = seen_ground(render_scene, tmp_path,
                        Fog(color=(0, 0, 1), visibilityRange=NEAR_RANGE))
    distant = seen_ground(render_scene, tmp_path,
                          Fog(color=(0, 0, 1), visibilityRange=FAR_RANGE))
    assert close[2] > distant[2] + 20
