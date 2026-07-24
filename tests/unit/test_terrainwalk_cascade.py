"""Event-cascade hook and no-op guard for :mod:`OpenGLContext.move.terrainwalk`.

The walk mixin clamps the viewer to the ground inside :meth:`DoEventCascade`, after
the host's own cascade. These tests confirm the mixin chains to ``super()`` and then
runs the clamp, and that the clamp is a safe no-op when there is no platform or no
height field bound.
"""
import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.move.terrainwalk import TerrainWalkMixin


class _FakePlatform:
    def __init__(self, p):
        self._p = np.array(p, 'd')
        self.quaternion = quaternion.fromXYZR(0, 1, 0, 0.0)

    @property
    def position(self):
        return self._p

    def setPosition(self, p):
        self._p = np.array(p, 'd')


class _Host:
    """A minimal host context whose DoEventCascade records that it ran."""
    def __init__(self):
        self.cascaded = False

    def DoEventCascade(self):
        self.cascaded = True
        return 'host-changed'


class _Walker(TerrainWalkMixin, _Host):
    def __init__(self, platform=None):
        _Host.__init__(self)
        self.platform = platform


def test_do_event_cascade_chains_to_host_then_clamps_to_ground():
    """DoEventCascade runs the host cascade, returns its value, and clamps height."""
    hf = HeightField(np.full((8, 8), 1.0), 100.0, 5.0)   # flat ground at y=5
    walker = _Walker(_FakePlatform((3.0, 999.0, -2.0)))
    walker.init_walk(hf)
    result = walker.DoEventCascade()
    assert walker.cascaded is True                       # host cascade ran
    assert result == 'host-changed'                      # and its result propagates
    # viewer snapped to terrain height + eye height, not left at y=999
    assert walker.platform.position[1] == pytest.approx(5.0 + walker.eye_height)


def test_clamp_is_a_noop_without_a_platform():
    """collide_and_clamp returns immediately when no platform is bound."""
    walker = _Walker(platform=None)
    walker.init_walk(HeightField(np.zeros((4, 4)), 10.0, 0.0))
    walker.collide_and_clamp()                            # must not raise


def test_clamp_is_a_noop_without_a_height_field():
    """collide_and_clamp returns immediately when no height field is bound."""
    walker = _Walker(_FakePlatform((0.0, 0.0, 0.0)))
    walker.collide_and_clamp()                            # _tw_hf never set
    assert tuple(walker.platform.position) == (0.0, 0.0, 0.0)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
