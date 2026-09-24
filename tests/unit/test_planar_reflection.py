"""The arithmetic of a planar mirror, with no GL.

Which surfaces are mirrors and in which plane, the camera a mirror is seen
through, the part of the screen it covers, and where a fragment of the mirror
reads its reflection. Drawing one is ``test_planar_mirror_gl.py``.
"""
import logging

import numpy as np
import pytest

from OpenGLContext.multiview.strategy import ViewFrame, view_records
from OpenGLContext.passes import reflection
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.water import STILL

#: A unit quad in its own xy plane, facing +z by its winding.
QUAD = np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], 'f')
QUAD_INDICES = np.array([0, 1, 2, 0, 2, 3], np.uint32)


def _rotation(axis, angle):
    axis = np.asarray(axis, 'd') / np.linalg.norm(axis)
    x, y, z = axis
    c, s, t = np.cos(angle), np.sin(angle), 1 - np.cos(angle)
    # Row-vector: point @ matrix.
    return np.array([
        [t * x * x + c, t * x * y + s * z, t * x * z - s * y],
        [t * x * y - s * z, t * y * y + c, t * y * z + s * x],
        [t * x * z + s * y, t * y * z - s * x, t * z * z + c],
    ])


def _placement(rotation=None, translate=(0.0, 0.0, 0.0), scale=1.0):
    matrix = np.identity(4)
    matrix[:3, :3] = (np.identity(3) if rotation is None else rotation) * scale
    matrix[3, :3] = translate
    return matrix


def _mirror_record(placement=None, reflector=None, positions=QUAD,
                   indices=QUAD_INDICES, roughness=0.0):
    mesh = PBRMesh(positions=np.asarray(positions, 'f'), indices=indices)
    material = PBRMaterial(metallic=1.0, roughness=roughness,
                           reflector=reflector or PlanarReflector())
    shape = Shape(geometry=mesh, appearance=Appearance(material=material))
    tmatrix = _placement() if placement is None else placement
    return ((False,), None, np.asarray(tmatrix, 'f'), None, (), shape)


def _water_record(level=0.0, translate=(0.0, 0.0, 0.0)):
    positions = np.array([(-5, level, -5), (5, level, -5), (5, level, 5)], 'f')
    mesh = PBRMesh(positions=positions, indices=np.array([0, 1, 2], np.uint32))
    mesh.waveStyle = STILL
    return ((False,), None, np.asarray(_placement(translate=translate), 'f'),
            None, (), Shape(geometry=mesh))


def _plain_record():
    mesh = PBRMesh(positions=QUAD, indices=QUAD_INDICES)
    shape = Shape(geometry=mesh, appearance=Appearance(
        material=PBRMaterial(metallic=1.0, roughness=0.0)))
    return ((False,), None, np.identity(4, 'f'), None, (), shape)


def _perspective(near=0.1, far=100.0, fov=1.0, aspect=1.0):
    """A row-vector perspective projection, as the engine's matrices are."""
    f = 1.0 / np.tan(fov / 2.0)
    column = np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
        [0, 0, -1, 0],
    ], 'd')
    return column.T


def _look_at(eye, target, up=(0.0, 1.0, 0.0)):
    """A row-vector view matrix for a camera at ``eye`` looking at ``target``."""
    eye = np.asarray(eye, 'd')
    forward = np.asarray(target, 'd') - eye
    forward /= np.linalg.norm(forward)
    side = np.cross(forward, up)
    side /= np.linalg.norm(side)
    upward = np.cross(side, forward)
    rotation = np.identity(4)
    rotation[:3, 0] = side
    rotation[:3, 1] = upward
    rotation[:3, 2] = -forward
    translation = np.identity(4)
    translation[3, :3] = -eye
    return translation @ rotation


# --- which surfaces are mirrors ------------------------------------------------

def test_a_material_with_a_reflector_is_a_mirror():
    reflector = PlanarReflector()
    assert reflection.reflector_for(_mirror_record(reflector=reflector)) is reflector


def test_a_smooth_material_without_one_reflects_the_probe():
    assert reflection.reflector_for(_plain_record()) is None


def test_a_disabled_reflector_reflects_the_probe():
    record = _mirror_record(reflector=PlanarReflector(enabled=False))
    assert reflection.reflector_for(record) is None


def test_water_is_a_mirror_whatever_its_material():
    reflector = reflection.reflector_for(_water_record())
    assert reflector is reflection.WATER_REFLECTOR
    assert reflector.interval == 1
    assert reflector.distortion == pytest.approx(reflection.WATER_DISTORTION)


# --- the plane of a mesh -------------------------------------------------------

