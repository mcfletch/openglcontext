"""X3D's ParticleSystems component on the engine's particles; no GL.

`ParticleSystem`, the six emitters and the three physics models
(:mod:`OpenGLContext.scenegraph.x3dparticles`): what each emitter gives the
simulation, how a system emits, ages and stops on the engine's clock, what
each physics model does to it, how its colour and texture ramps and its
appearance become the look it is drawn with, and the bounds it reports.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.events import systemtime
from OpenGLContext.scenegraph import basenodes, particlesim
from OpenGLContext.scenegraph.x3dparticles import (
    BoundedPhysicsModel, ConeEmitter, ExplosionEmitter, ForcePhysicsModel, ParticleSystem,
    PointEmitter, PolylineEmitter, SurfaceEmitter, VolumeEmitter, WindPhysicsModel,
)
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.video.clock import FixedStepClock

CUBE = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
        (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
CUBE_FACES = [0, 3, 2, 1, -1, 4, 5, 6, 7, -1, 0, 1, 5, 4, -1,
              2, 3, 7, 6, -1, 1, 2, 6, 5, -1, 0, 4, 7, 3, -1]


@pytest.fixture
def clock():
    """The engine's clock, held still until a test moves it"""
    original = systemtime.timeSource()
    fixed = FixedStepClock(fps=60, start=0.0).install()
    try:
        yield fixed
    finally:
        systemtime.setTimeSource(original)


def run(system, seconds, step=1.0 / 60.0, start=0.0):
    """Advance ``system`` by ``seconds`` in frames of ``step``; the last time"""
    now = start
    system.advance(now)
    for _ in range(int(round(seconds / step))):
        now += step
        system.advance(now)
    return now


def sample(emitter, count=400, seed=2):
    return emitter.particleSource().sample(np.random.default_rng(seed), count)


