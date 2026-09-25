"""The direction a camera looks along, for a ray cast from the view.

A gun, a pick or a line of sight starts at the camera and goes where it
faces: ``forward()`` answers that direction in world coordinates.
"""
import math

import numpy as np
import pytest

from OpenGLContext.move.viewplatform import ViewPlatform


def test_an_unturned_camera_looks_down_minus_z() -> None:
    assert np.allclose(ViewPlatform().forward(), (0.0, 0.0, -1.0))


@pytest.mark.parametrize('degrees', [30, 90, 135, 270])
def test_a_turn_about_y_turns_it(degrees: float) -> None:
    platform = ViewPlatform()
    platform.setOrientation((0.0, 1.0, 0.0, math.radians(degrees)))
    forward = platform.forward()
    assert forward.shape == (3,)
    assert np.linalg.norm(forward) == pytest.approx(1.0)
    assert forward[1] == pytest.approx(0.0, abs=1e-9)
    expected = (platform.quaternion * [0.0, 0.0, -1.0, 0.0])[:3]
    assert np.allclose(forward, expected)


def test_it_is_the_way_a_relative_move_forward_goes() -> None:
    platform = ViewPlatform(position=(1.0, 2.0, 3.0))
    platform.setOrientation((1.0, 0.0, 0.0, 0.4))
    step = np.asarray(platform.relativePosition(z=-1.0))[:3] - platform.position[:3]
    assert np.allclose(platform.forward(), step)
