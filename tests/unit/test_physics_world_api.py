"""The world the physics service builds: ground, instances, driven bodies, materials, gravity zones."""
import numpy as np
import pytest
from omi_audio import synth

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.zones import Box, Sphere
from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.zone import Zone, ZoneGravity
from OpenGLContext.testing.audio import RecordingAudio

LOOK = PhysicalMaterial(baseColor=(0.5, 0.5, 0.5))


def block(size, at=(0, 0, 0)):
    return surfaces.shape(surfaces.block(size), LOOK, translation=at)


def ball(radius=0.5, at=(0, 3, 0)):
    return surfaces.shape(surfaces.sphere(radius), LOOK, translation=at)


def make(mode='inline') -> Physics:
    return Physics(PhysicsDefinition(mode=mode, maxCatchUp=2.0, tickHz=100.0))


def run_for(physics, seconds, frame=0.02, setup=None):
    for _ in range(int(round(seconds / frame))):
        if setup is not None:
            setup()
        physics.frame(frame)


class Slope:
    """Land that rises 0.3 m for each metre in x: a Ground, answering for arrays."""

    def sample(self, x, z):
        return 0.3 * np.asarray(x, dtype='d') + 0.0 * np.asarray(z, dtype='d')


@pytest.fixture
def physics():
    service = make()
    yield service
    service.close()


# -- ground ---------------------------------------------------------------

def test_a_ball_rolls_to_rest_against_the_surface_of_a_ground(physics):
    physics.add_ground(Slope(), extent=((-50, -50), (50, 50)))
    node = ball(0.5, at=(5.0, 4.0, 0.0))
    physics.add_dynamic(node, proxy='sphere', restitution=0.0, friction=0.9)
    run_for(physics, 1.5)
    x = node.translation[0]
    top = 0.3 * x
    along = (node.translation[1] - top) * np.cos(np.arctan(0.3))
    assert along == pytest.approx(0.5, abs=0.06)


def test_a_ground_answers_a_ray(physics):
    body = physics.add_ground(Slope(), extent=((-50, -50), (50, 50)))
    hit = physics.raycast((10, 20, 0), (0, -1, 0))
    assert hit.body is body
    assert hit.point[1] == pytest.approx(3.0, abs=0.02)


def test_a_ground_that_answers_normals_is_asked_for_them(physics):
    class Tilted(Slope):
        asked = 0

        def normal(self, x, z):
            Tilted.asked += 1
            shape = np.shape(x) + (3,)
            out = np.zeros(shape)
            out[..., 1] = 1.0
            return out

    physics.add_ground(Tilted(), extent=((-50, -50), (50, 50)))
    hit = physics.raycast((10, 20, 0), (0, -1, 0))
    assert hit.normal == pytest.approx((0.0, 1.0, 0.0))
    assert Tilted.asked > 0


def test_a_ground_is_a_static_body_found_by_the_object(physics):
    land = Slope()
    body = physics.add_ground(land, extent=((-50, -50), (50, 50)))
    assert body.kind == 'static' and physics.body_for(land) is body


def test_the_grounds_bounds_are_found_by_sampling_when_none_are_given(physics):
    body = physics.add_ground(Slope(), extent=((-10, -10), (10, 10)))
    assert body.proxy.shape.type == 'heightfield'


def test_a_ground_takes_the_material_it_is_given(physics):
    physics.materials.define('moss', friction=0.8, footstep='soft.ogg')
    body = physics.add_ground(Slope(), extent=((-50, -50), (50, 50)), material='moss')
    assert body.material == 'moss'


def test_a_ball_struck_on_a_ground_of_a_material_with_a_sound_plays_it():
    thud = synth.impact(0.2, seed=1)
    audio = RecordingAudio()
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      audio=lambda: audio)
    service.materials.define('moss', friction=0.8, restitution=0.0, sound=thud)
    service.add_ground(Slope(), extent=((-50, -50), (50, 50)), material='moss')
    service.add_dynamic(ball(0.5, at=(-10.0, 3.0, 0.0)), proxy='sphere', restitution=0.0)
    run_for(service, 1.5)
    assert len(audio.played(thud)) >= 1
    service.close()


def test_proxy_heightfield_wraps_a_grid_of_heights():
    proxy = Proxy.heightfield(heights=np.zeros((4, 4)), spacing=2.0)
    assert proxy.shape.type == 'heightfield'


# -- instances --------------------------------------------------------------

def test_many_trunks_with_one_shape_stop_a_ball(physics):
    trunk = Proxy.cylinder(height=6.0, radius=0.4)
    positions = np.array([[x * 5.0, 3.0, 0.0] for x in range(-20, 21)])
    trunks = physics.add_static_instances(trunk, positions)
    node = ball(0.3, at=(5.0, 9.0, 0.0))
    physics.add_dynamic(node, proxy='sphere', restitution=0.0)
    run_for(physics, 2.0)
    assert trunks.count == 41
    assert node.translation[1] == pytest.approx(6.0 + 0.3, abs=0.1)