class TestEmitters:
    def test_a_point_emitter_throws_from_its_position_along_its_direction(self):
        positions, directions = sample(PointEmitter(position=(1, 2, 3), direction=(0, 0, 1)))
        assert np.allclose(positions, (1, 2, 3))
        assert np.allclose(directions, (0, 0, 1))

    def test_a_cone_emitter_keeps_within_its_angle(self):
        _positions, directions = sample(ConeEmitter(direction=(0, 1, 0), angle=0.2))
        assert np.arccos(np.clip(directions[:, 1], -1, 1)).max() <= 0.2 + 1e-5

    def test_an_explosion_throws_every_way(self):
        positions, directions = sample(ExplosionEmitter(position=(0, 1, 0)))
        assert np.allclose(positions, (0, 1, 0))
        assert (directions[:, 0] < -0.5).any() and (directions[:, 0] > 0.5).any()

    def test_a_polyline_emitter_starts_particles_along_its_lines(self):
        emitter = PolylineEmitter(coord=basenodes.Coordinate(point=[(0, 0, 0), (2, 0, 0), (2, 2, 0)]),
                                  coordIndex=[0, 1, 2, -1], direction=(0, 0, 1))
        positions, directions = sample(emitter)
        assert np.all(np.isclose(positions[:, 1], 0) | np.isclose(positions[:, 0], 2))
        assert positions[:, 0].max() <= 2 + 1e-6 and positions[:, 1].max() <= 2 + 1e-6
        assert np.allclose(directions, (0, 0, 1))

    def test_a_polyline_without_indices_joins_its_points_in_order(self):
        emitter = PolylineEmitter(coord=basenodes.Coordinate(point=[(0, 0, 0), (1, 0, 0)]))
        positions, _directions = sample(emitter)
        assert np.allclose(positions[:, 1:], 0) and positions[:, 0].max() > 0.5

    def test_set_coordIndex_changes_the_lines(self):
        emitter = PolylineEmitter(coord=basenodes.Coordinate(
            point=[(0, 0, 0), (1, 0, 0), (0, 5, 0)]), coordIndex=[0, 1, -1])
        emitter.set_coordIndex = [0, 2, -1]
        positions, _directions = sample(emitter)
        assert np.allclose(positions[:, 0], 0) and positions[:, 1].max() > 1

    def test_a_surface_emitter_throws_from_its_surface_along_the_normals(self):
        positions, directions = sample(SurfaceEmitter(surface=basenodes.Box(size=(2, 2, 2))))
        assert np.allclose(np.abs(positions).max(axis=1), 1.0, atol=1e-4)
        assert np.all(np.einsum('ij,ij->i', positions, directions) > 0.99)

    def test_a_volume_emitter_starts_particles_inside_its_faces(self):
        emitter = VolumeEmitter(coord=basenodes.Coordinate(point=CUBE), coordIndex=CUBE_FACES,
                                direction=(1, 0, 0))
        positions, directions = sample(emitter)
        assert np.all(np.abs(positions) <= 1.0 + 1e-6)
        assert (np.abs(positions).max(axis=1) < 0.9).mean() > 0.5
        assert np.allclose(directions, (1, 0, 0))

    def test_a_volume_emitter_that_is_not_internal_uses_its_boundary(self):
        emitter = VolumeEmitter(coord=basenodes.Coordinate(point=CUBE), coordIndex=CUBE_FACES,
                                internal=False)
        positions, _directions = sample(emitter)
        assert np.allclose(np.abs(positions).max(axis=1), 1.0, atol=1e-5)

    def test_an_emitter_with_no_geometry_is_empty(self):
        assert SurfaceEmitter().particleSource().empty
        assert VolumeEmitter().particleSource().empty
        assert PolylineEmitter().particleSource().empty

    def test_the_source_follows_every_field_it_is_made_from(self):
        cone = ConeEmitter()
        check_memo_inputs(
            lambda: cone.particleSource(),
            [('position', lambda: setattr(cone, 'position', (1, 0, 0))),
             ('direction', lambda: setattr(cone, 'direction', (0, 0, 1))),
             ('angle', lambda: setattr(cone, 'angle', 0.1))],
            same=lambda a, b: a is b)

    def test_a_geometry_source_follows_its_geometry(self):
        coord = basenodes.Coordinate(point=[(0, 0, 0), (1, 0, 0)])
        polyline = PolylineEmitter(coord=coord, coordIndex=[0, 1, -1])
        box = basenodes.Box(size=(1, 1, 1))
        surface = SurfaceEmitter(surface=box)
        volume = VolumeEmitter(coord=basenodes.Coordinate(point=CUBE), coordIndex=CUBE_FACES)

        def extents():
            return tuple(tuple(np.round(np.concatenate(
                emitter.particleSource().extent()), 5)) for emitter in (polyline, surface, volume))

        def fresh():
            from OpenGLContext.scenegraph import x3dparticles
            return tuple(tuple(np.round(np.concatenate(
                x3dparticles.build_source(emitter).extent()), 5))
                for emitter in (polyline, surface, volume))
        check_memo_inputs(extents, [
            ('coord point', lambda: setattr(coord, 'point', [(0, 0, 0), (3, 0, 0)])),
            ('coord node', lambda: setattr(polyline, 'coord', basenodes.Coordinate(
                point=[(0, 0, 0), (0, 4, 0)]))),
            ('surface size', lambda: setattr(box, 'size', (3, 3, 3))),
            ('surface node', lambda: setattr(surface, 'surface', basenodes.Box(size=(5, 5, 5)))),
            ('volume coord', lambda: setattr(volume.coord, 'point', [
                (x * 2, y * 2, z * 2) for x, y, z in CUBE])),
        ], fresh=fresh)


