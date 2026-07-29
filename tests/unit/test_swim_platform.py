"""Swimming moves where you are *looking*, which walking deliberately does not.

A walk flattens the move to the ground plane: leaning forward should not push
a player into the floor.  Under water that flattening is exactly wrong — the
surface and the bottom would be reachable only by the dedicated keys, which is
walking with the gravity turned off rather than swimming.
"""
import math

import numpy as np
import pytest

from omi_physics import model
from omi_physics.world import PhysicsWorld

from OpenGLContext.move.physicsplatform import PhysicsViewPlatform


def platform(**named):
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    return PhysicsViewPlatform(world, **named)


def moved(made):
    """The direction the character was last told to move."""
    return np.asarray(made.character.fly_dir, dtype='d')


class TestMovingAlongTheGaze:

    def test_level_forward_is_the_same_as_walking_forward(self):
        made = platform()
        made.set_swim_move(forward=1.0)
        assert float(moved(made)[1]) == pytest.approx(0.0, abs=1e-9)

    def test_looking_down_and_swimming_forward_goes_down(self):
        made = platform()
        made.look(0.6)                      # positive pitch looks *down*
        made.set_swim_move(forward=1.0)
        assert float(moved(made)[1]) < -0.1

    def test_looking_up_and_swimming_forward_goes_up(self):
        made = platform()
        made.look(-0.6)
        made.set_swim_move(forward=1.0)
        assert float(moved(made)[1]) > 0.1

    def test_swimming_backward_while_looking_down_goes_up(self):
        made = platform()
        made.look(0.6)
        made.set_swim_move(forward=-1.0)
        assert float(moved(made)[1]) > 0.1

    def test_the_move_is_a_direction_rather_than_a_speed(self):
        made = platform()
        made.look(0.6)
        made.set_swim_move(forward=1.0)
        assert float(np.linalg.norm(moved(made))) == pytest.approx(1.0, abs=1e-6)

    def test_strafing_stays_level_however_you_are_looking(self):
        """Sidling should not sink you; it is the one axis that stays flat."""
        made = platform()
        made.look(0.9)
        made.set_swim_move(strafe=1.0)
        assert float(moved(made)[1]) == pytest.approx(0.0, abs=1e-9)

    def test_the_up_key_still_rises_whatever_you_are_looking_at(self):
        """For holding depth while looking somewhere else."""
        made = platform()
        made.look(0.9)
        made.set_swim_move(up=1.0)
        assert float(moved(made)[1]) > 0.5

    def test_looking_and_pressing_up_add_rather_than_replace(self):
        made = platform()
        made.look(-0.4)
        made.set_swim_move(forward=1.0, up=1.0)
        assert float(moved(made)[1]) > 0.5

    def test_turning_swings_the_swim_the_way_it_swings_a_walk(self):
        made = platform()
        made.turn(math.pi / 2)
        made.set_swim_move(forward=1.0)
        level = moved(made)
        made.set_move(forward=1.0)
        assert np.allclose(level, np.asarray(made.character.move_dir), atol=1e-6)

    def test_no_input_at_all_is_no_movement(self):
        made = platform()
        made.set_swim_move()
        assert float(np.linalg.norm(moved(made))) == pytest.approx(0.0, abs=1e-9)
