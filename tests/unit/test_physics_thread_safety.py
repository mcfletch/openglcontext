"""The Jolt engine's tables under a free-running world: the world thread and the render thread at once.

In thread mode a command made on the world thread (``Physics.post``, an
``on_step`` function, a physics-thread handler) changes the engine's tables
there, while the render thread's frame reads the same tables. Each test
runs one such pattern for :data:`SECONDS` and asserts that no frame raises
and the world never stops.
"""
import time

import numpy as np
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.ragdolls import RagdollSpec
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.vehicles import CarTuning, VehicleSettings, car_wheels

pytest.importorskip('pyjoltphysics')

#: Seconds each pattern runs for.
SECONDS = 5.0
FRAME = 1.0 / 60.0


def make(tick_hz=1000.0) -> Physics:
    return Physics(PhysicsDefinition(mode='thread', tickHz=tick_hz, maxCatchUp=2.0,
                                     gravity=(0.0, 0.0, 0.0)))


def spheres(physics, count, radius=0.1):
    shape = Proxy.sphere(radius)
    return [physics.add_dynamic(None, proxy=shape, translation=(i % 100, i // 100, 0), mass=1.0)
            for i in range(count)]


def car(physics, x):
    tuning = CarTuning(engine_force=20000.0, brake_force=16000.0, maximum_steer=0.52)
    wheels = car_wheels(wheelbase=2.55, track=1.70, height=-0.16, radius=0.33)
    chassis = physics.add_dynamic(None, Proxy.box((1.85, 0.62, 4.2)), mass=1180.0,
                                  translation=(x, 0.8, 0.0))
    return physics.add_vehicle(chassis, VehicleSettings.from_tuning(tuning, wheels, 1180.0))


def until(deadline):
    return time.monotonic() < deadline


def test_bodies_removed_on_the_world_thread_leave_the_frame_whole():
    physics = make()
    try:
        bodies = spheres(physics, 3000)
        for body in bodies:
            physics.add_hinge(body, None, anchor=tuple(body.position), axis=(0, 0, 1))
            body.set_angular_velocity((0, 0, 1))
        physics.frame(FRAME)
        waiting = list(bodies)
        deadline = time.monotonic() + SECONDS
        while until(deadline) and waiting:
            for _ in range(5):
                if waiting:
                    physics.post(waiting.pop().remove)
            physics.frame(FRAME)
            assert physics.error is None
    finally:
        physics.close()


def test_vehicles_removed_on_the_world_thread_leave_the_frame_whole():
    physics = make(tick_hz=500.0)
    try:
        physics.add_static(None, Proxy.box((4000.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
        doomed = []

        def remove_one(view):
            if doomed:
                doomed.pop().chassis.remove()

        physics.on_step(remove_one)
        deadline = time.monotonic() + SECONDS
        x = 0.0
        while until(deadline):
            for _ in range(4):
                made = car(physics, x)
                made.set_input(throttle=1.0)
                doomed.append(made)
                x += 5.0
            for vehicle in physics.vehicles:
                vehicle.set_input(throttle=0.5)
            physics.frame(FRAME)
            assert physics.error is None
    finally:
        physics.close()


def test_ragdolls_removed_on_the_world_thread_leave_the_frame_whole():
    physics = make(tick_hz=500.0)
    try:
        spec = RagdollSpec.humanoid()
        deadline = time.monotonic() + SECONDS
        x = 0.0
        while until(deadline):
            for _ in range(2):
                made = physics.add_ragdoll(spec, position=(x, 2.0, 0.0))
                made.bones[0].set_force((0.0, 1.0, 0.0))
                physics.post(made.remove)
                x += 2.0
            physics.frame(FRAME)
            assert physics.error is None
    finally:
        physics.close()


def test_static_instances_removed_on_the_world_thread_leave_the_overlay_whole():
    physics = Physics(PhysicsDefinition(mode='thread', tickHz=1000.0, maxCatchUp=2.0,
                                        gravity=(0.0, 0.0, 0.0)),
                      mount=lambda node, on: None)
    try:
        spheres(physics, 10)
        physics.show_proxies(True)
        post = Proxy.box((0.2, 2.0, 0.2))
        deadline = time.monotonic() + SECONDS
        while until(deadline):
            for _ in range(20):
                made = physics.add_static_instances(post, np.random.default_rng(1).random((4, 3)))
                physics.post(made.remove)
            physics.frame(FRAME)
            assert physics.error is None
    finally:
        physics.close()


def test_standing_forces_changed_on_the_render_thread_leave_the_world_running():
    physics = make(tick_hz=500.0)
    try:
        bodies = spheres(physics, 5000)
        for body in bodies[:-1]:
            body.set_force((0.0, 1e-6, 0.0))
        last = bodies[-1]
        deadline = time.monotonic() + SECONDS
        toggles = 0
        while until(deadline) and physics.error is None:
            last.set_force((0.0, 1.0, 0.0))
            last.set_force((0.0, 0.0, 0.0))
            toggles += 1
            if toggles % 2000 == 0:
                physics.frame(FRAME)
        assert physics.error is None
        physics.frame(FRAME)
    finally:
        physics.close()


def test_the_switch_interval_is_short_while_any_holder_holds_it():
    import sys

    from OpenGLContext.physics.joltengine import _SwitchInterval

    start = sys.getswitchinterval()
    shared = _SwitchInterval()
    sys.setswitchinterval(0.005)
    try:
        shared.hold()
        assert sys.getswitchinterval() == pytest.approx(0.001)
        shared.hold()
        shared.release()
        assert sys.getswitchinterval() == pytest.approx(0.001)
        shared.release()
        assert sys.getswitchinterval() == pytest.approx(0.005)
    finally:
        sys.setswitchinterval(start)


def test_two_services_with_world_callbacks_leave_the_switch_interval_as_they_found_it():
    import sys

    before = sys.getswitchinterval()

    def service():
        physics = Physics(PhysicsDefinition(mode='thread'))
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.5), mass=1.0)
        body.set_force((0.0, 1.0, 0.0))     # a standing force registers a world callback
        physics.frame(FRAME)
        return physics

    first = service()
    second = service()
    assert sys.getswitchinterval() <= 0.001
    first.close()
    assert sys.getswitchinterval() <= 0.001
    second.close()
    assert sys.getswitchinterval() == before


def test_a_service_closed_on_the_world_thread_stops_its_world():
    physics = make(tick_hz=200.0)
    try:
        spheres(physics, 3)[0].set_velocity((1.0, 0.0, 0.0))
        physics.on_step(lambda view: None)          # keeps the world ticking
        physics.frame(FRAME)
        physics.post(physics.close)
        deadline = time.monotonic() + 5.0
        while not physics.closed and time.monotonic() < deadline:
            time.sleep(0.01)
        assert physics.closed
        time.sleep(0.1)
        world = physics._engine.world
        tick = world.tick
        time.sleep(0.3)
        assert world.tick == tick
    finally:
        physics.close()


def test_a_lockstep_service_closed_inside_a_tick_ends_its_frame_quietly():
    physics = Physics(PhysicsDefinition(mode='inline', tickHz=60.0))
    try:
        physics.add_dynamic(None, proxy=Proxy.sphere(0.5), mass=1.0)
        physics.frame(FRAME)
        physics.post(physics.close)
        physics.frame(4 * FRAME)
        assert physics.closed
        assert physics.frame(FRAME) is False
    finally:
        physics.close()