@pytest.mark.parametrize('axis,angle', [
    ((1, 0, 0), 0.0), ((1, 0, 0), np.pi / 2), ((1, 0, 0), -np.pi / 2),
    ((0, 1, 0), np.pi / 2), ((0, 1, 0), np.pi), ((1, 1, 0), 0.7),
    ((0.3, -1, 0.5), 2.1), ((1, 0, 0), np.pi),
])
def test_the_plane_follows_the_mesh_at_every_orientation(axis, angle):
    rotation = _rotation(axis, angle)
    positions = QUAD @ rotation + (3.0, -2.0, 1.0)
    fitted = reflection.fit_plane(positions, QUAD_INDICES)
    assert fitted.flat
    expected = np.array([0.0, 0.0, 1.0]) @ rotation
    assert tuple(fitted.normal) == pytest.approx(tuple(expected), abs=1e-6)
    assert tuple(fitted.point) == pytest.approx((3.0, -2.0, 1.0), abs=1e-6)


def test_the_normal_faces_the_side_the_triangles_face():
    fitted = reflection.fit_plane(QUAD, QUAD_INDICES[::-1].copy())
    assert tuple(fitted.normal) == pytest.approx((0.0, 0.0, -1.0))


def test_a_mesh_that_is_not_flat_is_not_a_plane():
    bent = np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0.2), (-1, 1, 0)], 'f')
    assert not reflection.fit_plane(bent, QUAD_INDICES).flat


def test_a_bent_mirror_says_so_once_and_reflects_the_probe(caplog):
    bent = np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0.2), (-1, 1, 0)], 'f')
    record = _mirror_record(positions=bent)
    with caplog.at_level(logging.WARNING, logger=reflection.__name__):
        assert reflection.surface_plane(record) is None
        assert reflection.surface_plane(record) is None
    assert len([r for r in caplog.records if 'flat' in r.getMessage()]) == 1


def test_a_sheared_placement_keeps_the_normal_perpendicular():
    shear = np.identity(4)
    shear[1, 0] = 0.8      # y leans into x
    shear[2, 1] = 0.3
    record = _mirror_record(placement=shear)
    point, normal = reflection.surface_plane(record)
    placed = np.c_[QUAD, np.ones(4)] @ shear
    for corner in placed[:, :3]:
        assert float(np.dot(corner - point, normal)) == pytest.approx(0.0, abs=1e-6)
    assert np.linalg.norm(normal) == pytest.approx(1.0)


def test_a_scaled_and_moved_mirror_stands_where_it_was_put():
    record = _mirror_record(placement=_placement(
        _rotation((0, 1, 0), np.pi / 2), translate=(4.0, 1.0, -2.0), scale=3.0))
    point, normal = reflection.surface_plane(record)
    assert tuple(point) == pytest.approx((4.0, 1.0, -2.0), abs=1e-6)
    assert tuple(normal) == pytest.approx((1.0, 0.0, 0.0), abs=1e-6)


def test_water_reflects_in_its_sheet_at_its_level():
    point, normal = reflection.surface_plane(_water_record(0.5, (0.0, 2.0, 0.0)))
    assert point[1] == pytest.approx(2.5)
    assert tuple(normal) == pytest.approx((0.0, 1.0, 0.0))


# --- the part of the screen a mirror covers -----------------------------------

VIEW_RECT = (0, 0, 400, 200)


def test_a_mirror_in_the_middle_of_the_view_covers_the_middle():
    view = _look_at((0.0, 0.0, 10.0), (0.0, 0.0, 0.0))
    projection = _perspective(aspect=2.0)
    rect = reflection.screen_rect(reflection.box_corners(QUAD), view @ projection)
    x0, y0, x1, y1 = rect
    assert x0 == pytest.approx(-x1) and y0 == pytest.approx(-y1)
    assert 0.0 < x1 < 1.0 and 0.0 < y1 < 1.0


def test_a_mirror_behind_the_camera_covers_nothing():
    view = _look_at((0.0, 0.0, -10.0), (0.0, 0.0, -20.0))
    assert reflection.screen_rect(reflection.box_corners(QUAD),
                                  view @ _perspective()) is None


def test_a_mirror_the_camera_stands_beside_covers_the_whole_view():
    """Part of it is behind the eye, so its projection is unbounded."""
    view = _look_at((0.0, 0.0, 0.5), (0.0, 0.0, -1.0))
    big = QUAD * 5.0
    assert reflection.screen_rect(reflection.box_corners(big),
                                  view @ _perspective()) == (-1.0, -1.0, 1.0, 1.0)


def test_the_crop_takes_a_rectangle_of_the_screen_to_the_whole_of_a_tile():
    rect = (-0.5, -0.2, 0.1, 0.6)
    crop = reflection.crop_matrix(rect)
    for x, y, expected in ((-0.5, -0.2, (-1, -1)), (0.1, 0.6, (1, 1))):
        clip = np.array([x * 3.0, y * 3.0, 0.2, 3.0]) @ crop
        assert tuple(clip[:2] / clip[3]) == pytest.approx(expected)


# --- the mirror's view --------------------------------------------------------

def _wall_mirror():
    """A 2 x 2 mirror on the wall z = -5, facing the room."""
    return _mirror_record(placement=_placement(translate=(0.0, 1.5, -5.0)))