class TestPhysicsModels:
    def test_a_force_model_is_a_force_on_the_emitters_mass(self):
        model = ForcePhysicsModel(force=(0, -10, 0)).particleModel(mass=2.0, surfaceArea=0.0)
        assert isinstance(model, particlesim.ConstantForce)
        assert model.acceleration == pytest.approx((0, -5, 0))

    def test_a_wind_model_blows_on_the_emitters_surface_area(self):
        model = WindPhysicsModel(direction=(0, 0, 1), speed=3.0, gustiness=0.0,
                                 turbulence=0.2).particleModel(mass=1.0, surfaceArea=0.5)
        assert isinstance(model, particlesim.Wind)
        assert model.area == 0.5 and model.turbulence == pytest.approx(0.2)

    def test_a_bounded_model_bounds_by_its_geometry(self):
        model = BoundedPhysicsModel(geometry=basenodes.Box(size=(2, 2, 2))).particleModel(
            mass=0.0, surfaceArea=0.0)
        assert isinstance(model, particlesim.Bounds)
        assert np.allclose(model.mesh.high, (1, 1, 1))

    def test_the_bounding_model_follows_its_geometry(self):
        box = basenodes.Box(size=(2, 2, 2))
        bounded = BoundedPhysicsModel(geometry=box)
        check_memo_inputs(
            lambda: tuple(bounded.particleModel(mass=0, surfaceArea=0).mesh.high),
            [('size', lambda: setattr(box, 'size', (4, 4, 4))),
             ('geometry', lambda: setattr(bounded, 'geometry', basenodes.Box(size=(6, 6, 6))))])


