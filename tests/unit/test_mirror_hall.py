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
    rim = _blocks(basin, hall.finish.sandstone)
    [(low, high)] = _blocks(basin, hall.finish.pool)
    assert len(rim) == 4
    assert 0.0 < low[1] and high[1] < 0.05 and high[1] - low[1] < 1e-6  # above the floor
    assert (low[0], high[0], low[2], high[2]) == pytest.approx((1.0, 3.0, -4.0, -2.0))
    reach = np.concatenate([np.array([lo, hi]) for lo, hi in rim])
    assert reach[:, 0].min() < 1.0 and reach[:, 0].max() > 3.0
    assert reach[:, 2].min() < -4.0 and reach[:, 2].max() > -2.0


def test_a_wall_the_hall_does_not_have_is_refused(hall):
    with pytest.raises(ValueError):
        hall.hang(surfaces.panel(1.0, 1.0), PBRMaterial(), 'ceiling', 0.0, 1.0)


# --- what breaks the room up -------------------------------------------------------

from OpenGLContext.bin.mirrorhall import BAYS, PILASTERS, STEPS, WINDOWS  # noqa: E402


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
    brick = _blocks(room, hall.finish.brick)
    for along, low, high in WINDOWS:
        middle = np.array([WIDTH / 2, (low + high) / 2, along])
        covering = [(lo, hi) for lo, hi in brick
                    if (lo - 1e-3 <= middle).all() and (middle <= hi + 1e-3).all()]
        assert covering == []


def test_the_floor_steps_up_to_the_far_wall(hall):
    treads = sorted(_blocks(hall.room(), hall.finish.treads), key=lambda box: box[1][1])
    assert [round(float(hi[1]), 3) for _lo, hi in treads] == [rise for rise, _front in STEPS]
    fronts = [float(hi[2]) for _lo, hi in treads]
    assert fronts == sorted(fronts, reverse=True)
    assert all(float(lo[2]) == pytest.approx(-LENGTH / 2) for lo, _hi in treads)


def test_every_step_has_a_nosing_along_its_edge(hall):
    nosings = _blocks(hall.room(), hall.finish.nosing)
    assert len(nosings) == len(STEPS)
    for rise, front in STEPS:
        [edge] = [(lo, hi) for lo, hi in nosings if abs(float(hi[1]) - rise) < 0.02]
        assert float(edge[1][2]) >= front and float(edge[0][2]) < front
        assert float(edge[1][0] - edge[0][0]) > WIDTH * 0.95


def test_half_columns_stand_between_the_bays(hall):
    for wall, bays in BAYS.items():
        for pilaster in PILASTERS[wall]:
            assert min(abs(pilaster - bay) for bay in bays) > 0.6
    columns = [record for record in _records(hall.room())
               if record[5].appearance.material is hall.finish.pilaster]
    assert len(columns) == sum(len(places) for places in PILASTERS.values())


@pytest.mark.parametrize('height', [0.09, 0.9, 4.25])
def test_a_molding_runs_the_length_of_every_wall_at_its_height(hall, height):
    runs = [(lo, hi) for lo, hi in _blocks(hall.room(), hall.finish.molding)
            if lo[1] - 0.05 <= height <= hi[1] + 0.05]
    for axis, span in ((0, WIDTH), (2, LENGTH)):
        assert any(float(hi[axis] - lo[axis]) > span * 0.9 for lo, hi in runs)
