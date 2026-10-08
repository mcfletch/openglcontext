"""X3D's ClipPlane: which planes clip a draw, in its own coordinates (passes.clipscope)"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.passes import clipscope
from OpenGLContext.scenegraph.basenodes import Box, Group, Shape, Transform
from OpenGLContext.scenegraph.nodepath import NodePath


def path_to(*nodes):
    return NodePath(list(nodes))


def test_a_plane_in_world_coordinates_follows_its_transform():
    moved = np.identity(4)
    moved[3, :3] = (0, 2, 0)
    # y > 0 in the plane's frame is y > 2 in the world
    found = clipscope.world_plane((0, 1, 0, 0), moved)
    assert np.allclose(found, (0, 1, 0, -2))


def test_an_objects_plane_is_the_world_plane_in_its_frame():
    world = np.array([0.0, 1.0, 0.0, -2.0])
    placed = np.identity(4)
    placed[3, :3] = (0, 5, 0)
    # The object's y = -3 is the world's y = 2
    found = clipscope.object_plane(world, placed)
    assert np.allclose(found, (0, 1, 0, 3))


def test_a_scaled_plane_is_given_unit_length():
    found = clipscope.object_plane(np.array([0.0, 4.0, 0.0, -8.0]), np.identity(4))
    assert np.allclose(found, (0, 1, 0, -2))


def scene():
    plane = x3d.ClipPlane(plane=(0, 1, 0, 0))
    shape = Shape(geometry=Box())
    outside = Shape(geometry=Box())
    inner = Transform(translation=(0, 1, 0), children=[shape])
    group = Group(children=[plane, inner])
    root = Group(children=[group, outside])
    return root, group, plane, inner, shape, outside


def test_a_plane_clips_its_siblings_and_their_descendants_alone():
    root, group, plane, inner, shape, outside = scene()
    planes = clipscope.ClipPlanes().following([path_to(root, group, plane)])
    assert len(planes.reaching(path_to(root, group, inner, shape))) == 1
    assert planes.reaching(path_to(root, outside)) == ()
    assert planes.reaching(path_to(root, group)) == ()


def test_the_objects_planes_carry_its_placement():
    root, group, plane, inner, shape, outside = scene()
    planes = clipscope.ClipPlanes().following([path_to(root, group, plane)])
    placed = np.identity(4)
    placed[3, :3] = (0, 1, 0)
    found = planes.object_planes(path_to(root, group, inner, shape), placed)
    assert found.dtype == np.float32
    assert np.allclose(found, [(0, 1, 0, 1)])
    assert planes.object_planes(path_to(root, outside), np.identity(4)).shape == (0, 4)


def test_a_disabled_plane_clips_nothing():
    root, group, plane, inner, shape, outside = scene()
    plane.enabled = False
    planes = clipscope.ClipPlanes().following([path_to(root, group, plane)])
    assert not planes
    assert planes.reaching(path_to(root, group, inner, shape)) == ()


def test_nested_planes_all_clip_nearest_first():
    near, far = x3d.ClipPlane(plane=(1, 0, 0, 0)), x3d.ClipPlane(plane=(0, 0, 1, 0))
    shape = Shape(geometry=Box())
    inner = Group(children=[near, shape])
    outer = Group(children=[far, inner])
    planes = clipscope.ClipPlanes().following([path_to(outer, far), path_to(outer, inner, near)])
    found = planes.object_planes(path_to(outer, inner, shape), np.identity(4))
    assert np.allclose(found, [(1, 0, 0, 0), (0, 0, 1, 0)])


def test_no_more_than_eight_planes_clip_a_draw():
    shape = Shape(geometry=Box())
    nodes = [x3d.ClipPlane(plane=(1, 0, 0, -index)) for index in range(10)]
    group = Group(children=[*nodes, shape])
    planes = clipscope.ClipPlanes().following([path_to(group, node) for node in nodes])
    assert len(planes.reaching(path_to(group, shape))) == clipscope.MAX_PLANES == 8


def test_the_same_planes_keep_what_was_worked_out_and_follow_a_moved_plane():
    root, group, plane, inner, shape, outside = scene()
    first = clipscope.ClipPlanes().following([path_to(root, group, plane)])
    target = path_to(root, group, inner, shape)
    first.reaching(target)
    plane.plane = (0, -1, 0, 0)
    second = first.following([path_to(root, group, plane)])
    assert second is first
    assert np.allclose(second.object_planes(target, np.identity(4)), [(0, -1, 0, 0)])
    other = x3d.ClipPlane()
    group.children.append(other)
    third = second.following([path_to(root, group, plane), path_to(root, group, other)])
    assert third is not second
    assert len(third.reaching(target)) == 2


def test_records_under_planes_are_kept_apart_from_instancing():
    root, group, plane, inner, shape, outside = scene()
    planes = clipscope.ClipPlanes().following([path_to(root, group, plane)])
    clipped = path_to(root, group, inner, shape)
    assert planes.apart(clipped) is not None
    assert planes.apart(clipped) != planes.apart(clipped)
    assert planes.apart(path_to(root, outside)) is None


@pytest.mark.parametrize('node, drawn', [
    (Shape(geometry=Box()), True),
    (Group(), False),
])
def test_what_the_pass_clips(node, drawn):
    assert clipscope.clipped_by_pass(node) is drawn


def test_a_shape_with_its_own_program_is_not_clipped():
    class Brings:
        bringsProgram = True
    shape = Shape(geometry=Box())
    shape.__dict__['appearance'] = Brings()
    assert not clipscope.clipped_by_pass(shape)


def red():
    from OpenGLContext.scenegraph.basenodes import Appearance, Material  # noqa: PLC0415 kept with its use
    return Appearance(material=Material(diffuseColor=(0, 0, 0), emissiveColor=(1, 0, 0)))


def clipped_scene(enabled=True, geometry=None):
    """A red box of size 2 about the origin, clipped to y above zero, seen from +z"""
    from OpenGLContext.scenegraph.basenodes import Viewpoint  # noqa: PLC0415 kept with its use
    plane = x3d.ClipPlane(plane=(0, 1, 0, 0), enabled=enabled)
    shape = Shape(geometry=geometry if geometry is not None else Box(), appearance=red())
    return [Viewpoint(position=(0, 0, 6)), Group(children=[plane, shape])], plane


def halves(image):
    """How red the frame's upper and lower thirds are, over its middle columns"""
    height, width = image.shape[:2]
    middle = image[:, width // 3: 2 * width // 3, 0].astype(int)
    return middle[: height // 3].max(), middle[2 * height // 3:].max()


RENDERS = [
    pytest.param({'renderer': 'pbr'}, {}, id='pbr'),
    pytest.param({'renderer': 'vrml97'}, {}, id='vrml97'),
    pytest.param({'renderer': 'vrml97'}, {'OPENGLCONTEXT_PROFILE': 'compatibility'},
                 id='compatibility'),
]


@pytest.mark.parametrize('definition, environment', RENDERS)
def test_a_clip_plane_cuts_away_the_side_below_it(definition, environment):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    children, plane = clipped_scene()
    with scene_context(children, environment=environment, **definition) as context:
        drawn_image(context)
        upper, lower = halves(drawn_image(context))
        assert upper > 200 and lower < 40
        plane.enabled = False
        upper, lower = halves(drawn_image(context))
        assert upper > 200 and lower > 200


def test_a_plane_moves_with_its_transform():
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    children, plane = clipped_scene()
    plane.plane = (0, -1, 0, 0)
    with scene_context(children, renderer='pbr') as context:
        drawn_image(context)
        upper, lower = halves(drawn_image(context))
    assert upper < 40 and lower > 200


def test_lines_drawn_wide_are_clipped():
    from vrml.x3d import nodes as x3dnodes  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.basenodes import Coordinate, IndexedLineSet  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    line = IndexedLineSet(coord=Coordinate(point=[(0, -2, 0), (0, 2, 0)]), coordIndex=[0, 1])
    children, _plane = clipped_scene(geometry=line)
    children[1].children[1].appearance.lineProperties = x3dnodes.LineProperties(
        linewidthScaleFactor=6)
    with scene_context(children, renderer='pbr') as context:
        drawn_image(context)
        upper, lower = halves(drawn_image(context))
    assert upper > 200 and lower < 40


def shadowed_floor(clipped):
    """From above: a floor lit from up and to the right, and a box over it of
    which the ClipPlane keeps the half at x above zero"""
    import math  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.basenodes import (  # noqa: PLC0415 kept with its use
        Appearance, DirectionalLight, Material, NavigationInfo, Transform, Viewpoint,
    )
    floor = Shape(geometry=Box(size=(20, 0.1, 20)),
                  appearance=Appearance(material=Material(diffuseColor=(1, 1, 1))))
    plane = x3d.ClipPlane(plane=(1, 0, 0, 0), enabled=clipped)
    box = Transform(translation=(0, 2, 0), children=[Shape(geometry=Box(), appearance=red())])
    return [NavigationInfo(headlight=False),
            Viewpoint(position=(0, 10, 0), orientation=(1, 0, 0, -math.pi / 2)),
            DirectionalLight(direction=(-1, -1, 0), intensity=1.0),
            floor, Group(children=[plane, box])]


@pytest.mark.parametrize('clipped', [True, False])
def test_the_part_clipped_away_casts_no_shadow(clipped):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(shadowed_floor(clipped), renderer='pbr',
                       environment={'OPENGLCONTEXT_SHADOWS': '1',
                                    'OPENGLCONTEXT_SHADOW_CASCADES': '1'}) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
    # The floor at x = -3 is in the shadow of the box's x < 0 half alone
    under = image[48, 13].sum()
    open_floor = image[48, 83].sum()
    if clipped:
        assert abs(under - open_floor) < 30
    else:
        assert under < open_floor - 60


def test_shapes_that_would_be_instanced_are_each_clipped():
    from OpenGLContext.scenegraph.basenodes import Sphere, Transform, Viewpoint  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    ball = Shape(geometry=Sphere(radius=0.45), appearance=red())
    row = [Transform(translation=(x - 2.0, 0, 0), children=[ball]) for x in range(5)]
    plane = x3d.ClipPlane(plane=(0, 1, 0, 0))
    children = [Viewpoint(position=(0, 0, 6)), Group(children=[plane, *row])]
    with scene_context(children, renderer='pbr',
                       environment={'OPENGLCONTEXT_INSTANCING': '1'}) as context:
        drawn_image(context)
        image = drawn_image(context)
    middle = image[:, :, 0].astype(int)
    assert middle[38:47].max() > 200      # the balls' upper halves
    assert middle[50:60].max() < 40       # and nothing below the plane