class TestParticleSystem:
    def test_it_emits_its_budget_over_one_lifetime(self, clock):
        system = ParticleSystem(maxParticles=100, particleLifetime=2.0, lifetimeVariation=0.0,
                                emitter=PointEmitter(speed=1.0))
        run(system, 1.0)
        assert system.particleCount == pytest.approx(50, abs=2)
        run(system, 3.0, start=1.0)
        assert 90 <= system.particleCount <= 100

    def test_each_particle_lives_its_lifetime_give_or_take_the_variation(self, clock):
        system = ParticleSystem(maxParticles=200, particleLifetime=2.0, lifetimeVariation=0.25,
                                emitter=PointEmitter())
        run(system, 0.5)
        lifetimes = system.pool.lifetime[:system.pool.live]
        assert lifetimes.min() >= 1.5 - 1e-5 and lifetimes.max() <= 2.5 + 1e-5
        assert lifetimes.std() > 0.05

    def test_particles_leave_the_emitter_at_its_speed(self, clock):
        system = ParticleSystem(maxParticles=50, particleLifetime=5.0,
                                emitter=PointEmitter(speed=2.0, variation=0.0, direction=(1, 0, 0)))
        run(system, 0.5)
        assert np.allclose(system.pool.velocity[:system.pool.live], (2, 0, 0))

    def test_creating_no_particles_leaves_those_out_to_live_on(self, clock):
        system = ParticleSystem(maxParticles=100, particleLifetime=2.0, emitter=PointEmitter())
        now = run(system, 0.5)
        alive = system.particleCount
        system.createParticles = False
        run(system, 0.2, start=now)
        assert 0 < system.particleCount <= alive

    def test_an_emitter_that_is_off_creates_nothing(self, clock):
        system = ParticleSystem(maxParticles=100, emitter=PointEmitter(on=False))
        run(system, 0.5)
        assert system.particleCount == 0

    def test_a_disabled_system_has_no_particles_and_is_not_active(self, clock):
        system = ParticleSystem(maxParticles=100, emitter=PointEmitter())
        now = run(system, 0.5)
        assert system.isActive
        system.enabled = False
        run(system, 0.1, start=now)
        assert system.particleCount == 0
        assert system.isActive is False

    def test_a_system_becomes_inactive_once_its_last_particle_dies(self, clock):
        system = ParticleSystem(maxParticles=20, particleLifetime=0.5, lifetimeVariation=0.0,
                                emitter=ExplosionEmitter())
        now = run(system, 0.1)
        assert system.isActive and system.particleCount == 20
        run(system, 1.0, start=now)
        assert system.particleCount == 0
        assert not system.isActive

    def test_an_explosion_releases_its_whole_budget_once(self, clock):
        system = ParticleSystem(maxParticles=30, particleLifetime=0.5, lifetimeVariation=0.0,
                                emitter=ExplosionEmitter(speed=1.0))
        now = run(system, 0.05)
        assert system.particleCount == 30
        now = run(system, 1.5, start=now)
        assert system.particleCount == 0

    def test_an_explosion_goes_off_again_when_creation_is_switched_back_on(self, clock):
        system = ParticleSystem(maxParticles=30, particleLifetime=0.5,
                                emitter=ExplosionEmitter())
        now = run(system, 1.5)
        system.createParticles = False
        now = run(system, 0.1, start=now)
        system.createParticles = True
        run(system, 0.05, start=now)
        assert system.particleCount == 30

    def test_shrinking_the_budget_keeps_the_survivors_it_can(self, clock):
        system = ParticleSystem(maxParticles=100, particleLifetime=5.0, emitter=PointEmitter())
        now = run(system, 2.0)
        system.maxParticles = 10
        run(system, 0.0, start=now)
        assert system.particleCount == 10
        assert system.pool.capacity == 10

    def test_no_emitter_is_a_still_point_at_the_origin(self, clock):
        system = ParticleSystem(maxParticles=10, particleLifetime=1.0)
        run(system, 0.5)
        assert system.particleCount > 0
        assert np.allclose(system.pool.position[:system.pool.live], 0.0)

    def test_the_physics_models_act_in_order_on_the_emitters_mass(self, clock):
        system = ParticleSystem(maxParticles=10, particleLifetime=10.0,
                                emitter=ExplosionEmitter(mass=2.0),
                                physics=[ForcePhysicsModel(force=(0, -4, 0)),
                                         ForcePhysicsModel(force=(2, 0, 0), enabled=False)])
        now = run(system, 1.0 / 60.0)
        system.createParticles = False
        before = system.pool.velocity[0].copy()
        system.advance(now + 0.05)
        assert system.pool.velocity[0] - before == pytest.approx((0, -0.1, 0), abs=1e-5)

    def test_a_bounded_system_keeps_its_particles_in(self, clock):
        system = ParticleSystem(maxParticles=200, particleLifetime=10.0,
                                emitter=ExplosionEmitter(speed=4.0),
                                physics=[BoundedPhysicsModel(geometry=basenodes.Box(size=(2, 2, 2)))])
        run(system, 3.0)
        assert np.all(np.abs(system.pool.position[:system.pool.live]) <= 1.0 + 1e-3)

    def test_wind_carries_the_particles_downwind(self, clock):
        system = ParticleSystem(maxParticles=50, particleLifetime=10.0,
                                emitter=PointEmitter(mass=1.0, surfaceArea=1.0),
                                physics=[WindPhysicsModel(direction=(1, 0, 0), speed=2.0,
                                                          gustiness=0.0)])
        run(system, 1.0)
        assert np.all(system.pool.velocity[:system.pool.live, 0] > 0)


