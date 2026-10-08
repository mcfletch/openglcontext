"""A Billboard turns its children toward the viewer.

X3D (19775-1, Navigation, Billboard): about a non-zero ``axisOfRotation``, the
children turn until their local +Z points at the viewer's projection onto the
plane perpendicular to the axis. With ``0 0 0``, local +Z points at the viewer
and local +Y lines up with the viewer's up.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import nodepath
from OpenGLContext.scenegraph.basenodes import Billboard, Shape, Sphere, Transform, sceneGraph
from OpenGLContext.scenegraph.billboard import billboard_rotation


def rotate(rotation, vector):
    """`vector` turned by an X3D rotation (axis, angle), right-handed"""
    axis, angle = np.asarray(rotation[:3], float), float(rotation[3])
    vector = np.asarray(vector, float)
    if not np.linalg.norm(axis):
        return vector
    axis = axis / np.linalg.norm(axis)
    return (vector * math.cos(angle) + np.cross(axis, vector) * math.sin(angle)
            + axis * (axis @ vector) * (1 - math.cos(angle)))


def unit(vector):
    vector = np.asarray(vector, float)
    return vector / np.linalg.norm(vector)


@pytest.mark.parametrize('eye', [(3, 1, 0), (-2, 5, -2), (0, -1, -4), (0.5, 0, 0.5)])
def test_about_the_y_axis_z_faces_the_viewer(eye):
    rotation = billboard_rotation((0, 1, 0), eye)
    assert rotate(rotation, (0, 0, 1)) == pytest.approx(unit((eye[0], 0, eye[2])))
    assert rotate(rotation, (0, 1, 0)) == pytest.approx((0, 1, 0))


def test_about_another_axis():
    axis = unit((1, 1, 0))
    eye = np.array((0.0, 0.0, -5.0)) + 2 * axis
    rotation = billboard_rotation(axis, eye)
    assert rotate(rotation, axis) == pytest.approx(axis)
    assert rotate(rotation, (0, 0, 1)) == pytest.approx((0, 0, -1), abs=1e-6)


def test_a_viewer_on_the_axis_leaves_it_unturned():
    assert rotate(billboard_rotation((0, 1, 0), (0, 4, 0)), (0, 0, 1)) == pytest.approx((0, 0, 1))


def test_an_axis_along_z_leaves_it_unturned():
    assert rotate(billboard_rotation((0, 0, 1), (3, 0, 1)), (1, 0, 0)) == pytest.approx((1, 0, 0))


@pytest.mark.parametrize('eye, up', [((2, 3, 4), (0, 1, 0)), ((0, 0, 5), (1, 1, 0)),
                                     ((-3, 0, -1), (0, 0, 1))])
def test_viewer_alignment(eye, up):
    rotation = billboard_rotation((0, 0, 0), eye, up)
    z = rotate(rotation, (0, 0, 1))
    y = rotate(rotation, (0, 1, 0))
    assert z == pytest.approx(unit(eye))
    up = np.asarray(up, float)
    assert y == pytest.approx(unit(up - (up @ unit(eye)) * unit(eye)))


def test_a_viewer_at_the_centre_leaves_it_unturned():
    assert billboard_rotation((0, 1, 0), (0, 0, 0))[3] == 0.0
    assert billboard_rotation((0, 0, 0), (0, 0, 0), (0, 1, 0))[3] == 0.0


def test_unturned_a_path_through_one_has_its_parents_transform():
    shape = Shape(geometry=Sphere())
    billboard = Billboard(children=[shape])
    moved = Transform(translation=(1, 2, 3), children=[billboard])
    graph = sceneGraph(children=[moved])
    through = nodepath.NodePath([]) + graph + moved + billboard + shape
    beside = nodepath.NodePath([]) + graph + moved
    assert np.allclose(through.transformMatrix(), beside.transformMatrix())


def test_turned_a_path_through_it_carries_the_turn():
    shape = Shape(geometry=Sphere())
    billboard = Billboard(children=[shape])
    moved = Transform(translation=(1, 2, 3), children=[billboard])
    graph = sceneGraph(children=[moved])
    through = nodepath.NodePath([]) + graph + moved + billboard + shape
    before = through.transformMatrix()
    assert billboard.face((5, 0, 0))
    after = np.array((0, 0, 1, 1), 'd') @ through.transformMatrix()
    assert after[:3] == pytest.approx((2, 2, 3))
    assert not np.allclose(before, through.transformMatrix())
    assert not billboard.face((5, 0, 0)), 'unchanged: nothing to work out again'


def test_the_viewer_in_the_parents_coordinates():
    """Row vectors, as the engine's matrices are: a point times the parent's
    world matrix times the modelview is in eye coordinates"""
    from OpenGLContext.scenegraph.billboard import viewer_in  # noqa: PLC0415 kept with its use
    from vrml.vrml97 import transformmatrix  # noqa: PLC0415 kept with its use
    parent, _ = transformmatrix.localMatrices(translation=(1, 2, 3))
    # A camera at (0, 2, 10) in the world, turned a quarter about Y, so its up is +Y
    camera, view = transformmatrix.localMatrices(translation=(0, 2, 10),
                                                 rotation=(0, 1, 0, math.pi / 2))
    eye, up = viewer_in(parent, view)
    assert eye == pytest.approx((-1, 0, 7))
    assert up == pytest.approx((0, 1, 0))


def test_drawn_facing_the_viewer(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(
        b"<X3D version='3.3'><Scene><Viewpoint position='6 0 0' orientation='0 1 0 1.5708'/>"
        b"<Billboard axisOfRotation='0 1 0'><Shape><Appearance>"
        b"<Material diffuseColor='0 0 0' emissiveColor='1 0 0'/></Appearance>"
        b"<IndexedFaceSet coordIndex='0 1 2 3'>"
        b"<Coordinate point='-1 -1 0 1 -1 0 1 1 0 -1 1 0'/></IndexedFaceSet>"
        b"</Shape></Billboard></Scene></X3D>", 'scene.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        drawn_image(context)
        centre = drawn_image(context)[16, 16].astype(int)
    assert centre[0] > 150 and centre[1] < 80, centre


def test_a_billboard_scaled_to_nothing_is_left_unturned():
    from OpenGLContext.scenegraph.billboard import viewer_in  # noqa: PLC0415 kept with its use
    assert viewer_in(np.diag((0.0, 0.0, 0.0, 1.0)), np.identity(4)) is None


def billboards(count, spacing=3.0):
    """`count` Billboards each under a Transform of its own, as their paths"""
    graph = sceneGraph()
    paths = []
    for index in range(count):
        billboard = Billboard(children=[Shape(geometry=Sphere())])
        moved = Transform(translation=(spacing * index, 0, 0), children=[billboard])
        graph.children = list(graph.children) + [moved]
        paths.append(nodepath.NodePath([]) + graph + moved + billboard)
    return paths


def camera_at(x):
    from vrml.vrml97 import transformmatrix  # noqa: PLC0415 kept with its use
    return transformmatrix.localMatrices(translation=(x, 0, 10))[1]


class TestFacing:
    """A frame's Billboards turned toward its camera: those whose camera,
    parent or axis moved since the last frame are worked out"""

    def test_each_faces_the_camera_in_its_parents_coordinates(self):
        from OpenGLContext.scenegraph.billboard import Facing  # noqa: PLC0415 kept with its use
        paths = billboards(3)
        assert Facing().face(paths, camera_at(3.0)) == 3
        for index, path in enumerate(paths):
            expected = billboard_rotation((0, 1, 0), (3.0 - 3.0 * index, 0, 10))
            assert path[-1].facing == pytest.approx(expected)

    def test_a_still_frame_works_out_none(self):
        from OpenGLContext.scenegraph.billboard import Facing  # noqa: PLC0415 kept with its use
        paths, facing = billboards(4), Facing()
        facing.face(paths, camera_at(1.0))
        assert facing.face(paths, camera_at(1.0)) == 0

    def test_a_parent_or_an_axis_that_moved_is_worked_out_again(self):
        from OpenGLContext.scenegraph.billboard import Facing  # noqa: PLC0415 kept with its use
        paths, facing = billboards(4), Facing()
        facing.face(paths, camera_at(1.0))
        paths[1][1].translation = (50, 0, 0)
        paths[2][-1].axisOfRotation = (1, 0, 0)
        assert facing.face(paths, camera_at(1.0)) == 2
        assert paths[1][-1].facing == pytest.approx(
            billboard_rotation((0, 1, 0), (-49.0, 0, 10)))

    def test_a_billboard_inside_another_follows_its_turn(self):
        from OpenGLContext.scenegraph.billboard import Facing  # noqa: PLC0415 kept with its use
        inner = Billboard(axisOfRotation=(0, 0, 0), children=[Shape(geometry=Sphere())])
        outer = Billboard(children=[inner])
        graph = sceneGraph(children=[outer])
        outer_path = nodepath.NodePath([]) + graph + outer
        paths = [outer_path, outer_path + inner]
        facing = Facing()
        facing.face(paths, camera_at(4.0))
        assert facing.face(paths, camera_at(-4.0)) == 2

    def test_the_work_grows_with_the_billboards(self, check_scaling):
        from OpenGLContext.scenegraph.billboard import Facing  # noqa: PLC0415 kept with its use

        def prepare(n):
            paths, facing = billboards(n), Facing()
            cameras = iter(range(1000000))
            return lambda: facing.face(paths, camera_at(float(next(cameras))))
        check_scaling(prepare, n=50, most=5.0, measure='count')
