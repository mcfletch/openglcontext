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


def test_a_basin_rims_the_pool_it_is_given(hall):
    rim = _records(hall.basin(1.0, 3.0, -4.0, -2.0))
    assert len(rim) == 4
    reach = np.concatenate([
        (np.c_[record[5].geometry.positions, np.ones(24)] @ np.asarray(record[2], 'd'))[:, :3]
        for record in rim])
    assert reach[:, 0].min() < 1.0 and reach[:, 0].max() > 3.0
    assert reach[:, 2].min() < -4.0 and reach[:, 2].max() > -2.0


def test_a_wall_the_hall_does_not_have_is_refused(hall):
    with pytest.raises(ValueError):
        hall.hang(surfaces.panel(1.0, 1.0), PBRMaterial(), 'ceiling', 0.0, 1.0)