def test_instances_are_removed_together(physics):
    trunks = physics.add_static_instances(Proxy.cylinder(6.0, 0.4), np.array([[0.0, 3.0, 0.0]]))
    trunks.remove()
    trunks.remove()
    assert physics.raycast((0, 20, 0), (0, -1, 0)) is None


def test_instances_with_no_positions_are_refused(physics):
    with pytest.raises(ValueError, match='positions'):
        physics.add_static_instances(Proxy.sphere(0.5), np.zeros((0, 3)))


# -- driven bodies -------------------------------------------------------------

def test_a_driven_body_follows_its_pose_and_carries_what_rests_on_it(physics):
    from OpenGLContext.physics.callbacks import physics_callback

    platform = block((6, 0.4, 6), at=(0, 0, 0))
    body = physics.add_kinematic(platform, proxy='box')

    @physics_callback
    def pose(time):
        return (time * 1.0, 0.0, 0.0), None

    body.drive(pose)
    cargo = block((0.5, 0.5, 0.5), at=(0, 0.45, 0))
    physics.add_dynamic(cargo, proxy='box', restitution=0.0, friction=1.0)
    run_for(physics, 2.0)
    assert platform.translation[0] == pytest.approx(2.0, abs=0.05)
    assert cargo.translation[0] > 1.5


def test_a_drive_function_must_be_marked(physics):
    body = physics.add_kinematic(block((1, 1, 1)), proxy='box')
    with pytest.raises(ValueError, match='physics_callback'):
        body.drive(lambda time: ((0.0, 0.0, 0.0), None))


def test_driving_a_body_that_is_not_kinematic_is_refused(physics):
    from OpenGLContext.physics.callbacks import physics_callback
    body = physics.add_dynamic(ball())

    @physics_callback
    def pose(time):
        return (0.0, 0.0, 0.0), None

    with pytest.raises(ValueError, match='kinematic'):
        body.drive(pose)


# -- materials --------------------------------------------------------------------

def test_a_defined_material_is_used_by_name(physics):
    physics.materials.define('mud', friction=0.9, restitution=0.0)
    body = physics.add_dynamic(ball(), material='mud')
    physics.worker.flush()
    runtime = physics.worker.runtime
    index = runtime.entry(body.uid).index
    material = runtime.world.material_for(int(runtime.world.collider_material[index]))
    assert material.staticFriction == pytest.approx(0.9) and material.restitution == 0.0


def test_a_material_pair_overrides_the_friction_between_the_two(physics):
    physics.materials.define('mud', friction=0.9)
    physics.materials.pair('mud', 'rubber', friction=1.2)
    physics.add_dynamic(ball(), material='mud')
    physics.add_dynamic(ball(at=(3, 3, 0)), material='rubber')
    physics.worker.flush()
    world = physics.worker.runtime.world
    assert len(world.pair_friction) == 1
    assert list(world.pair_friction.values())[0] == (1.2, 1.2)


def test_every_pair_of_a_grid_of_materials_keeps_its_own_friction(physics):
    grips = {('steel', 'stone'): 0.35, ('steel', 'ice'): 0.03,
             ('rubber', 'stone'): 0.9, ('rubber', 'ice'): 0.15}
    for name in ('steel', 'rubber', 'stone', 'ice'):
        physics.materials.define(name, friction=0.5)
    for (marble, surface), friction in grips.items():
        physics.materials.pair(marble, surface, friction=friction)
    bodies = {name: physics.add_dynamic(ball(at=(3 * n, 3, 0)), material=name)
              for n, name in enumerate(('steel', 'rubber', 'stone', 'ice'))}
    physics.worker.flush()
    world = physics.worker.runtime.world

    def material_of(name):
        return int(world.collider_material[physics.slot_of(bodies[name])])

    for (marble, surface), friction in grips.items():
        found = world.pair_friction_for(material_of(marble), material_of(surface))
        assert found == (friction, friction), (marble, surface)


def test_a_body_and_its_slot_in_the_world_name_each_other(physics):
    first = physics.add_dynamic(ball(), proxy='sphere')
    second = physics.add_dynamic(ball(at=(3, 3, 0)), proxy='sphere')
    world = physics.world
    assert physics.slot_of(first) != physics.slot_of(second)
    assert world.position[physics.slot_of(second)][0] == pytest.approx(3.0)
    assert physics.body_at(physics.slot_of(first)) is first
    assert physics.body_at(physics.slot_of(second)) is second


def test_a_slot_with_no_body_names_none(physics):
    assert physics.body_at(0) is None
    assert physics.body_at(99) is None


