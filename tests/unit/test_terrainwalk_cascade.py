"""Event-cascade hook and no-op guard for :mod:`OpenGLContext.move.terrainwalk`.

The walk mixin clamps the viewer to the ground inside :meth:`DoEventCascade`, after
the host's own cascade. These tests confirm the mixin chains to ``super()`` and then
runs the clamp, and that the clamp is a safe no-op when there is no platform or no
height field bound.
"""
import numpy as np
import pytest

from OpenGLContext import context as context_module
from OpenGLContext.scenegraph.terrain import HeightField

from ._terrain_host import Clock


@pytest.fixture
def clock():
    made = Clock()
    yield made
    made.restore()


@pytest.fixture
def host_cascade(monkeypatch):
    """The context's own cascade, replaced by one that records that it ran."""
    ran = []

    def cascade(self):
        ran.append(self)
        return 'host-changed'

    monkeypatch.setattr(context_module.Context, 'DoEventCascade', cascade)
    return ran


def test_do_event_cascade_chains_to_host_then_clamps_to_ground(clock, host_cascade):
    """DoEventCascade runs the host cascade, returns its value, and clamps height."""
    hf = HeightField(np.full((8, 8), 1.0), 100.0, 5.0)   # flat ground at y=5
    walker = clock.host((3.0, 999.0, -2.0))
    walker.init_walk(hf)
    result = walker.DoEventCascade()
    assert host_cascade == [walker]                      # host cascade ran
    assert result == 'host-changed'                      # and its result propagates
    # viewer seated on the terrain at eye height, not left at y=999
    assert walker.platform.position[1] == pytest.approx(5.0 + walker.eye_height, abs=0.02)


def test_the_cascade_runs_and_clamps_nothing_without_a_platform(clock, host_cascade):
    """With no platform bound the host cascade still runs and nothing is placed."""
    walker = clock.host(platform=False)
    walker.init_walk(HeightField(np.zeros((4, 4)), 10.0, 0.0))
    assert walker.DoEventCascade() == 'host-changed'
    assert host_cascade == [walker]
    assert walker.platform is None


def test_clamp_is_a_noop_without_a_height_field(clock):
    """collide_and_clamp returns immediately when no height field is bound."""
    walker = clock.host((0.0, 0.0, 0.0))
    walker.collide_and_clamp()                            # no field bound
    assert tuple(walker.platform.position[:3]) == (0.0, 0.0, 0.0)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
