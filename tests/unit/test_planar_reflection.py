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


# --- how rough a mirror is ---------------------------------------------------

def _textured(roughness_texel, factor=1.0):
    from PIL import Image
    from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
    pixels = np.zeros((4, 4, 3), np.uint8)
    pixels[..., 1] = int(roughness_texel * 255)
    return PBRMaterial(roughness=factor, textures={
        'metallicRoughness': PBRTexture(Image.fromarray(pixels, 'RGB'))})


def test_a_mirrors_roughness_is_its_factor_where_it_has_no_map():
    assert reflection.surface_roughness(PBRMaterial(roughness=0.2)) == pytest.approx(0.2)


def test_a_roughness_map_scales_the_factor():
    """glTF's way: factor 1, and the map says how rough the surface is."""
    assert reflection.surface_roughness(_textured(0.1)) == pytest.approx(0.1, abs=0.01)
    assert reflection.surface_roughness(_textured(0.5, 0.5)) == pytest.approx(0.25, abs=0.01)


def test_a_polished_textured_floor_is_a_mirror():
    from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
    from OpenGLContext.passes.reflectiontiles import Budget
    from OpenGLContext.multiview.strategy import ViewFrame
    from OpenGLContext.multiview.views import View
    record = _mirror_record(placement=_placement(translate=(0.0, 1.5, -5.0)))
    material = _textured(0.05)
    material.reflector = reflection.reflector_for(record)
    record[5].appearance.material = material
    view = _look_at((1.0, 1.6, 3.0), (0.0, 1.5, -5.0))
    projection = _perspective(aspect=2.0)
    frame = ViewFrame(View(), None, VIEW_RECT, view, projection, view @ projection, None)
    frame.toRender = [record]
    plan = ReflectionPlanner().plan([frame], (512, 512),
                                    Budget(views=4, separate_views=4, texels=10 ** 9))
    assert len(plan.draws) == 1


# --- which shapes are mirrors ---------------------------------------------------

def test_making_a_shape_a_mirror_moves_the_mirror_generation():
    """A pass remembers which of the scene's shapes are mirrors until one of
    the fields that decide it is set."""
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.reflector import PlanarReflector
    material = PBRMaterial()
    appearance = basenodes.Appearance(material=material)
    shape = basenodes.Shape(appearance=appearance)
    reflector = PlanarReflector()
    seen = [reflection.mirror_generation()]
    material.reflector = reflector
    seen.append(reflection.mirror_generation())
    reflector.enabled = False
    seen.append(reflection.mirror_generation())
    appearance.material = PBRMaterial()
    seen.append(reflection.mirror_generation())
    shape.appearance = basenodes.Appearance()
    seen.append(reflection.mirror_generation())
    assert all(later > earlier for earlier, later in zip(seen, seen[1:]))


def test_making_a_mesh_water_moves_the_mirror_generation():
    """A mesh with a wave is water, and water is a mirror."""
    import numpy as np
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
    from OpenGLContext.scenegraph.water.surface import WaterStyle
    mesh = PBRMesh(positions=np.zeros((3, 3), 'f'), indices=np.arange(3, dtype=np.uint32))
    before = reflection.mirror_generation()
    mesh.waveStyle = WaterStyle()
    assert reflection.mirror_generation() > before


# --- the fitted plane is kept while its inputs are --------------------------------

XZ_QUAD = np.array([(-1, 0, -1), (-1, 0, 1), (1, 0, 1), (1, 0, -1)], 'f')


def test_a_replaced_point_array_is_fitted_again_every_time():
    """The kept fit is the fit of the array the mesh holds now, even where a
    new array is given the address a released one had."""
    mesh = PBRMesh(positions=QUAD.copy(), indices=QUAD_INDICES)
    for turn in range(40):
        facing_up = turn % 2 == 1
        mesh.positions = None
        mesh.positions = np.array(XZ_QUAD if facing_up else QUAD, 'f')
        normal = reflection.mesh_plane(mesh).normal
        expected = (0.0, 1.0, 0.0) if facing_up else (0.0, 0.0, 1.0)
        assert tuple(normal) == pytest.approx(expected, abs=1e-6), turn


def test_replaced_indices_turn_the_plane_over():
    mesh = PBRMesh(positions=QUAD.copy(), indices=QUAD_INDICES)
    assert reflection.mesh_plane(mesh).normal[2] == pytest.approx(1.0)
    mesh.indices = QUAD_INDICES[::-1].copy()
    assert reflection.mesh_plane(mesh).normal[2] == pytest.approx(-1.0)


def test_a_mesh_plane_is_fitted_once_while_the_mesh_is_unchanged():
    mesh = PBRMesh(positions=QUAD.copy(), indices=QUAD_INDICES)
    assert reflection.mesh_plane(mesh) is reflection.mesh_plane(mesh)