def test_materials_are_listed_and_can_be_read_back(physics):
    material = physics.materials.define('mud', friction=0.9, sound='squelch.ogg')
    assert 'mud' in physics.materials.names and 'rubber' in physics.materials.names
    assert physics.materials.get('mud') is material
    assert material.sound == 'squelch.ogg'


def test_an_unknown_material_is_refused_with_the_known_ones(physics):
    with pytest.raises(ValueError, match='rubber'):
        physics.add_dynamic(ball(), material='custard')


def test_a_material_with_a_sound_plays_it_where_a_body_lands():
    audio = RecordingAudio()
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      audio=lambda: audio)
    service.materials.define('stone', friction=0.6, restitution=0.0, sound='thud.ogg')
    service.add_static(block((20, 1, 20), at=(0, -0.5, 0)), proxy='box', material='stone')
    service.add_dynamic(ball(0.5, at=(0, 2, 0)), proxy='sphere', restitution=0.0)
    run_for(service, 1.0)
    plays = audio.played('thud.ogg')
    assert len(plays) == 1
    assert plays[0].at[1] == pytest.approx(0.0, abs=0.1)
    assert 0.0 < plays[0].gain <= 1.0
    service.close()


def test_a_material_sound_may_be_a_clip_the_script_made():
    thud = synth.impact(0.2, seed=1)
    audio = RecordingAudio()
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      audio=lambda: audio)
    service.materials.define('stone', friction=0.6, restitution=0.0, sound=thud)
    service.add_static(block((20, 1, 20), at=(0, -0.5, 0)), proxy='box', material='stone')
    service.add_dynamic(ball(0.5, at=(0, 2, 0)), proxy='sphere', restitution=0.0)
    run_for(service, 1.0)
    [play] = audio.played(thud)
    assert play.source is thud
    service.close()


def test_a_soft_touch_makes_no_sound():
    audio = RecordingAudio()
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0, tickHz=100.0),
                      audio=lambda: audio)
    service.materials.define('stone', friction=0.6, restitution=0.0, sound='thud.ogg')
    service.add_static(block((20, 1, 20), at=(0, -0.5, 0)), proxy='box', material='stone')
    service.add_dynamic(ball(0.5, at=(0, 0.505, 0)), proxy='sphere', restitution=0.0)
    run_for(service, 1.0)
    assert audio.played('thud.ogg') == []
    service.close()


# -- gravity zones ---------------------------------------------------------------------

def test_a_box_zone_changes_gravity_inside_it_only(physics):
    physics.gravity = (0, -9.81, 0)
    physics.add_gravity_zone(Box(center=(0, 3, 0), size=(4, 6, 4)), gravity=(0, 4.0, 0), replace=True)
    inside = ball(0.3, at=(0, 3, 0))
    outside = ball(0.3, at=(20, 3, 0))
    physics.add_dynamic(inside, proxy='sphere', linear_damping=0.0)
    physics.add_dynamic(outside, proxy='sphere', linear_damping=0.0)
    run_for(physics, 0.4)
    assert inside.translation[1] > 3.0
    assert outside.translation[1] < 3.0


def test_a_sphere_zone_pulls_toward_its_centre(physics):
    physics.gravity = (0, 0, 0)
    physics.add_gravity_zone(Sphere(center=(0, 0, 0), radius=20.0), gravity=6.0,
                             toward=(0, 0, 0))
    node = ball(0.3, at=(5, 0, 0))
    physics.add_dynamic(node, proxy='sphere', linear_damping=0.0)
    run_for(physics, 0.5)
    assert node.translation[0] < 5.0


def test_a_zone_node_in_the_scene_carries_gravity_to_the_world(physics):
    zone = Zone(size=(10, 10, 10), settings=[ZoneGravity(enabled=True, gravity=4.0,
                                                        direction=(0, 1, 0), replace=True)])
    from OpenGLContext.physics import zones as zones_module
    root = basenodes.sceneGraph(children=[zone])
    physics.zones_changed(zones_module.scene_zones(root))
    node = ball(0.3, at=(0, 0, 0))
    physics.add_dynamic(node, proxy='sphere', linear_damping=0.0)
    run_for(physics, 0.4)
    assert node.translation[1] > 0.1


def test_the_same_zones_are_not_sent_twice(physics):
    from OpenGLContext.physics import zones as zones_module
    root = basenodes.sceneGraph(children=[Zone(settings=[ZoneGravity(enabled=True)])])
    placed = zones_module.scene_zones(root)
    assert physics.zones_changed(placed) is True
    assert physics.zones_changed(placed) is False


# -- seeing the proxies ------------------------------------------------------------------

