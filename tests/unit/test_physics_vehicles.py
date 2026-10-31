"""Vehicles through the physics service: settings, inputs, reads, blows and removal."""
import dataclasses
import inspect
import math
import typing

import numpy as np
import pytest

from OpenGLContext.physics import Physics, PhysicsDefinition, Proxy
from OpenGLContext.physics.callbacks import physics_callback
from OpenGLContext.physics.vehicles import (
    TARMAC, CarTuning, Impact, Surface, Vehicle, VehicleSettings, VehicleState, Wheel, WheelState,
    car_wheels,
)

pj = pytest.importorskip('pyjoltphysics')

MASS = 1180.0
TICK_HZ = 120.0
FRAME = 1.0 / 60.0


def car_settings(**changes):
    tuning = CarTuning(engine_force=20000.0, brake_force=16000.0, maximum_steer=0.52,
                       steer_speed=3.2, rolling_resistance=0.02, downforce=6.0,
                       steer_falloff_speed=10.0, base_speed=21.0, drag=0.9)
    wheels = car_wheels(wheelbase=2.55, track=1.70, height=-0.16, drive='rear', radius=0.33,
                        suspension_travel=0.22, suspension_stiffness=26.0,
                        suspension_damping=0.55, grip=1.9)
    return VehicleSettings.from_tuning(tuning, wheels, MASS, **changes)


def make_service(mode='inline'):
    physics = Physics(PhysicsDefinition(mode=mode, tickHz=TICK_HZ, maxCatchUp=0.25))
    physics.gravity = (0.0, -9.81, 0.0)
    return physics


@pytest.fixture
def physics():
    service = make_service()
    yield service
    service.close()


def add_ground(physics, material=None):
    options = {} if material is None else {'material': material}
    return physics.add_static(None, Proxy.box((400.0, 1.0, 400.0)), translation=(0.0, -0.5, 0.0),
                              **options)


def add_car(physics, position=(0.0, 0.8, 0.0), **changes):
    chassis = physics.add_dynamic(None, Proxy.box((1.85, 0.62, 4.2)), mass=MASS,
                                  angular_damping=0.4, translation=position)
    return physics.add_vehicle(chassis, car_settings(**changes))


def run(physics, seconds):
    for _ in range(int(round(seconds / FRAME))):
        physics.frame(FRAME)


def heading_of(body):
    """The chassis's turn about +Y from -Z, in radians, positive to the left."""
    x, y, z, w = (float(v) for v in body.physics.poses([body]).orientation[0])
    forward = np.array([-2.0 * (x * z + w * y), -2.0 * (y * z - w * x),
                        -(1.0 - 2.0 * (x * x + y * y))])
    return math.atan2(-forward[0], -forward[2])


# -- settings ------------------------------------------------------------------

def test_the_settings_have_pyjoltphysics_field_names():
    """The service hands its settings to pyjoltphysics by name, so the names are the same."""
    ours = {f.name for f in dataclasses.fields(VehicleSettings)}
    theirs = {f.name for f in dataclasses.fields(pj.VehicleSettings)}
    assert ours == theirs
    assert {f.name for f in dataclasses.fields(Wheel)} == {
        f.name for f in dataclasses.fields(pj.WheelSettings)}


def test_settings_survive_a_round_trip_through_builtin_types():
    settings = car_settings()
    plain = settings.as_dict()
    assert isinstance(plain['wheels'][0], dict) and plain['kind'] == 'wheeled'
    assert VehicleSettings.from_dict(plain) == settings


def test_a_tuning_maps_as_pyjoltphysics_maps_a_raycast_vehicle():
    tuning = CarTuning(engine_force=9000.0, base_speed=15.0, drag=0.5)
    wheels = car_wheels()
    ours = VehicleSettings.from_tuning(tuning, wheels, 1000.0)
    theirs = pj.VehicleSettings.from_raycast(tuning, wheels, 1000.0)
    assert ours.engine.max_torque == pytest.approx(theirs.engine.max_torque)
    assert [w.stiffness for w in ours.wheels] == pytest.approx([w.stiffness for w in theirs.wheels])
    assert ours.max_steer == tuning.maximum_steer and ours.cast == 'ray'
    assert VehicleSettings.from_tuning(tuning, wheels, 1000.0, drag=2.0).drag == 2.0


