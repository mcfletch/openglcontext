"""The room oglc-mirrors hangs its mirrors in; no GL.

:class:`~OpenGLContext.bin.mirrorhall.Hall` is scenery: walls, ceiling,
columns, lamps, and the places a demo puts its own surfaces. These hold it to
having no mirrors of its own and to putting a surface where it is asked.
"""
import numpy as np
import pytest

from OpenGLContext.bin.mirrorhall import HEIGHT, LENGTH, WIDTH, Hall
from OpenGLContext.passes import reflection
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from tests.unit.test_mirrors_demo import _placed

INSIDE = np.array([0.0, HEIGHT / 2.0, 0.0])


@pytest.fixture(scope='module')
def hall():
    return Hall()


def _records(nodes):
    found = []
    for node in nodes:
        _placed(node, out=found)
    return found


def _facing(record):
    """A flat shape's world centre and normal."""
    mesh = record[5].geometry
    matrix = np.asarray(record[2], 'd')
    centre = np.append(mesh.positions.mean(axis=0), 1.0) @ matrix
    normal = np.append(mesh.normals[0], 0.0) @ matrix
    return centre[:3], normal[:3] / np.linalg.norm(normal[:3])


def test_the_room_has_no_mirrors_of_its_own(hall):
    records = _records(hall.room())
    assert len(records) > 10
    assert not [record for record in records if reflection.is_reflector(record)]


def test_every_textured_surface_in_the_room_is_textured_by_the_metre(hall):
    for record in _records(hall.room()):
        mesh = record[5].geometry
        if getattr(record[5].appearance.material, 'textures', None):
            assert getattr(mesh, 'tangents', None) is not None


@pytest.mark.parametrize('wall, along, plane', [
    ('far', 1.0, (2, -LENGTH / 2)), ('near', -1.0, (2, LENGTH / 2)),
    ('left', 2.0, (0, -WIDTH / 2)), ('right', -2.0, (0, WIDTH / 2)),
])
def test_a_surface_hung_on_a_wall_faces_into_the_room_just_off_it(hall, wall, along, plane):
    material = PBRMaterial()
    [record] = _records(hall.hang(surfaces.panel(1.0, 1.0), material, wall, along, 1.5))
    centre, normal = _facing(record)
    axis, at = plane
    assert abs(centre[axis] - at) < 0.2 and abs(centre[axis] - at) > 0.0
    assert centre[1] == pytest.approx(1.5)
    assert centre[2 - axis if axis == 0 else 0] == pytest.approx(along)
    assert np.dot(normal, INSIDE - centre) > 0.0


def test_a_frame_borders_the_surface_behind_it(hall):
    material, gilt = PBRMaterial(), PBRMaterial()
    hung, frame = _records(hall.hang(surfaces.panel(2.0, 1.0), material, 'far', 0.0, 2.0,
                                     frame=gilt, border=0.2))
    assert frame[5].appearance.material is gilt
    extent = np.ptp(frame[5].geometry.positions, axis=0)
    assert extent[:2] == pytest.approx((2.4, 1.4))
    surface_z = _facing(hung)[0][2]
    frame_z = (np.append(frame[5].geometry.positions.mean(axis=0), 1.0)
               @ np.asarray(frame[2], 'd'))[2]
    assert -LENGTH / 2 < frame_z < surface_z


def test_a_basin_rims_the_pool_it_is_given_and_tiles_its_bottom(hall):
    basin = hall.basin(1.0, 3.0, -4.0, -2.0)
    [(rim_low, rim_high)] = _blocks(basin, hall.finish.sandstone)
    [(low, high)] = _blocks(basin, hall.finish.pool)
    assert 0.0 < low[1] and high[1] < 0.05 and high[1] - low[1] < 1e-6  # above the floor
    assert (low[0], high[0], low[2], high[2]) == pytest.approx((1.0, 3.0, -4.0, -2.0))
    assert rim_low[0] < 1.0 and rim_high[0] > 3.0
    assert rim_low[2] < -4.0 and rim_high[2] > -2.0


def test_a_wall_the_hall_does_not_have_is_refused(hall):
    with pytest.raises(ValueError):
        hall.hang(surfaces.panel(1.0, 1.0), PBRMaterial(), 'ceiling', 0.0, 1.0)


# --- what breaks the room up -------------------------------------------------------

from OpenGLContext.bin.mirrorhall import BAYS, PILASTERS, STEPS, WINDOWS


def _pieces(hall, material):
    """Every piece of the hall's scenery wearing ``material``, as world bounds."""
    return [(part.geometry.positions.min(axis=0), part.geometry.positions.max(axis=0))
            for part in hall.parts() if part.material is material]


def test_the_room_draws_its_scenery_merged(hall):
    """A shape for each group of the room and material, holding every piece."""
    parts = hall.parts()
    worn = {id(part.material) for part in parts}
    shapes = [record for record in _records(hall.room())
              if id(record[5].appearance.material) in worn]
    assert len(shapes) == len({(p.group, id(p.material)) for p in parts})
    assert len(shapes) * 4 < len(parts)
    assert sum(len(r[5].geometry.indices) for r in shapes) == sum(
        len(p.geometry.indices) for p in parts)


