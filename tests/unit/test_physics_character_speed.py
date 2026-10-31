"""A character's speed set with its move, and a run along a course at a speed that changes with time.

Speeds are metres a second. ``set_move(direction, speed=None)`` keeps the
capabilities' speed for the mode; a number moves the character at that speed
whatever the mode. ``run_along(course, speed=...)`` takes a number or a function
of the seconds since the run began.
"""
import numpy as np
import pytest
from OpenGLContext.physics import CharacterCapabilities

from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.roadcourse import RoadCourse

pytestmark = pytest.mark.engines('omi', 'jolt')

#: How close a velocity read back is: Jolt's snapshot holds velocities as float32.
VELOCITY = {'omi': 1e-9, 'jolt': 1e-6}

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
STEP = 1.0 / 120.0


@pytest.fixture
def physics():
    service = Physics(PhysicsDefinition(mode='inline', tickHz=120.0))
    service.add_static(surfaces.shape(surfaces.block((400, 1, 400)), LOOK,
                                      translation=(0, -0.5, 0)), proxy='box')
    yield service
    service.close()


def standing(physics, **options):
    me = physics.add_character(position=(0, 0.05, 0), **options)
    for _ in range(60):
        physics.frame(1 / 60)
    return me


def frames(physics, seconds, before=None):
    for frame in range(int(round(seconds * 60))):
        if before is not None:
            before(frame / 60.0)
        physics.frame(1 / 60)


def test_set_move_with_a_speed_moves_the_character_at_that_speed(physics, physics_engine):
    me = standing(physics)
    start = me.position.copy()
    me.set_move((1, 0, 0), speed=4.5)
    frames(physics, 1.0)
    assert me.velocity[0] == pytest.approx(4.5, abs=VELOCITY[physics_engine])
    assert me.position[0] - start[0] == pytest.approx(4.5, abs=1e-6)
    assert me.speed == 4.5


def test_set_move_without_a_speed_keeps_the_mode_speed_of_the_capabilities(physics, physics_engine):
    caps = CharacterCapabilities(walkSpeed=1.5, runSpeed=6.0)
    me = standing(physics, capabilities=caps)
    me.set_move((1, 0, 0), speed=4.5)
    me.set_move((1, 0, 0), mode='run')
    frames(physics, 0.5)
    assert me.velocity[0] == pytest.approx(6.0, abs=VELOCITY[physics_engine])
    assert me.speed == 6.0
    assert caps.runSpeed == 6.0 and caps.walkSpeed == 1.5        # the capabilities are not changed


def test_speed_is_settable_and_none_gives_the_mode_back(physics, physics_engine):
    me = standing(physics, capabilities=CharacterCapabilities(walkSpeed=1.5))
    me.set_move((0, 0, -1))
    me.speed = 2.25
    frames(physics, 0.5)
    assert me.velocity[2] == pytest.approx(-2.25, abs=VELOCITY[physics_engine])
    me.speed = None
    frames(physics, 0.5)
    assert me.velocity[2] == pytest.approx(-1.5, abs=VELOCITY[physics_engine])
    assert me.speed == 1.5


def test_a_speed_that_is_not_a_finite_number_at_or_above_zero_is_refused(physics, physics_engine):
    me = standing(physics)
    for bad in (-1.0, float('nan'), float('inf')):
        with pytest.raises(ValueError, match='speed'):
            me.set_move((1, 0, 0), speed=bad)
        with pytest.raises(ValueError, match='speed'):
            me.speed = bad
        with pytest.raises(ValueError, match='speed'):
            me.run_along(straight(), speed=bad)


def test_a_speed_function_that_answers_a_bad_speed_is_refused_at_the_step(physics, physics_engine):
    me = standing(physics)
    me.run_along(straight(), speed=lambda seconds: 3.0 if seconds < 0.25 else -1.0)
    frames(physics, 0.2)
    assert me.speed == 3.0
    with pytest.raises(ValueError, match='speed'):
        me.step(0.1)
        me.step(0.1)


def straight(length=400.0):
    return RoadCourse(np.array([(0.0, 0.0, 0.0), (0.0, 0.0, -length / 2), (0.0, 0.0, -length)]))


def test_run_along_at_a_number_runs_the_course_at_that_speed(physics, physics_engine):
    me = standing(physics)
    me.run_along(straight(), speed=7.0)
    frames(physics, 1.0)
    assert me.velocity[2] == pytest.approx(-7.0, abs=VELOCITY[physics_engine])
    assert me.position[2] == pytest.approx(-7.0, abs=1e-6)


def test_run_along_at_a_function_of_time_follows_it(physics, physics_engine):
    me = standing(physics)
    me.run_along(straight(), speed=lambda seconds: 2.0 + seconds)
    frames(physics, 2.0)
    # Each 1/120 s step goes at the speed at its start: 240 steps, sum of 2 + n/120.
    expected = sum((2.0 + n * STEP) * STEP for n in range(240))
    assert me.position[2] == pytest.approx(-expected, abs=1e-6)
    assert me.speed == pytest.approx(2.0 + 239 * STEP)


def test_run_along_leaves_the_capabilities_alone(physics, physics_engine):
    caps = CharacterCapabilities(runSpeed=6.0)
    me = standing(physics, capabilities=caps)
    me.run_along(straight(), speed=9.0)
    frames(physics, 0.5)
    assert caps.runSpeed == 6.0


def test_run_along_on_a_lane_holds_the_lateral_offset_and_hops(physics, physics_engine):
    me = standing(physics)
    me.run_along(straight(), speed=5.0, lane=1.5)
    frames(physics, 1.5)
    assert me.position[0] == pytest.approx(1.5, abs=1e-3)
    assert me.lane == 1.5
    me.hop_to(-1.5, over=0.25)
    frames(physics, 1.0)
    assert me.position[0] == pytest.approx(-1.5, abs=1e-3)
    assert me.lane == -1.5
    assert me.velocity[2] == pytest.approx(-5.0, abs=1e-6)


def test_lane_without_a_course_is_none(physics, physics_engine):
    me = standing(physics)
    assert me.lane is None