class TestLook:
    def test_each_geometry_type_is_drawn_as_its_shape(self):
        shapes = {kind: ParticleSystem(geometryType=kind).look(None).shape
                  for kind in ('LINE', 'POINT', 'QUAD', 'SPRITE', 'TRIANGLE')}
        assert shapes == {'LINE': 'line', 'POINT': 'point', 'QUAD': 'quad',
                          'SPRITE': 'sprite', 'TRIANGLE': 'quad'}

    def test_the_particle_size_is_width_and_height(self):
        assert ParticleSystem(particleSize=(0.5, 0.25)).look(None).size == (0.5, 0.25)

    def test_an_opaque_appearance_is_drawn_opaque(self):
        system = ParticleSystem(appearance=basenodes.Appearance(
            material=basenodes.Material(diffuseColor=(1, 0, 0))))
        look = system.look(None)
        assert look.blending == 'opaque'
        assert look.start_color == pytest.approx((1, 0, 0, 1))

    def test_a_transparent_material_is_blended(self):
        system = ParticleSystem(appearance=basenodes.Appearance(
            material=basenodes.Material(transparency=0.5)))
        look = system.look(None)
        assert look.blending == 'alpha' and look.start_color[3] == pytest.approx(0.5)

    def test_an_emissive_material_draws_in_its_emissive_colour(self):
        system = ParticleSystem(appearance=basenodes.Appearance(
            material=basenodes.Material(emissiveColor=(0, 1, 0))))
        assert system.look(None).start_color == pytest.approx((0, 1, 0, 1))

    def test_a_translucent_colour_ramp_is_blended(self):
        system = ParticleSystem(colorKey=[0, 1], color=x3d.ColorRGBA(
            color=[(1, 0, 0, 1), (1, 0, 0, 0)]))
        assert system.look(None).blending == 'alpha'

    def test_the_colour_ramp_is_keyed_by_age_in_seconds(self, clock):
        system = ParticleSystem(maxParticles=1, particleLifetime=10.0, lifetimeVariation=0.0,
                                colorKey=[0, 2], color=basenodes.Color(color=[(1, 0, 0), (0, 0, 1)]),
                                emitter=ExplosionEmitter())
        run(system, 1.0)
        colors = system.particleColors()
        assert colors[0] == pytest.approx((0.5, 0, 0.5, 1), abs=0.02)

    def test_without_a_ramp_each_particle_is_white(self, clock):
        system = ParticleSystem(maxParticles=1, emitter=PointEmitter())
        run(system, 0.1)
        assert system.particleColors() is None

    def test_texture_frames_step_with_age_in_seconds(self, clock):
        frames = [(0, 0), (0.5, 0), (0.5, 1), (0, 1), (0.5, 0), (1, 0), (1, 1), (0.5, 1)]
        system = ParticleSystem(maxParticles=1, particleLifetime=10.0, lifetimeVariation=0.0,
                                texCoordKey=[0, 1],
                                texCoord=x3d.TextureCoordinate(point=frames),
                                emitter=ExplosionEmitter())
        run(system, 0.5)
        assert list(system.particleFrames()) == [0]
        run(system, 1.0, start=0.5)
        assert list(system.particleFrames()) == [1]
        assert system.look(None).frames.shape == (2, 4, 2)

    def test_point_size_comes_from_the_point_properties(self):
        system = ParticleSystem(geometryType='POINT', appearance=basenodes.Appearance(
            pointProperties=x3d.PointProperties(pointSizeScaleFactor=4, pointSizeMaxValue=8)))
        assert system.look(None).point_size == (4.0, 1.0, 8.0)


class TestGeometryParticles:
    def test_a_geometry_system_draws_its_geometry_at_each_particle(self, clock):
        system = ParticleSystem(geometryType='GEOMETRY', geometry=basenodes.Box(size=(0.1, 0.1, 0.1)),
                                maxParticles=5, particleLifetime=10.0,
                                emitter=ExplosionEmitter(speed=1.0, variation=0))
        assert system.drawsNothing()
        run(system, 1.0)
        placements = system.instancePlacements()
        assert placements.shape == (5, 4, 4)
        assert np.allclose(placements[:, 3, :3], system.pool.position[:5])
        assert not system.drawsNothing()

    def test_other_types_have_no_placements(self, clock):
        system = ParticleSystem(geometryType='QUAD', geometry=basenodes.Box(),
                                maxParticles=5, emitter=PointEmitter())
        run(system, 0.5)
        assert system.instancePlacements() is None

    def test_a_geometry_system_is_sorted_by_its_appearance(self):
        system = ParticleSystem(geometryType='GEOMETRY', geometry=basenodes.Box())
        assert system.sortKey(_Mode(), np.identity(4))[0] is False
        assert ParticleSystem().sortKey(_Mode(), np.identity(4))[0] is True


