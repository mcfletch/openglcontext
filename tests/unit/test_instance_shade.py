"""Per-instance shade: how much of the sun reaches one plant.

An instanced field is one draw call, so everything in it is lit alike unless the
instance itself says otherwise. Under a canopy that is wrong in the way that
shows most: grass lit like an open field, standing on ground the terrain has
already darkened to a fifth, reads as a row of lamps on the forest floor.

So the instance layout carries a shade with the position, the yaw and the scale.
It defaults to 1 -- full sun -- so a caller with nothing to say about light
says nothing.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.clumps import InstancedClumps

COUNT = 6


def _points():
    return np.zeros((COUNT, 3), 'f4'), np.zeros(COUNT, 'f4'), np.ones(COUNT, 'f4')


def _cards():
    return InstancedBillboards(*_points(), 'grass.png')


def _clumps():
    points = np.zeros((3, 3), 'f4')
    return InstancedClumps(points, points, np.zeros((3, 2), 'f4'),
                           np.arange(3, dtype='u4'), 'clump.png')


class TestWhatAnInstanceCarries:
    def test_a_row_is_position_yaw_scale_and_shade(self) -> None:
        assert _cards()._instance_rows().shape == (COUNT, 6)

    def test_full_sun_unless_told_otherwise(self) -> None:
        assert np.allclose(_cards()._instance_rows()[:, 5], 1.0)

    def test_a_shade_can_be_given_with_the_rest(self) -> None:
        cards = _cards()
        cards.update_instances(*_points(), shades=np.full(COUNT, 0.25, 'f4'))
        assert np.allclose(cards._instance_rows()[:, 5], 0.25)

    def test_it_survives_the_next_update(self) -> None:
        cards = _cards()
        cards.update_instances(*_points(), shades=np.full(COUNT, 0.25, 'f4'))
        cards.update_instances(*_points())
        assert np.allclose(cards._instance_rows()[:, 5], 1.0)

    def test_an_empty_field_has_the_same_shape(self) -> None:
        empty = InstancedBillboards(np.zeros((0, 3), 'f4'), np.zeros(0, 'f4'),
                                    np.zeros(0, 'f4'), 'grass.png')
        assert empty._instance_rows().shape == (0, 6)

    def test_clumps_carry_it_too(self) -> None:
        clumps = _clumps()
        clumps.update_instances(np.zeros((2, 3), 'f4'), np.zeros(2, 'f4'),
                                np.ones(2, 'f4'), shades=np.array([0.3, 0.7],
                                                                  'f4'))
        assert np.allclose(clumps._instance_rows()[:, 5], [0.3, 0.7])

    def test_a_wrong_length_is_reported(self) -> None:
        cards = _cards()
        with pytest.raises(ValueError):
            cards.update_instances(*_points(), shades=np.ones(2, 'f4'))


class TestTheShadersAgreeWithIt:
    def test_every_instanced_shader_reads_a_shade(self) -> None:
        import os
        from OpenGLContext.scenegraph import instancedgl
        where = os.path.join(os.path.dirname(instancedgl.__file__), '..',
                             'shaders')
        for name in ('veg_billboard.vert', 'veg_mesh.vert'):
            with open(os.path.join(where, name)) as handle:
                assert 'aShade' in handle.read(), name


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
