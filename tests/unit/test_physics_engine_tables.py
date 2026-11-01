"""What the Jolt engine holds for each body, and that removing the body lets it go.

The engine keeps a native shape per proxy and a row in its tables per body.
A game that spawns and removes bodies, swaps scenery or removes ragdolls
must end where it began.
"""
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.ragdolls import RagdollSpec
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition

pytest.importorskip('pyjoltphysics')

FRAME = 1.0 / 60.0


def make() -> Physics:
    return Physics(PhysicsDefinition(mode='inline', tickHz=60.0, maxCatchUp=2.0))


@pytest.fixture
def physics():
    service = make()
    service.add_static(None, proxy=Proxy.box((40.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
    service.frame(FRAME)
    yield service
    service.close()


def held(physics):
    """How much the engine holds: native shapes, and the size of each per-body table."""
    engine = physics._engine
    return {'world shapes': int(engine.world.stats()['shapes']), 'shapes': len(engine._shapes),
            'kinds': len(engine._kinds), 'poses': len(engine._poses), 'given': len(engine.given),
            'forces': len(engine._forces), 'torques': len(engine._torques),
            'joints': len(engine._joint_bodies), 'movers': len(engine._rows_full)}


def test_bodies_spawned_and_removed_leave_nothing_behind(physics):
    before = held(physics)
    for i in range(200):
        body = physics.add_dynamic(None, proxy=Proxy.sphere(0.1), translation=(i % 10, 5, 0),
                                   mass=1.0)
        body.set_force((0.0, 1.0, 0.0))
        physics.frame(FRAME)
        body.remove()
    physics.frame(FRAME)
    assert held(physics) == before


def test_scenery_swapped_leaves_nothing_behind(physics):
    before = held(physics)
    for swap in range(5):
        scene = [physics.add_static(None, proxy=Proxy.trimesh(
            [(0, 0, 0), (1, 0, 0), (0, 0, 1)], [(0, 1, 2)]), translation=(i, swap, 0))
            for i in range(20)]
        physics.frame(FRAME)
        for body in scene:
            body.remove()
        physics.frame(FRAME)
    assert held(physics) == before


def test_static_instances_removed_leave_nothing_behind(physics):
    before = held(physics)
    for _ in range(5):
        made = physics.add_static_instances(Proxy.box((0.2, 2.0, 0.2)),
                                            [(x, 1.0, 3.0) for x in range(30)])
        physics.frame(FRAME)
        made.remove()
        physics.frame(FRAME)
    assert held(physics) == before


def test_a_shape_two_bodies_share_stays_until_both_are_removed(physics):
    shared = Proxy.sphere(0.3)
    start = held(physics)['world shapes']
    first = physics.add_dynamic(None, proxy=shared, translation=(0, 3, 0), mass=1.0)
    second = physics.add_dynamic(None, proxy=shared, translation=(2, 3, 0), mass=1.0)
    physics.frame(FRAME)
    assert held(physics)['world shapes'] == start + 1
    first.remove()
    physics.frame(FRAME)
    assert held(physics)['world shapes'] == start + 1
    third = physics.add_dynamic(None, proxy=shared, translation=(4, 3, 0), mass=1.0)
    physics.frame(FRAME)
    assert held(physics)['world shapes'] == start + 1
    second.remove()
    third.remove()
    physics.frame(FRAME)
    assert held(physics)['world shapes'] == start


def test_ragdolls_removed_leave_nothing_behind(physics):
    engine = physics._engine
    spec = RagdollSpec.humanoid()
    # The first leaves its spec's bone shapes, kept for the next ragdoll of that spec.
    physics.add_ragdoll(spec).remove()
    physics.frame(FRAME)
    before = held(physics)
    for _ in range(5):
        doll = physics.add_ragdoll(spec, position=(0.0, 0.1, 0.0))
        physics.frame(FRAME)
        doll.bones[0].set_force((0.0, 10.0, 0.0))
        joint = physics.add_ball(doll.bones[2], None, anchor=(0.0, 2.0, 0.0))
        physics.frame(FRAME)
        doll.remove()
        physics.frame(FRAME)
        assert not joint.alive
    physics.frame(FRAME)
    assert held(physics) == before
    assert not engine._callbacks_set


def test_the_bone_shapes_of_specs_no_longer_kept_are_let_go(physics):
    start = held(physics)['world shapes']
    for height in range(1, 31):
        physics.add_ragdoll(RagdollSpec.humanoid(height=1.0 + 0.02 * height)).remove()
        physics.frame(FRAME)
    kept = physics._engine._ragdoll_made
    assert held(physics)['world shapes'] == start + sum(len(made[2].bones) for made in kept)


def test_a_vehicle_on_a_bone_goes_with_its_ragdoll(physics):
    from OpenGLContext.physics.vehicles import CarTuning, VehicleSettings, car_wheels

    doll = physics.add_ragdoll(RagdollSpec.humanoid(), position=(0.0, 0.1, 0.0))
    physics.frame(FRAME)
    tuning = CarTuning(engine_force=2000.0, brake_force=1600.0, maximum_steer=0.5)
    wheels = car_wheels(wheelbase=0.4, track=0.3, height=-0.1, radius=0.1)
    vehicle = physics.add_vehicle(doll.bones[0], VehicleSettings.from_tuning(tuning, wheels, 10.0))
    physics.frame(FRAME)
    doll.remove()
    for _ in range(30):
        physics.frame(FRAME)
    assert not vehicle.alive
    assert physics.vehicles == ()
    assert len(physics._engine.vehicle_table) == 0
    assert int(physics._engine.world.stats()['vehicles']) == 0


def test_a_body_spawned_and_one_removed_a_frame_write_what_changed(check_scaling, monkeypatch):
    from OpenGLContext.physics import service as service_module
    from OpenGLContext.scenegraph.transform import Transform

    written = [0]
    write = service_module.write_poses

    def counted(nodes, positions, rotations):
        written[0] += len(nodes)
        return write(nodes, positions, rotations)

    monkeypatch.setattr(service_module, 'write_poses', counted)
    made = []

    def prepare(n):
        physics = Physics(PhysicsDefinition(mode='inline', tickHz=60.0, maxCatchUp=2.0,
                                            gravity=(0.0, 0.0, 0.0)))
        made.append(physics)
        shape = Proxy.sphere(0.2)
        for i in range(n):
            physics.add_dynamic(Transform(translation=(i % 100, i // 100, 0)), proxy=shape,
                                mass=1.0)
        for _ in range(90):     # long enough for the bodies to fall asleep
            physics.frame(FRAME)
        spawned = []

        def work():
            written[0] = 0
            for _ in range(10):
                spawned.append(physics.add_dynamic(Transform(translation=(0, 50, 0)),
                                                   proxy=shape, mass=1.0))
                if len(spawned) > 3:
                    spawned.pop(0).remove()
                physics.frame(FRAME)
            return written[0]
        return work

    try:
        check_scaling(prepare, n=500, most=1.5, measure='count')
    finally:
        for physics in made:
            physics.close()


def test_rows_emptied_by_removals_are_packed_and_the_rest_still_drawn(physics):
    from OpenGLContext.physics.joltengine import PACK_AFTER
    from OpenGLContext.scenegraph.transform import Transform

    shape = Proxy.sphere(0.1)
    nodes = [Transform(translation=(i % 50, 2 + i // 50, 0)) for i in range(PACK_AFTER + 200)]
    bodies = [physics.add_dynamic(node, proxy=shape, mass=1.0) for node in nodes]
    physics.frame(FRAME)
    layout = physics._engine._layout
    for body in bodies[:PACK_AFTER + 100]:
        body.remove()
    for _ in range(5):
        physics.frame(FRAME)
    assert physics._engine._layout == layout + 1
    assert len(physics._engine._movers) == 100
    for node, body in zip(nodes[-100:], bodies[-100:]):
        assert tuple(node.translation) == pytest.approx(tuple(body.position))
        assert node.translation[1] < 2 + (PACK_AFTER + 200) // 50


def test_adds_past_max_bodies_are_refused_on_the_callers_thread():
    physics = Physics(PhysicsDefinition(mode='inline', tickHz=60.0, maxBodies=50))
    try:
        with pytest.raises(ValueError, match='maxBodies'):
            physics.add_static_instances(Proxy.box((0.2, 2.0, 0.2)), [(x, 0, 0) for x in range(51)])
        posts = physics.add_static_instances(Proxy.box((0.2, 2.0, 0.2)),
                                             [(x, 0, 0) for x in range(40)])
        shape = Proxy.sphere(0.1)
        kept = [physics.add_dynamic(None, proxy=shape, translation=(i, 3, 0), mass=1.0)
                for i in range(10)]
        with pytest.raises(ValueError, match='maxBodies'):
            physics.add_dynamic(None, proxy=shape, translation=(0, 5, 0), mass=1.0)
        with pytest.raises(ValueError, match='maxBodies'):
            physics.add_ragdoll(RagdollSpec.humanoid())
        physics.frame(FRAME)
        assert physics.counts.bodies == 50
        posts.remove()
        kept[0].remove()
        physics.frame(FRAME)            # a removal makes room once the world applies it
        physics.add_ragdoll(RagdollSpec.humanoid())
        physics.frame(FRAME)
        assert physics.counts.bodies == 9 + 11
    finally:
        physics.close()


def test_max_bodies_is_a_positive_count():
    with pytest.raises(ValueError, match='maxBodies'):
        PhysicsDefinition(maxBodies=0).validate()
    assert PhysicsDefinition().maxBodies == 65536


def test_a_body_the_engine_cannot_make_is_dead(physics):
    body = physics.add_dynamic(None, proxy=Proxy.convex([(0, 0, 0), (1, 0, 0), (2, 0, 0)]),
                               mass=1.0)
    physics.frame(FRAME)
    assert not body.alive
    assert body not in physics._bodies.values()


def test_a_ragdoll_the_engine_cannot_make_is_dead(physics, monkeypatch):
    def refuse(*arguments, **named):
        raise ValueError('no room for a ragdoll')

    monkeypatch.setattr(physics._engine.world, 'add_ragdoll', refuse)
    doll = physics.add_ragdoll(RagdollSpec.humanoid())
    physics.frame(FRAME)
    assert not doll.alive
    assert not any(bone.alive for bone in doll.bones)
    assert physics.ragdolls == ()


def test_removed_bodies_stay_nameable_for_a_while_and_then_are_let_go(physics, monkeypatch):
    from OpenGLContext.physics import joltengine

    monkeypatch.setattr(joltengine, 'RETIRED_KEPT', 4)
    engine = physics._engine
    start = len(engine._svc)
    bodies = [physics.add_dynamic(None, proxy=Proxy.sphere(0.1), translation=(i, 3, 0), mass=1.0)
              for i in range(10)]
    physics.frame(FRAME)
    jolts = [engine.jolt_uid(body.uid) for body in bodies]
    for body in bodies:
        body.remove()
    physics.frame(FRAME)
    assert len(engine._retired) == 4 and len(engine._retired_kinds) == 4
    assert len(engine._svc) == start + 4
    assert [engine.service_uid(jolt) for jolt in jolts[-4:]] == [body.uid for body in bodies[-4:]]
    assert engine.service_uid(jolts[0]) is None


def test_a_body_removed_while_it_moves_leaves_the_frame_idle(physics):
    still = physics.add_dynamic(None, proxy=Proxy.sphere(0.2), translation=(0, 0.2, 0), mass=1.0)
    moving = physics.add_dynamic(None, proxy=Proxy.sphere(0.2), translation=(5, 3, 0), mass=1.0)
    moving.set_velocity((0.0, 0.0, 3.0))
    for _ in range(90):
        physics.frame(FRAME)
    moving.remove()
    for _ in range(5):
        physics.frame(FRAME)
    assert still.asleep
    assert physics.frame(FRAME) is False