class _Mode:
    def getProjection(self):
        return np.identity(4)

    def getViewport(self):
        return (0, 0, 10, 10)


class TestBounds:
    def test_the_bounds_cover_the_living_particles(self, clock):
        system = ParticleSystem(maxParticles=50, particleLifetime=10.0,
                                emitter=PointEmitter(speed=1.0, direction=(1, 0, 0)))
        run(system, 3.0)
        volume = system.boundingVolume(None)
        low = np.asarray(volume.center) - np.asarray(volume.size) / 2
        high = np.asarray(volume.center) + np.asarray(volume.size) / 2
        live = system.pool.position[:system.pool.live]
        assert np.all(live >= low) and np.all(live <= high)

    def test_the_bounds_cover_where_particles_will_start(self):
        system = ParticleSystem(emitter=PolylineEmitter(
            coord=basenodes.Coordinate(point=[(10, 0, 0), (12, 0, 0)]), coordIndex=[0, 1, -1]))
        volume = system.boundingVolume(None)
        high = np.asarray(volume.center) + np.asarray(volume.size) / 2
        assert high[0] >= 12


class TestLoading:
    def test_a_document_builds_the_engines_nodes(self):
        from OpenGLContext.loaders.x3d import X3DHandler
        document = b'''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Full" version="4.0"><Scene>
<ParticleSystem DEF="P" geometryType="SPRITE" maxParticles="50" colorKey="0 1">
  <ConeEmitter containerField="emitter" angle="0.3" speed="2"/>
  <WindPhysicsModel containerField="physics" speed="3"/>
  <ForcePhysicsModel containerField="physics"/>
  <ColorRGBA containerField="color" color="1 0 0 1 0 0 1 0"/>
</ParticleSystem></Scene></X3D>'''
        _ok, scene = X3DHandler().parse(document, '')
        system = scene.children[0]
        assert isinstance(system, ParticleSystem)
        assert isinstance(system.emitter, ConeEmitter)
        assert [type(model).__name__ for model in system.physics] == [
            'WindPhysicsModel', 'ForcePhysicsModel']


class QueueContext:
    """A context's render queue and redraw requests, with no window"""

    def __init__(self):
        from OpenGLContext.events.renderqueue import RenderQueue
        self.renderQueue = RenderQueue()
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


class TestTicking:
    def test_a_bound_system_steps_each_frame_while_it_is_active(self, clock):
        system = ParticleSystem(maxParticles=10, particleLifetime=0.2, lifetimeVariation=0.0,
                                emitter=ExplosionEmitter())
        context = QueueContext()
        system.bind(context)
        assert system.particleCount == 10 and len(context.renderQueue) == 1
        for _ in range(30):
            clock.advance()
            context.renderQueue.run()
        assert system.particleCount == 0
        assert len(context.renderQueue) == 0
        assert context.redraws > 0

    def test_switching_creation_back_on_wakes_a_stopped_system(self, clock):
        system = ParticleSystem(maxParticles=10, particleLifetime=0.2, lifetimeVariation=0.0,
                                emitter=ExplosionEmitter())
        context = QueueContext()
        system.bind(context)
        for _ in range(30):
            clock.advance()
            context.renderQueue.run()
        system.createParticles = False
        system.createParticles = True
        assert len(context.renderQueue) == 1
        context.renderQueue.run()
        assert system.particleCount == 10

    def test_switching_the_emitter_back_on_wakes_a_stopped_system(self, clock):
        emitter = PointEmitter(on=False)
        system = ParticleSystem(maxParticles=10, emitter=emitter)
        context = QueueContext()
        system.bind(context)
        context.renderQueue.run()
        assert len(context.renderQueue) == 0
        emitter.on = True
        assert len(context.renderQueue) == 1