def _plan(record, eye=(1.0, 1.6, 3.0), target=(0.0, 1.5, -5.0), scale=0.5,
          view_rect=VIEW_RECT):
    view = _look_at(eye, target)
    projection = _perspective(aspect=view_rect[2] / view_rect[3])
    plane = reflection.surface_plane(record)
    corners = reflection.world_corners(reflection.local_plane(record), record[2])
    return view, projection, reflection.plan_mirror(
        plane, corners, view, projection, view_rect, scale)


def test_a_mirror_seen_from_behind_plans_nothing():
    _view, _projection, planned = _plan(_wall_mirror(), eye=(0.0, 1.5, -9.0))
    assert planned is None


def test_the_mirror_camera_sees_the_room_reflected():
    view, _projection, planned = _plan(_wall_mirror())
    point = np.array([0.3, 1.0, 2.0, 1.0])
    reflected = np.array([0.3, 1.0, -12.0, 1.0])
    assert np.allclose(point @ planned.modelView, reflected @ view)


def test_what_stands_behind_the_mirror_is_clipped():
    _view, _projection, planned = _plan(_wall_mirror())
    in_front = np.array([0.0, 1.5, 0.0, 1.0]) @ planned.modelproj
    behind = np.array([0.0, 1.5, -7.0, 1.0]) @ planned.modelproj
    assert -1.0 < in_front[2] / in_front[3] < 1.0
    assert behind[2] / behind[3] < -1.0


def test_the_tile_is_the_mirrors_rectangle_and_its_guard_band_at_scale():
    view, projection, planned = _plan(_wall_mirror(), scale=0.5)
    corners = reflection.box_corners(QUAD) + (0.0, 1.5, -5.0)
    x0, y0, x1, y1 = reflection.screen_rect(corners, view @ projection)
    width, height = (x1 - x0) / 2 * 400, (y1 - y0) / 2 * 200
    guard = 1.0 + 2 * reflection.GUARD
    assert planned.size[0] == pytest.approx(width * guard * 0.5, abs=8)
    assert planned.size[1] == pytest.approx(height * guard * 0.5, abs=8)


@pytest.mark.parametrize('eye,target,placement', [
    ((1.0, 1.6, 3.0), (0.0, 1.5, -5.0), _placement(translate=(0.0, 1.5, -5.0))),
    ((-3.0, 2.0, 1.0), (0.5, 1.0, -4.0), _placement(translate=(0.0, 1.5, -5.0))),
    ((0.0, 4.0, 4.0), (0.0, 0.0, 0.0),
     _placement(_rotation((1, 0, 0), -np.pi / 2), scale=3.0)),
    ((2.0, 1.0, 2.0), (-4.0, 1.0, 0.0),
     _placement(_rotation((0, 1, 0), np.pi / 2), translate=(-4.0, 1.0, 0.0))),
    ((5.0, 3.0, -1.0), (0.0, 1.0, 0.0),
     _placement(_rotation((0.2, 1, 0.1), 1.1), translate=(0.0, 1.0, 0.0), scale=2.0)),
])
def test_a_fresh_tile_is_read_where_the_mirror_is_on_screen(eye, target, placement):
    """The projective lookup lands on the texel the screen position would.

    Each point on the mirror, pushed through the tile's own matrix into the
    atlas, reads the same place a lookup by its screen position reads,
    because the tile was drawn through this frame's camera.
    """
    record = _mirror_record(placement=placement)
    view, projection, planned = _plan(record, eye=eye, target=target)
    assert planned is not None
    atlas = (1024, 512)
    tile = (100, 60) + planned.size
    rng = np.random.default_rng(7)
    local = np.c_[rng.uniform(-0.9, 0.9, (20, 2)), np.zeros(20), np.ones(20)]
    for world in local @ np.asarray(placement, 'd'):
        u, v = reflection.atlas_lookup(world[:3], planned, tile, atlas)
        clip = world @ view @ projection
        screen = (clip[:2] / clip[3] * 0.5 + 0.5) * VIEW_RECT[2:]
        crop = planned.crop
        tx = (screen[0] / VIEW_RECT[2] * 2 - 1 - crop[0]) / (crop[2] - crop[0])
        ty = (screen[1] / VIEW_RECT[3] * 2 - 1 - crop[1]) / (crop[3] - crop[1])
        assert u == pytest.approx((tile[0] + tx * tile[2]) / atlas[0], abs=1e-6)
        assert v == pytest.approx((tile[1] + ty * tile[3]) / atlas[1], abs=1e-6)


def test_the_view_table_carries_a_mirror_view_exactly():
    view, projection, planned = _plan(_wall_mirror())
    reference = ViewFrame(None, None, VIEW_RECT, view, projection,
                          view @ projection, None)
    mirror = ViewFrame(None, None, (0, 0) + planned.size, planned.modelView,
                       planned.projection, planned.modelproj, None)
    record = view_records([mirror], reference)[0]
    world = np.array([0.4, 1.2, 1.0, 1.0])
    assert np.allclose((world @ view) @ record.refToClip, world @ planned.modelproj)
