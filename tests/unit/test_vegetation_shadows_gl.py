"""Near trees cast shadows, and are bounded by the trees that are drawn.

An instanced node is drawn through its own program, so the shadow pass has to be
handed its trees to write into the depth maps; and a node bounded by the whole
forest would stretch every cascade of the sun's shadows over all of it.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from PIL import Image

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD
from tests.unit.glrender import base_env, frames_of

HEIGHT = 12.0


@pytest.fixture(autouse=True)
def shadows_on(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS=1, OPENGLCONTEXT_SHADOW_CASCADES=3)


def tree_files(tmp_path):
    """A tree that is one tall upright card: a wide shadow on level ground."""
    positions = np.array([[-3, 0, 0], [3, 0, 0], [3, 1, 0], [-3, 1, 0]], 'f4')
    normals = np.tile(np.array([0, 0, 1], 'f4'), (4, 1))
    uvs = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], 'f4')
    indices = np.array([0, 1, 2, 0, 2, 3], np.uint32)
    npz = tmp_path / 'tree.npz'
    np.savez(str(npz), P=positions, N=normals, U=uvs, I=indices)
    Image.new('RGBA', (4, 4), (40, 120, 40, 255)).save(tmp_path / 'leaf.png')
    return dict(npz=str(npz), o_keys=('P', 'N', 'U', 'I'), o_tex=str(tmp_path / 'leaf.png'),
                b_keys=('P', 'N', 'U', 'I'), b_tex=str(tmp_path / 'leaf.png'))


def trees(tmp_path, at=((0.0, 0.0, 0.0),)):
    node = InstancedMeshLOD(np.array(at, 'f4'), np.zeros(len(at), 'f4'),
                            np.full(len(at), HEIGHT, 'f4'), [tree_files(tmp_path)])
    node.update(float(at[0][0]), float(at[0][2]))
    return node


def scene(node, casts):
    ground = basenodes.Shape(
        geometry=basenodes.Box(size=(60, 0.2, 60)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.8, 0.8, 0.8))))
    shape = basenodes.Shape(geometry=node, appearance=basenodes.Appearance(
        material=basenodes.Material()), castShadow=casts)
    return [basenodes.Viewpoint(position=(0, 40, 25), orientation=(1, 0, 0, -1.0)),
            basenodes.Transform(translation=(0, -0.1, 0), children=[ground]),
            basenodes.DirectionalLight(direction=(-0.6, -1.0, -0.2), intensity=1.0, shadows=True),
            shape]


def test_trees_that_cast_darken_the_ground_the_sun_cannot_reach(render_scene, tmp_path):
    lit = frames_of(render_scene, scene(trees(tmp_path), casts=False))[-1].astype(int)
    shaded = frames_of(render_scene, scene(trees(tmp_path), casts=True))[-1].astype(int)
    darker = (lit.sum(axis=2) - shaded.sum(axis=2)) > 60
    assert int(darker.sum()) > 300


def test_trees_that_do_not_cast_leave_the_ground_as_it_was(render_scene, tmp_path):
    first = frames_of(render_scene, scene(trees(tmp_path), casts=False))[-1].astype(int)
    again = frames_of(render_scene, scene(trees(tmp_path), casts=False))[-1].astype(int)
    assert int((abs(first - again).sum(axis=2) > 60).sum()) == 0


def test_the_trees_are_bounded_by_the_set_that_is_drawn(tmp_path):
    node = InstancedMeshLOD(np.array([[500.0, 0, 500.0], [9000.0, 0, 9000.0]], 'f4'),
                            np.zeros(2, 'f4'), np.full(2, HEIGHT, 'f4'), [tree_files(tmp_path)])
    assert max(node.boundingVolume(None).size) > 1000.0
    node.update(500.0, 500.0)
    volume = node.boundingVolume(None)
    assert max(volume.size) < 80.0
    centre = np.asarray(volume.center, float)
    assert abs(centre[0] - 500.0) < 5.0 and abs(centre[2] - 500.0) < 5.0
    assert centre[1] + volume.size[1] / 2 >= HEIGHT


def test_no_trees_staged_is_nothing_to_bound(tmp_path):
    node = InstancedMeshLOD(np.array([[500.0, 0, 500.0]], 'f4'), np.zeros(1, 'f4'),
                            np.full(1, HEIGHT, 'f4'), [tree_files(tmp_path)])
    node.update(0.0, 0.0)
    assert max(node.boundingVolume(None).size) < 1.0