def test_show_proxies_mounts_an_overlay_and_removes_it():
    mounted = []
    service = Physics(PhysicsDefinition(mode='inline', maxCatchUp=2.0),
                      mount=lambda node, on: mounted.append((node, on)))
    service.add_dynamic(ball())
    service.show_proxies(True)
    assert mounted and mounted[0][1] is True
    service.frame(0.02)
    service.show_proxies(False)
    assert mounted[-1][1] is False and mounted[-1][0] is mounted[0][0]
    service.close()


# -- collider sources ------------------------------------------------------------------

class Stones:
    """A source of stones on a line, made as the focus nears them."""

    def __init__(self):
        self.updates = []
        self.have = set()
        self.proxy = Proxy.box((2.0, 2.0, 2.0))

    def update(self, focus):
        from OpenGLContext.physics.sources import Changes

        self.updates.append(tuple(focus))
        x = round(focus[0] / 10.0) * 10.0
        near = {x - 10.0, x, x + 10.0}
        added = [pos for pos in sorted(near) if ('stone', pos) not in self.have]
        gone = [key for key in sorted(self.have) if key[1] not in near]
        self.have |= {('stone', pos) for pos in added}
        self.have -= set(gone)
        return Changes(add=[(('stone', pos), self.proxy, (pos, 1.0, 0.0), None) for pos in added],
                       remove=gone)


def logged(caplog, message):
    """How many records carry an exception whose text has ``message``."""
    return sum(1 for record in caplog.records
               if record.exc_info and message in str(record.exc_info[1]))


class Broken:
    """A source whose update raises."""

    def __init__(self):
        self.calls = 0

    def update(self, focus):
        self.calls += 1
        raise ZeroDivisionError('the source divided by zero')


def test_a_source_that_raises_is_logged_once_and_the_frame_goes_on(physics, caplog):
    broken = Broken()
    stones = Stones()
    physics.add_collider_source(broken, focus=lambda: (0.0, 0.0, 0.0))
    physics.add_collider_source(stones, focus=lambda: (0.0, 0.0, 0.0))
    physics.frame(0.02)
    physics.frame(0.02)
    assert broken.calls == 2
    assert len(stones.updates) == 2
    assert logged(caplog, 'the source divided by zero') == 1


def test_a_character_whose_update_raises_is_logged_once_and_the_frame_goes_on(physics, caplog):
    physics.add_static(block((20, 1, 20), at=(0, -0.5, 0)))
    first = physics.add_character(position=(0, 0.05, 0))
    second = physics.add_character(position=(3, 0.05, 0))
    stepped = []

    def broken(dt):
        raise KeyError('the character lost its clip')

    first.update = broken
    real = second.update
    second.update = lambda dt: stepped.append(dt) or real(dt)
    physics.frame(0.02)
    physics.frame(0.02)
    assert len(stepped) == 2
    assert logged(caplog, 'the character lost its clip') == 1


def test_a_collider_source_adds_bodies_near_the_focus_and_drops_those_left_behind(physics):
    source = Stones()
    where = [0.0, 0.0, 0.0]
    physics.add_collider_source(source, focus=lambda: where)
    physics.frame(0.02)
    assert physics.raycast((0, 10, 0), (0, -1, 0)).distance == pytest.approx(8.0, abs=0.01)
    assert physics.raycast((30, 10, 0), (0, -1, 0)) is None
    where[0] = 30.0
    physics.frame(0.02)
    assert physics.raycast((30, 10, 0), (0, -1, 0)).distance == pytest.approx(8.0, abs=0.01)
    assert physics.raycast((0, 10, 0), (0, -1, 0)) is None


def test_a_source_is_asked_where_the_focus_is_each_frame(physics):
    source = Stones()
    physics.add_collider_source(source, focus=lambda: (1.0, 2.0, 3.0))
    physics.frame(0.02)
    physics.frame(0.02)
    assert source.updates == [(1.0, 2.0, 3.0), (1.0, 2.0, 3.0)]


def test_a_source_may_be_removed(physics):
    source = Stones()
    handle = physics.add_collider_source(source, focus=lambda: (0.0, 0.0, 0.0))
    physics.frame(0.02)
    handle.remove()
    handle.remove()
    assert physics.raycast((0, 10, 0), (0, -1, 0)) is None
    physics.frame(0.02)
    assert len(source.updates) == 1


def test_a_source_with_no_focus_follows_the_first_character(physics):
    # Between the stones the source makes, so the character is not pushed out of one.
    me = physics.add_character(position=(35.0, 0.05, 0.0))
    source = Stones()
    physics.add_collider_source(source)
    physics.frame(0.02)
    assert source.updates[0][0] == pytest.approx(me.position[0])


def test_a_source_with_no_focus_and_no_character_is_refused(physics):
    with pytest.raises(ValueError, match='focus'):
        physics.add_collider_source(Stones())
