"""The props a baked world carries, read back by the engine.

A world's boulders travel in its tileset's ``extras`` as JSON, one object per
prop. Its loose stone is tens of thousands of props, and the ``extras`` is
parsed by everything that opens the world, so those travel as a binary table
beside the tileset with only its name and count in ``extras``
(:func:`~OpenGLContext.scenegraph.props.props_table`).
:func:`~OpenGLContext.loaders.tiles3d.props.baked_props` reads either form, and
``PropColliders.baked`` stands them up.
"""
import json

import numpy as np
import pytest
from omi_physics.world import PhysicsWorld

from OpenGLContext.loaders.tiles3d.props import baked_props
from OpenGLContext.physics.props import PropColliders
from OpenGLContext.scenegraph.props import Prop, props_from_table, props_table

STONES = [Prop('granite', (float(i), 0.5 * i, -2.0 * i), yaw=0.1 * i,
               scale=1.0 + 0.01 * i, radius=0.3 + 0.001 * i,
               height=0.2 + 0.002 * i, shape='dome')
          for i in range(50)] + [Prop('slate', (7.0, 1.0, 9.0), shape='box')]


def _close(found, wanted):
    assert [one.kind for one in found] == [one.kind for one in wanted]
    assert [one.shape for one in found] == [one.shape for one in wanted]
    for name in ('yaw', 'scale', 'radius', 'height'):
        np.testing.assert_allclose([getattr(one, name) for one in found],
                                   [getattr(one, name) for one in wanted],
                                   rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose([one.position for one in found],
                               [one.position for one in wanted], atol=1e-4)


class TestTheTable:
    def test_a_table_reads_back_as_the_props_written(self):
        _close(props_from_table(props_table(STONES)), STONES)

    def test_it_is_smaller_than_the_json(self):
        many = STONES * 200
        assert len(props_table(many)) * 4 < len(
            json.dumps([one.to_json() for one in many]))

    def test_no_props_is_an_empty_table(self):
        assert props_from_table(props_table([])) == []

    def test_a_table_that_is_not_one_is_refused(self):
        with pytest.raises(ValueError):
            props_from_table(b'not a table at all')


class TestWhatAWorldCarries:
    def test_props_as_json_in_the_extras(self, tmp_path):
        extras = {'props': [one.to_json() for one in STONES[:3]]}
        _close(baked_props(extras, 'props', str(tmp_path)), STONES[:3])

    def test_props_as_a_table_beside_the_tileset(self, tmp_path):
        (tmp_path / 'stones.npz').write_bytes(props_table(STONES))
        extras = {'stones': {'table': 'stones.npz', 'count': len(STONES)}}
        _close(baked_props(extras, 'stones', str(tmp_path)), STONES)

    def test_a_channel_the_world_does_not_carry_is_empty(self, tmp_path):
        assert baked_props({}, 'stones', str(tmp_path)) == []

    def test_a_table_outside_the_world_is_refused(self, tmp_path):
        (tmp_path / 'stones.npz').write_bytes(props_table(STONES))
        (tmp_path / 'world').mkdir()
        extras = {'stones': {'table': '../stones.npz', 'count': len(STONES)}}
        with pytest.raises(OSError):
            baked_props(extras, 'stones', str(tmp_path / 'world'))

    def test_a_count_that_disagrees_with_the_table_is_refused(self, tmp_path):
        (tmp_path / 'stones.npz').write_bytes(props_table(STONES))
        extras = {'stones': {'table': 'stones.npz', 'count': 3}}
        with pytest.raises(ValueError, match='3'):
            baked_props(extras, 'stones', str(tmp_path))


class TestStandingThemUp:
    def test_the_colliders_are_built_from_the_world(self, tmp_path):
        (tmp_path / 'stones.npz').write_bytes(props_table(STONES))
        extras = {'stones': {'table': 'stones.npz', 'count': len(STONES)}}
        colliders = PropColliders.baked(PhysicsWorld(), extras, 'stones',
                                        str(tmp_path), reach=5.0)
        assert len(colliders.props) == len(STONES)
        colliders.update((0.0, 0.0, 0.0))
        assert 0 < len(colliders.standing) < len(STONES)
