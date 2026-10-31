"""Joints on the physics service: hinges, balls, sliders and distances between bodies and the world."""
import math
import time

import numpy as np
import pytest

from OpenGLContext.physics import Joint
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial

from OpenGLContext.testing import physics as physics_testing

pytestmark = pytest.mark.engines('omi', 'jolt')


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('tickHz', 120.0)
    named.setdefault('maxCatchUp', 2.0)
    return Physics(PhysicsDefinition(**named))


def run_for(physics: Physics, seconds: float, frame: float = 1.0 / 60.0) -> None:
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


def ball(physics, at, radius=0.2):
    return physics.add_dynamic(None, proxy=Proxy.sphere(radius), translation=at, mass=1.0)


def bar(physics, at, size=(2.0, 0.2, 0.2)):
    return physics.add_dynamic(None, proxy=Proxy.box(size), translation=at, mass=1.0)


def joints_in_world(physics):
    return [None] * physics_testing.joint_count(physics)


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


def test_a_hinge_to_the_world_holds_its_anchor_and_the_bar_swings_down(physics):
    rod = bar(physics, (1.0, 5.0, 0.0))
    hinge = physics.add_hinge(rod, anchor=(0.0, 5.0, 0.0), axis=(0, 0, 1))
    assert isinstance(hinge, Joint)
    assert hinge.kind == 'hinge' and hinge.body is rod and hinge.to is None
    lowest = 5.0
    for _ in range(90):
        run_for(physics, 1.0 / 60.0)
        tip = np.asarray(rod.position)
        assert np.linalg.norm(tip - (0.0, 5.0, 0.0)) == pytest.approx(1.0, abs=0.05)
        assert abs(tip[2]) < 0.02
        lowest = min(lowest, float(tip[1]))
    assert lowest < 4.2


def test_a_hinge_stops_at_its_limits(physics):
    rod = bar(physics, (1.0, 5.0, 0.0))
    physics.add_hinge(rod, anchor=(0.0, 5.0, 0.0), axis=(0, 0, 1), limits=(-0.5, 0.5))
    run_for(physics, 2.0)
    centre = np.asarray(rod.position) - (0.0, 5.0, 0.0)
    angle = math.atan2(centre[1], centre[0])
    assert angle == pytest.approx(-0.5, abs=0.08)


def test_a_hinge_motor_turns_the_body_at_its_speed(physics):
    physics.gravity = (0, 0, 0)
    rod = bar(physics, (0.0, 3.0, 0.0))
    physics.add_hinge(rod, anchor=(0.0, 3.0, 0.0), axis=(0, 1, 0), motor=(4.0, 50.0))
    run_for(physics, 0.5)
    assert float(rod.angular_velocity[1]) == pytest.approx(4.0, abs=0.2)
    assert np.allclose(rod.position, (0.0, 3.0, 0.0), atol=0.02)


def test_drive_changes_the_motor_of_a_joint_already_in_the_world(physics):
    physics.gravity = (0, 0, 0)
    rod = bar(physics, (0.0, 3.0, 0.0))
    hinge = physics.add_hinge(rod, anchor=(0.0, 3.0, 0.0), axis=(0, 1, 0), motor=(4.0, 50.0))
    assert hinge.motor == (4.0, 50.0)
    run_for(physics, 0.5)
    hinge.drive(-2.0, 50.0)
    assert hinge.motor == (-2.0, 50.0)
    run_for(physics, 0.5)
    assert float(rod.angular_velocity[1]) == pytest.approx(-2.0, abs=0.2)


def test_a_ball_joint_holds_two_bodies_at_a_point_between_them(physics):
    top = ball(physics, (0.0, 5.0, 0.0))
    physics.add_ball(top, anchor=(0.0, 5.5, 0.0))
    below = ball(physics, (0.0, 4.0, 0.0))
    physics.add_ball(below, top, anchor=(0.0, 4.5, 0.0))
    top.apply_impulse((2.0, 0.0, 0.0))
    run_for(physics, 2.0)
    assert np.linalg.norm(np.asarray(top.position) - (0.0, 5.5, 0.0)) == pytest.approx(0.5, abs=0.05)
    assert np.linalg.norm(np.asarray(below.position) - top.position) == pytest.approx(1.0, abs=0.08)


def test_a_distance_joint_keeps_a_pendulum_at_its_length(physics):
    bob = ball(physics, (2.0, 6.0, 0.0))
    link = physics.add_distance(bob, to_anchor=(0.0, 6.0, 0.0))
    assert link.kind == 'distance'
    lowest = 6.0
    for _ in range(120):
        run_for(physics, 1.0 / 60.0)
        assert np.linalg.norm(np.asarray(bob.position) - (0.0, 6.0, 0.0)) == pytest.approx(
            2.0, abs=0.1)
        lowest = min(lowest, float(bob.position[1]))
    assert lowest < 4.5