def test_settings_refuse_what_no_vehicle_can_be():
    with pytest.raises(ValueError, match='at least one wheel'):
        VehicleSettings(wheels=())
    with pytest.raises(ValueError, match='kind'):
        VehicleSettings(wheels=(Wheel((0, 0, 0)),), kind='hovercraft')
    with pytest.raises(ValueError, match='cast'):
        VehicleSettings(wheels=(Wheel((0, 0, 0)),), cast='laser')
    with pytest.raises(ValueError, match='tracks'):
        VehicleSettings(wheels=(Wheel((0, 0, 0)),), kind='tracked')


def test_the_wheelbase_and_the_lock_follow_the_settings():
    settings = car_settings()
    assert settings.wheelbase() == pytest.approx(2.55)
    assert settings.steer_lock(0.0) == pytest.approx(0.52)
    assert settings.steer_lock(10.0) == pytest.approx(0.26)
    assert dataclasses.replace(settings, steer_falloff_speed=0.0).steer_lock(50.0) == 0.52


def test_a_tuning_answers_its_forces_and_lock():
    tuning = CarTuning(engine_force=1000.0, base_speed=10.0, drag=2.0, maximum_steer=0.5,
                       steer_falloff_speed=0.0)
    assert tuning.drive_force(5.0) == 1000.0 and tuning.drive_force(20.0) == 500.0
    assert tuning.drag_force(3.0) == 18.0
    assert tuning.steer_lock(40.0) == 0.5
    assert CarTuning(steer_falloff_speed=30.0, maximum_steer=0.6).steer_lock(30.0) == pytest.approx(0.3)


def test_car_wheels_put_the_steered_pair_in_front():
    wheels = car_wheels(wheelbase=2.0, track=1.0, drive='front', radius=0.4)
    assert [w.steering for w in wheels] == [True, True, False, False]
    assert [w.driven for w in wheels] == [True, True, False, False]
    assert wheels[0].position == (-0.5, -0.1, -1.0) and wheels[0].radius == 0.4
    assert all(w.driven for w in car_wheels(drive='all'))
    with pytest.raises(ValueError, match='drive'):
        car_wheels(drive='sideways')


# -- driving -------------------------------------------------------------------

def test_a_car_settles_on_its_four_wheels(physics):
    add_ground(physics, material='rubber')
    car = add_car(physics)
    run(physics, 1.5)
    state = car.state()
    assert isinstance(state, VehicleState) and len(state.wheels) == 4
    assert all(isinstance(wheel, WheelState) for wheel in state.wheels)
    assert car.grounded and all(wheel.grounded for wheel in state.wheels)
    assert sum(wheel.load for wheel in state.wheels) == pytest.approx(MASS * 9.81, rel=0.05)
    assert all(0.0 < wheel.compression < 0.22 for wheel in state.wheels)
    assert state.wheels[0].material == 'rubber'
    assert state.wheels[0].ground is not None and state.wheels[0].ground.kind == 'static'
    assert abs(state.speed) < 0.1 and abs(car.chassis.velocity[1]) < 0.1


def test_throttle_drives_the_car_forward_in_first_gear(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 1.0)
    car.set_input(throttle=1.0)
    run(physics, 2.0)
    assert car.forward_speed > 15.0 and car.gear == 1 and car.rpm > 0.0
    assert car.chassis.position[2] < -10.0                    # -Z is forward
    assert car.speed == pytest.approx(car.forward_speed, rel=0.05)


def test_a_negative_throttle_reverses(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 1.0)
    car.set_input(throttle=-1.0)
    run(physics, 1.5)
    assert car.forward_speed < -2.0 and car.gear == -1


def test_steering_left_turns_the_car_left(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 1.0)
    car.set_input(throttle=0.4, steer=1.0)
    run(physics, 2.0)
    assert car.steer_angle > 0.05
    assert heading_of(car.chassis) > 0.3
    steered = [wheel.steer for wheel in car.wheels[:2]]
    assert all(angle > 0.05 for angle in steered) and car.wheels[2].steer == 0.0


def test_the_brake_stops_a_moving_car(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 1.0)
    car.set_input(throttle=1.0)
    run(physics, 1.5)
    assert car.forward_speed > 10.0
    car.set_input(brake=1.0)
    run(physics, 3.0)
    assert abs(car.forward_speed) < 0.3


def test_inputs_are_clamped_and_must_be_finite(physics):
    add_ground(physics)
    car = add_car(physics)
    car.set_input(throttle=3.0, steer=-4.0, brake=-1.0, handbrake=2.0)
    assert (car.throttle, car.steer, car.brake, car.handbrake) == (1.0, -1.0, 0.0, 1.0)
    with pytest.raises(ValueError):
        car.set_input(throttle=float('nan'))


