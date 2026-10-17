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


def shaped(node):
    return basenodes.Shape(geometry=node, appearance=basenodes.Appearance(
        material=basenodes.Material()))


def test_a_shape_follows_the_trees_as_they_are_staged_somewhere_else(tmp_path):
    """The shape caches its geometry's bound: a trees node that handed out a new bound each time
    would be culled for good once the camera had left the first one, and every tree with it."""
    node = InstancedMeshLOD(np.array([[500.0, 0, 500.0], [9000.0, 0, 9000.0]], 'f4'),
                            np.zeros(2, 'f4'), np.full(2, HEIGHT, 'f4'), [tree_files(tmp_path)])
    shape = shaped(node)
    assert max(shape.boundingVolume(None).size) > 1000.0
    node.update(500.0, 500.0)
    here = shape.boundingVolume(None)
    assert max(here.size) < 80.0 and abs(here.center[0] - 500.0) < 5.0
    node.update(9000.0, 9000.0)
    there = shape.boundingVolume(None)
    assert max(there.size) < 80.0 and abs(there.center[0] - 9000.0) < 5.0
    node.update(500.0, 500.0)
    assert abs(shape.boundingVolume(None).center[0] - 500.0) < 5.0


def test_trees_staged_where_the_camera_has_gone_are_in_view_of_it(tmp_path):
    node = InstancedMeshLOD(np.array([[0.0, 0, -300.0]], 'f4'), np.zeros(1, 'f4'),
                            np.full(1, HEIGHT, 'f4'), [tree_files(tmp_path)])
    shape = shaped(node)
    node.update(0.0, 0.0)                       # nothing near the first place
    shape.boundingVolume(None)
    node.update(0.0, -290.0)                    # and then the camera is where the tree is
    volume = shape.boundingVolume(None)
    low = np.asarray(volume.center) - np.asarray(volume.size) / 2.0
    high = np.asarray(volume.center) + np.asarray(volume.size) / 2.0
    assert (low <= [0.0, 0.0, -300.0]).all() and (high >= [0.0, HEIGHT, -300.0]).all()


def test_the_corners_the_pass_culls_by_follow_the_trees_too(tmp_path):
    node = InstancedMeshLOD(np.array([[500.0, 0, 500.0], [9000.0, 0, 9000.0]], 'f4'),
                            np.zeros(2, 'f4'), np.full(2, HEIGHT, 'f4'), [tree_files(tmp_path)])
    shape = shaped(node)
    shape.boundingVolume(None).getPoints()          # as the first frame's cull does
    node.update(9000.0, 9000.0)
    corners = np.asarray(shape.boundingVolume(None).getPoints())[:, :3]
    assert abs(float(corners[:, 0].mean()) - 9000.0) < 10.0
    assert corners[:, 0].max() - corners[:, 0].min() < 80.0


def test_the_shadow_pass_is_told_the_trees_moved_by_a_bound_that_is_a_new_object(tmp_path):
    """The caster pool and the depth maps are reused while a caster's bound is the same object, so
    a node whose trees change hands the shape a new bound for them and the same one when they do
    not."""
    node = InstancedMeshLOD(np.array([[500.0, 0, 500.0], [9000.0, 0, 9000.0]], 'f4'),
                            np.zeros(2, 'f4'), np.full(2, HEIGHT, 'f4'), [tree_files(tmp_path)])
    shape = shaped(node)
    node.update(500.0, 500.0)
    first = shape.boundingVolume(None)
    assert shape.boundingVolume(None) is first                       # unmoved: the same one
    node.update(9000.0, 9000.0)
    second = shape.boundingVolume(None)
    assert second is not first                                       # moved: a new one
    assert shape.boundingVolume(None) is second


def test_trees_throw_shadows_after_the_camera_has_moved_on(render_scene, tmp_path):
    """The depth maps are made again for trees staged somewhere else: a forest the camera
    runs through casts its shadows wherever it runs."""
    far = ((0.0, 0.0, 0.0), (0.0, 0.0, -400.0))
    node = InstancedMeshLOD(np.array(far, 'f4'), np.zeros(2, 'f4'), np.full(2, HEIGHT, 'f4'),
                            [tree_files(tmp_path)])
    node.update(0.0, 0.0)
    shape = shaped(node)
    shape.castShadow = True
    frames_of(render_scene, scene_with(shape))              # the first place, drawn and shadowed
    node.update(0.0, -400.0)                                # the camera has run on
    ground = basenodes.Shape(
        geometry=basenodes.Box(size=(60, 0.2, 60)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.8, 0.8, 0.8))))
    moved = [basenodes.Viewpoint(position=(0, 40, -375), orientation=(1, 0, 0, -1.0)),
             basenodes.Transform(translation=(0, -0.1, -400), children=[ground]),
             basenodes.DirectionalLight(direction=(-0.6, -1.0, -0.2), intensity=1.0, shadows=True),
             shape]
    shaded = frames_of(render_scene, moved)[-1].astype(int)
    shape.castShadow = False
    lit = frames_of(render_scene, moved)[-1].astype(int)
    assert int(((lit.sum(axis=2) - shaded.sum(axis=2)) > 60).sum()) > 300


def scene_with(shape):
    ground = basenodes.Shape(
        geometry=basenodes.Box(size=(60, 0.2, 60)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(0.8, 0.8, 0.8))))
    return [basenodes.Viewpoint(position=(0, 40, 25), orientation=(1, 0, 0, -1.0)),
            basenodes.Transform(translation=(0, -0.1, 0), children=[ground]),
            basenodes.DirectionalLight(direction=(-0.6, -1.0, -0.2), intensity=1.0, shadows=True),
            shape]