def test_still_waters_plane_is_worked_out_once():
    record = _water_record(0.5)
    assert reflection.local_plane(record) is reflection.local_plane(record)


def test_water_whose_sheet_is_replaced_reflects_at_its_new_level():
    record = _water_record(0.5)
    geometry = record[5].geometry
    assert reflection.local_plane(record).point[1] == pytest.approx(0.5)
    geometry.positions = geometry.positions + np.array([0.0, 1.0, 0.0], 'f')
    assert reflection.local_plane(record).point[1] == pytest.approx(1.5)


def test_a_mesh_made_water_reflects_at_its_level_not_its_fit():
    """One geometry asked about as a mirror and then as water answers each."""
    tilted = np.array([(-1, 0, -1), (1, 0, -1), (1, 1, 1)], 'f')
    mesh = PBRMesh(positions=tilted, indices=np.array([0, 2, 1], np.uint32))
    record = ((False,), None, np.identity(4, 'f'), None, (), Shape(
        geometry=mesh, appearance=Appearance(material=PBRMaterial(
            reflector=PlanarReflector()))))
    assert reflection.local_plane(record).normal[1] != pytest.approx(1.0)
    mesh.waveStyle = STILL
    assert tuple(reflection.local_plane(record).normal) == pytest.approx((0.0, 1.0, 0.0))


# --- VRML97 IndexedFaceSet mirrors ---------------------------------------------------

def _face_set(points, coord_index, ccw=True):
    from OpenGLContext.scenegraph import basenodes
    return basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=np.asarray(points, 'f')),
        coordIndex=list(coord_index), ccw=ccw)


def _face_set_record(geometry):
    material = PBRMaterial(metallic=1.0, roughness=0.0, reflector=PlanarReflector())
    shape = Shape(geometry=geometry, appearance=Appearance(material=material))
    return ((False,), None, np.identity(4, 'f'), None, (), shape)


@pytest.mark.parametrize('ccw,facing', [(True, 1.0), (False, -1.0)])
def test_a_face_set_mirror_faces_the_side_its_winding_says(ccw, facing):
    """``ccw FALSE`` names the other side of the same winding as the front."""
    record = _face_set_record(_face_set(QUAD, [0, 1, 2, 3, -1], ccw=ccw))
    point, normal = reflection.surface_plane(record)
    assert tuple(normal) == pytest.approx((0.0, 0.0, facing))


def test_turning_a_face_set_over_turns_its_plane_over():
    geometry = _face_set(QUAD, [0, 1, 2, 3, -1])
    assert reflection.mesh_plane(geometry).normal[2] == pytest.approx(1.0)
    geometry.ccw = False
    assert reflection.mesh_plane(geometry).normal[2] == pytest.approx(-1.0)


def test_a_face_set_of_many_cornered_polygons_is_fanned():
    """Two pentagons, the second without a closing -1, both facing +z."""
    angles = np.linspace(0.0, 2.0 * np.pi, 6)[:5]
    ring = np.c_[np.cos(angles), np.sin(angles), np.zeros(5)]
    points = np.concatenate([ring, ring + (3.0, 0.0, 0.0)])
    geometry = _face_set(points, [0, 1, 2, 3, 4, -1, 5, 6, 7, 8, 9])
    assert reflection.fan([0, 1, 2, 3, 4, -1, 5, 6, 7]).tolist() == [
        0, 1, 2, 0, 2, 3, 0, 3, 4, 5, 6, 7]
    fitted = reflection.mesh_plane(geometry)
    assert tuple(fitted.normal) == pytest.approx((0.0, 0.0, 1.0))


def test_a_face_set_with_no_polygon_is_read_as_triangles_in_order():
    assert reflection.fan([]) is None
    assert reflection.fan([0, 1, -1]) is None
    geometry = _face_set(QUAD[:3], [])
    assert tuple(reflection.mesh_plane(geometry).normal) == pytest.approx((0.0, 0.0, 1.0))


def test_a_face_set_without_points_is_no_mirror():
    from OpenGLContext.scenegraph import basenodes
    record = _face_set_record(basenodes.IndexedFaceSet())
    assert reflection.surface_plane(record) is None


# --- a map's roughness is worked out once per image ---------------------------------

def test_a_roughness_maps_mean_is_kept_on_its_texture():
    from PIL import Image
    material = _textured(0.2)
    texture = material.textures['metallicRoughness']
    assert texture.mean_roughness() == pytest.approx(0.2, abs=0.01)
    pixels = np.zeros((4, 4, 3), np.uint8)
    pixels[..., 1] = 204
    texture.image = Image.fromarray(pixels, 'RGB')
    assert texture.mean_roughness() == pytest.approx(0.8, abs=0.01)