def test_a_distance_joint_takes_the_length_it_is_given(physics):
    bob = ball(physics, (2.0, 6.0, 0.0))
    physics.add_distance(bob, to_anchor=(0.0, 6.0, 0.0), length=1.0)
    run_for(physics, 2.0)
    assert np.linalg.norm(np.asarray(bob.position) - (0.0, 6.0, 0.0)) == pytest.approx(
        1.0, abs=0.1)


def test_a_slider_lets_the_body_move_along_its_axis_and_no_other_way(physics):
    block = bar(physics, (0.0, 2.0, 0.0), size=(0.5, 0.5, 0.5))
    physics.add_slider(block, axis=(1, 0, 0), motor=(1.5, 100.0))
    run_for(physics, 1.0)
    assert float(block.position[0]) == pytest.approx(1.5, abs=0.15)
    assert float(block.position[1]) == pytest.approx(2.0, abs=0.02)
    assert abs(float(block.position[2])) < 0.02


def test_a_slider_stops_at_its_limits(physics):
    block = bar(physics, (0.0, 2.0, 0.0), size=(0.5, 0.5, 0.5))
    physics.add_slider(block, axis=(1, 0, 0), limits=(-0.5, 0.5), motor=(2.0, 100.0))
    run_for(physics, 1.5)
    assert float(block.position[0]) == pytest.approx(0.5, abs=0.05)


def test_a_removed_joint_lets_its_body_fall(physics):
    bob = ball(physics, (1.0, 6.0, 0.0))
    hinge = physics.add_ball(bob, anchor=(0.0, 6.0, 0.0))
    run_for(physics, 0.5)
    hinge.remove()
    hinge.remove()
    assert not hinge.alive
    assert joints_in_world(physics) == []
    run_for(physics, 1.0)
    assert float(bob.position[1]) < 3.0


def test_removing_a_body_removes_its_joints(physics):
    top = ball(physics, (0.0, 5.0, 0.0))
    below = ball(physics, (0.0, 4.0, 0.0))
    held = physics.add_ball(top, anchor=(0.0, 5.5, 0.0))
    link = physics.add_ball(below, top, anchor=(0.0, 4.5, 0.0))
    run_for(physics, 0.2)
    top.remove()
    assert not held.alive and not link.alive
    assert joints_in_world(physics) == []
    link.drive(1.0, 1.0)
    link.remove()
    run_for(physics, 0.2)


def test_a_joint_names_its_bodies_by_their_nodes():
    physics = make()
    try:
        look = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
        node = surfaces.shape(surfaces.sphere(0.2), look, translation=(1.0, 6.0, 0.0))
        body = physics.add_dynamic(node, mass=1.0)
        hinge = physics.add_ball(node, anchor=(0.0, 6.0, 0.0))
        assert hinge.body is body
        run_for(physics, 1.0)
        assert np.linalg.norm(np.asarray(body.position) - (0.0, 6.0, 0.0)) == pytest.approx(
            1.0, abs=0.05)
    finally:
        physics.close()


def test_a_joint_to_something_not_in_the_world_is_refused(physics):
    look = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))
    stray = surfaces.shape(surfaces.sphere(0.2), look)
    with pytest.raises(ValueError, match='no body'):
        physics.add_ball(stray, anchor=(0, 0, 0))
    rod = bar(physics, (0, 1, 0))
    with pytest.raises(ValueError, match='itself'):
        physics.add_ball(rod, rod, anchor=(0, 1, 0))
    rod.remove()
    with pytest.raises(ValueError, match='removed'):
        physics.add_ball(rod, anchor=(0, 1, 0))
    with pytest.raises(ValueError, match='axis'):
        physics.add_hinge(bar(physics, (0, 1, 0)), anchor=(0, 1, 0), axis=(0, 0, 0))


def test_a_joint_works_on_the_physics_thread():
    physics = make(mode='thread')
    try:
        physics.gravity = (0, 0, 0)
        rod = bar(physics, (0.0, 3.0, 0.0))
        physics.add_hinge(rod, anchor=(0.0, 3.0, 0.0), axis=(0, 1, 0), motor=(3.0, 50.0))
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            physics.frame(1.0 / 60.0)
            if abs(float(rod.angular_velocity[1]) - 3.0) < 0.2:
                break
            time.sleep(0.01)
        assert float(rod.angular_velocity[1]) == pytest.approx(3.0, abs=0.2)
    finally:
        physics.close()


@pytest.mark.engines('omi', reason="the copy of the bodies characters step against is the omi engine's")
def test_the_characters_copy_of_the_world_is_made_with_joints_in_it(physics):
    rod = bar(physics, (1.0, 5.0, 0.0))
    physics.add_hinge(rod, anchor=(0.0, 5.0, 0.0), axis=(0, 0, 1))
    replica = physics._character_replica()
    assert rod.uid in replica
    run_for(physics, 0.5)