# -- when inputs land ------------------------------------------------------------

def test_a_frame_s_inputs_apply_at_its_first_tick(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    car.set_input(throttle=0.7, steer=0.25)
    physics.frame(1.0 / TICK_HZ)                                  # exactly one tick
    state = car.state()
    assert (state.throttle, state.steer) == pytest.approx((0.7, 0.25))


def test_every_vehicle_s_inputs_reach_the_world_in_one_batch(physics):
    add_ground(physics)
    cars = [add_car(physics, position=(x, 0.8, 0.0)) for x in (-5.0, 0.0, 5.0)]
    run(physics, 0.2)
    world = physics._engine.world
    calls = []
    sent = world.vehicle_inputs

    def counted(ids, values, at_tick=0):
        calls.append(len(ids))
        return sent(ids, values, at_tick)

    world.vehicle_inputs = counted
    try:
        for car in cars:
            car.set_input(throttle=0.5)
        physics.frame(FRAME)
    finally:
        del world.vehicle_inputs
    assert calls == [3]


def test_inputs_given_in_a_before_step_handler_apply_at_that_tick(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    seen = []

    @physics_callback
    def drive(step):
        car.set_input(throttle=(step.index % 7) / 10.0)

    @physics_callback
    def read(step):
        seen.append((step.index, car.state().throttle, car.state().step))

    handlers = [physics.addEventHandler('before-step', drive),
                physics.addEventHandler('after-step', read)]
    run(physics, 0.1)
    for handler in handlers:
        handler.cancel()
    assert len(seen) >= 10
    for index, throttle, step in seen:
        assert step == index + 1
        assert throttle == pytest.approx((index % 7) / 10.0)


def test_a_free_running_world_takes_inputs_too():
    physics = make_service('thread')
    try:
        add_ground(physics)
        car = add_car(physics)
        car.set_input(throttle=1.0)
        import time
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and car.forward_speed < 2.0:
            physics.frame(FRAME)
            time.sleep(0.01)
        assert car.forward_speed > 2.0
    finally:
        physics.close()


# -- the ground under the wheels --------------------------------------------------

def test_a_surface_reaches_the_wheels_and_is_sent_once(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    world = physics._engine.world
    calls = []
    sent = world.set_vehicle_surfaces

    def counted(*args, **kw):
        calls.append(args)
        return sent(*args, **kw)

    world.set_vehicle_surfaces = counted
    try:
        for _ in range(5):
            car.set_surface(Surface(grip=0.3, rolling=0.2))
            physics.frame(FRAME)
        car.set_surface(Surface(grip=0.6), wheel=2)
        car.set_surface(Surface(grip=0.6), wheel=2)
        physics.frame(FRAME)
    finally:
        del world.set_vehicle_surfaces
    assert len(calls) == 2
    grips = [wheel.grip for wheel in car.wheels]
    assert grips == pytest.approx([0.3, 0.3, 0.6, 0.3])
    car.set_surface(TARMAC)
    physics.frame(FRAME)
    assert [wheel.grip for wheel in car.wheels] == pytest.approx([1.0] * 4)
    with pytest.raises(IndexError):
        car.set_surface(TARMAC, wheel=4)


def test_low_grip_slows_the_launch(physics):
    add_ground(physics)
    grippy, slippery = add_car(physics, position=(-6, 0.8, 0)), add_car(physics, position=(6, 0.8, 0))
    run(physics, 1.0)
    slippery.set_surface(Surface(grip=0.2))
    for car in (grippy, slippery):
        car.set_input(throttle=1.0)
    run(physics, 1.5)
    assert slippery.forward_speed < 0.5 * grippy.forward_speed
    assert max(abs(w.slip_ratio) for w in slippery.wheels) > max(abs(w.slip_ratio) for w in grippy.wheels)


# -- blows ----------------------------------------------------------------------

def test_a_wall_is_the_heaviest_blow_and_a_crash(physics):
    add_ground(physics)
    wall = physics.add_static(None, Proxy.box((20.0, 4.0, 1.0)), translation=(0.0, 2.0, -40.0))
    other = physics.add_static(None, Proxy.box((1.0, 1.0, 1.0)), translation=(30.0, 0.5, 0.0))
    car = add_car(physics)
    crashes, blows = [], []

    @physics_callback
    def watch(step):
        found = car.impact(above=1.0)
        if found is not None:
            blows.append(found)

    def crashed(collision):
        crashes.append(collision)

    handler = physics.addEventHandler('after-step', watch)
    car.addEventHandler('crash', crashed, other=wall)
    run(physics, 1.0)
    car.set_input(throttle=1.0)
    run(physics, 4.0)
    handler.cancel()
    assert blows and isinstance(blows[0], Impact)
    heaviest = max(blows, key=lambda blow: blow.closing)
    assert heaviest.body is wall and heaviest.closing > 10.0 and heaviest.impulse > 0.0
    assert crashes and crashes[0].body is car.chassis and crashes[0].other is wall
    assert crashes[0].approach > 10.0
    assert car.impact(among=[other]) is None


def test_the_impact_event_names_the_vehicle_s_chassis(physics):
    add_ground(physics)
    post = physics.add_dynamic(None, Proxy.box((0.4, 1.0, 0.4)), mass=20.0,
                               translation=(0.0, 0.5, -15.0))
    car = add_car(physics, impact_speed=1.0, crash_speed=50.0)
    impacts = []

    def struck(collision):
        impacts.append(collision)

    car.addEventHandler('impact', struck)
    run(physics, 1.0)
    car.set_input(throttle=0.6)
    run(physics, 2.5)
    struck = [hit for hit in impacts if hit.other is post]
    assert struck and struck[0].body is car.chassis and struck[0].kind == 'vehicle'
    with pytest.raises(ValueError):
        car.addEventHandler('hit', struck)


# -- placing and removing ---------------------------------------------------------

def test_place_stops_the_car_where_it_is_put(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 1.0)
    car.set_input(throttle=1.0)
    run(physics, 1.0)
    car.place((10.0, 0.8, 5.0), heading=math.pi / 2)
    car.set_input()
    run(physics, 1.0)
    assert np.allclose(car.chassis.position[[0, 2]], (10.0, 5.0), atol=0.3)
    assert heading_of(car.chassis) == pytest.approx(math.pi / 2, abs=0.05)
    assert car.speed < 0.3


def test_removing_the_vehicle_leaves_the_chassis(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    car.remove()
    car.remove()
    run(physics, 0.2)
    assert not car.alive and car.chassis.alive
    assert car.wheels == () and car.forward_speed == 0.0 and car.impact() is None
    with pytest.raises(ValueError):
        car.state()
    assert physics._engine.world.stats()['vehicles'] == 0
    assert car not in physics.vehicles


def test_removing_the_chassis_removes_the_vehicle(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    car.chassis.remove()
    run(physics, 0.2)
    assert not car.alive and physics.vehicles == ()
    car.set_input(throttle=1.0)                                   # harmless once removed


def test_a_vehicle_needs_a_dynamic_chassis(physics):
    ground = add_ground(physics)
    with pytest.raises(ValueError, match='dynamic'):
        physics.add_vehicle(ground, car_settings())


def test_a_vehicle_reads_nothing_before_its_first_tick(physics):
    add_ground(physics)
    car = add_car(physics)
    assert car.wheels == () and car.speed == 0.0 and car.rpm == 0.0 and car.gear == 0
    assert car.steer_angle == 0.0 and not car.grounded
    assert 'Vehicle' in repr(car)


# -- no engine type crosses the API ----------------------------------------------

def _mentions_engine(annotation):
    if isinstance(annotation, str):
        return 'pyjoltphysics' in annotation or 'pj.' in annotation
    module = getattr(annotation, '__module__', '') or ''
    if module.startswith('pyjoltphysics'):
        return True
    return any(_mentions_engine(arg) for arg in typing.get_args(annotation))


def test_no_vehicle_signature_names_a_pyjoltphysics_type():
    for name, member in inspect.getmembers(Vehicle):
        if name.startswith('_'):
            continue
        function = member.fget if isinstance(member, property) else member
        if not callable(function):
            continue
        signature = inspect.signature(function)
        assert not _mentions_engine(signature.return_annotation), name
        for parameter in signature.parameters.values():
            assert not _mentions_engine(parameter.annotation), (name, parameter.name)


def test_no_vehicle_read_is_a_pyjoltphysics_object(physics):
    add_ground(physics)
    car = add_car(physics)
    run(physics, 0.5)
    state = car.state()
    values = [getattr(owner, field.name) for owner in (state, state.wheels[0])
              for field in dataclasses.fields(owner)]
    for value in values:
        assert not (type(value).__module__ or '').startswith('pyjoltphysics'), value
    assert all(isinstance(wheel.position, np.ndarray) for wheel in state.wheels)