def test_a_large_roughness_maps_mean_is_its_greens_mean():
    from PIL import Image
    from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
    rows = np.linspace(0, 255, 3000).astype(np.uint8)
    pixels = np.zeros((3000, 2000, 4), np.uint8)
    pixels[..., 1] = rows[:, None]
    pixels[..., 0] = 255
    texture = PBRTexture(Image.fromarray(pixels, 'RGBA'))
    assert texture.mean_roughness() == pytest.approx(rows.mean() / 255.0, abs=0.01)


@pytest.mark.parametrize('mode', ['L', 'P', 'I;16'])
def test_a_roughness_map_in_any_mode_has_a_mean(mode):
    from PIL import Image
    from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
    image = Image.new('RGB', (8, 8), (0, 128, 0)).convert(mode)
    expected = np.asarray(image.convert('RGB'))[..., 1].mean() / 255.0
    assert PBRTexture(image).mean_roughness() == pytest.approx(expected, abs=0.01)


def test_a_mesh_drawn_with_its_own_material_is_as_rough_as_that_material():
    """A mesh with no appearance material is drawn with the one it carries."""
    from OpenGLContext.multiview.strategy import ViewFrame
    from OpenGLContext.multiview.views import View
    from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
    from OpenGLContext.passes.reflectiontiles import Budget
    rough = PBRMaterial(roughness=0.9, reflector=PlanarReflector())
    shape = Shape(geometry=PBRMesh(positions=QUAD, indices=QUAD_INDICES, material=rough))
    assert reflection.shape_material(shape) is rough
    record = ((False,), None, np.asarray(_placement(translate=(0.0, 1.5, -5.0)), 'f'),
              None, (), shape)
    view = _look_at((1.0, 1.6, 3.0), (0.0, 1.5, -5.0))
    projection = _perspective(aspect=2.0)
    frame = ViewFrame(View(), None, VIEW_RECT, view, projection, view @ projection, None)
    frame.toRender = [record]
    plan = ReflectionPlanner().plan([frame], (512, 512),
                                    Budget(views=4, separate_views=4, texels=10 ** 9))
    assert plan.draws == []


def test_the_public_names_are_the_ones_other_modules_use():
    for name in ('NDCRect', 'WHOLE', 'TEXEL_STEP', 'TileRect', 'mesh_plane', 'texels',
                 'shape_material', 'fan'):
        assert name in reflection.__all__
    assert 'WATER_DISTORTION' not in reflection.__all__


@pytest.mark.parametrize('tile', [(4, 4, 48, 48), (0, 0, 8, 8), (100, 36, 24, 200)])
def test_a_tiles_bounds_name_the_tile_they_were_made_from(tile):
    atlas = (1360, 768)
    assert reflection.bounds_tile(reflection.tile_bounds(tile, atlas), atlas) == tile


# --- a mirror with a corner behind the camera --------------------------------------

def _floor_corners(half=20.0):
    return reflection.box_corners(np.array([(-half, 0.0, -half), (half, 0.0, half)]))


def test_a_floor_under_a_level_camera_covers_the_view_below_the_horizon():
    """Half the floor is behind the camera, and still it covers only the
    lower half of the view, not all of it."""
    view = _look_at((0.0, 1.6, 0.0), (0.0, 1.6, -10.0))
    rect = reflection.screen_rect(_floor_corners(), view @ _perspective())
    x0, y0, x1, y1 = rect
    assert (x0, y0, x1) == pytest.approx((-1.0, -1.0, 1.0))
    assert -0.2 < y1 < 0.0


def test_a_mirror_off_to_one_side_and_behind_covers_only_its_side():
    view = _look_at((0.0, 0.0, 0.0), (0.0, 0.0, -10.0))
    wall = reflection.box_corners(np.array([(3.0, -1.0, -10.0), (3.0, 1.0, 10.0)]))
    x0, y0, x1, y1 = reflection.screen_rect(wall, view @ _perspective())
    assert x0 > 0.0 and x1 == pytest.approx(1.0)


def test_several_boxes_with_corners_behind_the_camera_are_clipped_each():
    view = _look_at((0.0, 1.6, 0.0), (0.0, 1.6, -10.0))
    corners = np.concatenate([_floor_corners(), _floor_corners() + (0.0, 0.0, 30.0)])
    x0, y0, x1, y1 = reflection.screen_rect(corners, view @ _perspective())
    assert y1 < 0.0


def test_a_mirror_wholly_behind_the_camera_plane_covers_nothing():
    view = _look_at((0.0, 0.0, 0.0), (0.0, 0.0, -10.0))
    behind = reflection.box_corners(np.array([(-1.0, -1.0, 1.0), (1.0, 1.0, 3.0)]))
    assert reflection.screen_rect(behind, view @ _perspective()) is None