def _blocks(nodes, material):
    """Every shape wearing ``material``, as its world-space bounds."""
    found = []
    for record in _records(nodes):
        if record[5].appearance.material is not material:
            continue
        points = record[5].geometry.positions
        world = (np.c_[points, np.ones(len(points))] @ np.asarray(record[2], 'd'))[:, :3]
        found.append((world.min(axis=0), world.max(axis=0)))
    return found


def test_the_windows_open_onto_a_sky(hall):
    from OpenGLContext.scenegraph.basenodes import Background
    room = hall.room()
    assert any(isinstance(node, Background) for node in room)
    brick = _pieces(hall, hall.finish.brick)
    for along, low, high in WINDOWS:
        middle = np.array([WIDTH / 2, (low + high) / 2, along])
        covering = [(lo, hi) for lo, hi in brick
                    if (lo - 1e-3 <= middle).all() and (middle <= hi + 1e-3).all()]
        assert covering == []


# --- how the room is lit ---------------------------------------------------------------

def test_only_the_lamp_housings_cast_no_shadow(hall):
    """A housing stands between its lamp and the room; everything else casts."""
    records = _records(hall.room())
    lamp = hall.finish.lamp
    housings = [r[5] for r in records if r[5].appearance.material is lamp]
    assert housings
    assert not any(shape.castsShadow for shape in housings)
    assert all(r[5].castsShadow for r in records if r[5].appearance.material is not lamp)


def test_the_sun_comes_in_through_the_windows_well_onto_the_floor(hall):
    """Each window lays its light on the floor inside, reaching metres into the room."""
    from OpenGLContext.scenegraph.basenodes import DirectionalLight
    [sun] = [node for node in hall.room() if isinstance(node, DirectionalLight)]
    direction = np.asarray(sun.direction, 'd')
    for along, low, high in WINDOWS:
        for height in (low, high):
            opening = np.array([WIDTH / 2, height, along])
            landing = opening + direction * (height / -direction[1])
            assert abs(landing[0]) < WIDTH / 2 and abs(landing[2]) < LENGTH / 2
        assert WIDTH / 2 - landing[0] > 2.0


def test_the_room_is_lit_by_what_can_be_seen_inside_it(hall):
    """A zone round the whole room takes its environment from a capture."""
    from OpenGLContext.scenegraph.basenodes import Transform, Zone
    [holder] = [node for node in hall.room() if isinstance(node, Transform)
                and any(isinstance(child, Zone) for child in node.children)]
    [zone] = holder.children
    [setting] = zone.settings
    assert setting.capture
    low = np.asarray(holder.translation) - np.asarray(zone.size) / 2
    high = np.asarray(holder.translation) + np.asarray(zone.size) / 2
    for part in hall.parts():
        points = part.geometry.positions
        assert (points.min(axis=0) > low).all() and (points.max(axis=0) < high).all()


def test_the_floor_steps_up_to_the_far_wall(hall):
    treads = sorted(_pieces(hall, hall.finish.treads), key=lambda box: box[1][1])
    assert [round(float(hi[1]), 3) for _lo, hi in treads] == [rise for rise, _front in STEPS]
    fronts = [float(hi[2]) for _lo, hi in treads]
    assert fronts == sorted(fronts, reverse=True)
    assert all(float(lo[2]) == pytest.approx(-LENGTH / 2) for lo, _hi in treads)


def test_every_step_has_a_nosing_along_its_edge(hall):
    nosings = _pieces(hall, hall.finish.nosing)
    assert len(nosings) == len(STEPS)
    for rise, front in STEPS:
        [edge] = [(lo, hi) for lo, hi in nosings if abs(float(hi[1]) - rise) < 0.02]
        assert float(edge[1][2]) >= front and float(edge[0][2]) < front
        assert float(edge[1][0] - edge[0][0]) > WIDTH * 0.95


def test_half_columns_stand_between_the_bays(hall):
    for wall, bays in BAYS.items():
        for pilaster in PILASTERS[wall]:
            assert min(abs(pilaster - bay) for bay in bays) > 0.6
    columns = _pieces(hall, hall.finish.pilaster)
    assert len(columns) == sum(len(places) for places in PILASTERS.values())


@pytest.mark.parametrize('height', [0.09, 0.9, 4.25])
def test_a_molding_runs_the_length_of_every_wall_at_its_height(hall, height):
    runs = [(lo, hi) for lo, hi in _pieces(hall, hall.finish.molding)
            if lo[1] - 0.05 <= height <= hi[1] + 0.05]
    for axis, span in ((0, WIDTH), (2, LENGTH)):
        assert any(float(hi[axis] - lo[axis]) > span * 0.9 for lo, hi in runs)
