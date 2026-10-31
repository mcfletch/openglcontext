"""Soft bodies on the physics service: specs, pins, wind, frames by version and removal."""
import math

import numpy as np
import pytest

from OpenGLContext.physics.engine import EngineUnavailable
from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.softbodies import SoftBodySpec, icosphere

HZ = 60.0


def make(**named) -> Physics:
    named.setdefault('mode', 'inline')
    named.setdefault('tickHz', HZ)
    named.setdefault('engine', 'jolt')
    return Physics(PhysicsDefinition(**named))


def run_for(physics: Physics, seconds: float, frame: float = 1.0 / 60.0) -> None:
    for _ in range(int(round(seconds / frame))):
        physics.frame(frame)


@pytest.fixture
def world():
    physics = make()
    physics.add_static(None, proxy=Proxy.box((40.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
    yield physics
    physics.close()


def hanging(world, at=(0.0, 2.0, 0.0), **values):
    values.setdefault('linear_damping', 2.0)
    cloth = SoftBodySpec.cloth(1.0, 1.0, 11, 11, mass=0.5, **values)
    a, b, _, _ = cloth.corner_indices()
    pins = cloth.positions[[a, b]] + at
    return world.add_soft_body(cloth, position=at, pins=([a, b], pins)), (a, b), pins


# -- the spec -----------------------------------------------------------------

def test_a_cloth_is_a_grid_of_upward_faces():
    cloth = SoftBodySpec.cloth(2.0, 1.0, 5, 3, mass=1.0)
    assert len(cloth) == 15 and cloth.faces.shape == (16, 3)
    a, b, c, _ = (cloth.positions[i] for i in cloth.corner_indices())
    assert np.cross(b - a, c - a)[1] < 0.0 or np.cross(c - a, b - a)[1] > 0.0
    first = cloth.positions[cloth.faces[0]]
    assert np.cross(first[1] - first[0], first[2] - first[0])[1] > 0.0


def test_rope_and_ball_layout():
    rope = SoftBodySpec.rope([(0, 0, 0), (1, 0, 0)], segments=10, bend_compliance=0.01)
    assert len(rope) == 11 and len(rope.edges) == 10 + 9
    ball = SoftBodySpec.ball(radius=0.5, subdivisions=1)
    assert len(ball.faces) == 80 and ball.bend == 'none'
    assert np.linalg.norm(ball.positions, axis=1) == pytest.approx(0.5)
    vertices, faces = icosphere(0)
    assert len(vertices) == 12 and len(faces) == 20


@pytest.mark.parametrize('call, message', [
    (lambda: SoftBodySpec(np.zeros((3, 3)), faces=[[0, 1, 5]]), 'faces'),
    (lambda: SoftBodySpec(np.zeros((0, 3))), 'at least one'),
    (lambda: SoftBodySpec.cloth(1, 1, 3, 3, mass=-1.0), 'mass'),
    (lambda: SoftBodySpec.cloth(1, 1, 1, 3), 'columns'),
    (lambda: SoftBodySpec(np.zeros((3, 3)), bend='folded'), 'bend'),
    (lambda: SoftBodySpec(np.zeros((3, 3)), long_range='far'), 'long_range'),
    (lambda: SoftBodySpec(np.full((3, 3), math.nan)), 'finite'),
    (lambda: SoftBodySpec(np.zeros((3, 3)), masses=[1.0, -1.0, 1.0]), 'masses'),
    (lambda: SoftBodySpec.rope([(0, 0, 0)]), 'two points'),
    (lambda: SoftBodySpec.ball().corner_indices(), 'corners'),
])
def test_a_spec_that_describes_no_body_is_refused(call, message):
    with pytest.raises(ValueError, match=message):
        call()


def test_a_spec_round_trips_through_plain_data():
    rope = SoftBodySpec.rope([(0, 0, 0), (0, -1, 0)], segments=4)
    again = SoftBodySpec.from_dict(rope.as_dict())
    assert np.array_equal(again.positions, rope.positions)
    assert np.array_equal(again.edges, rope.edges)
    assert again.bend_compliance == math.inf
    masses = SoftBodySpec(np.zeros((2, 3)), masses=[1.0, 2.0])
    assert masses.total_mass() == 3.0


# -- in the world ------------------------------------------------------------------

def test_a_cloth_pinned_at_two_corners_hangs_from_them(world):
    soft, corners, pins = hanging(world)
    assert soft.vertices() == pytest.approx(soft.spec.positions + (0.0, 2.0, 0.0))
    assert soft.frame() is None
    run_for(world, 4.0)
    vertices = soft.vertices()
    assert np.abs(vertices[list(corners)] - pins).max() < 1e-3
    assert vertices[:, 1].min() < 2.0 - 0.8
    frame = soft.frame()
    assert frame.positions.dtype == np.float32
    assert np.linalg.norm(frame.normals, axis=1) == pytest.approx(1.0, abs=1e-3)
    assert soft.body.kind == 'soft' and soft.body.mass == pytest.approx(0.5)


def test_the_version_moves_while_the_cloth_moves_and_stops_when_it_sleeps(world):
    cloth = SoftBodySpec.cloth(1.0, 1.0, 11, 11, mass=0.5, linear_damping=2.0, friction=0.8)
    soft = world.add_soft_body(cloth, position=(0.0, 0.3, 0.0))
    run_for(world, 0.2)
    first = soft.frame().version
    run_for(world, 0.2)
    assert soft.frame().version > first
    assert soft.frame() is soft.frame()     # one read a tick
    run_for(world, 8.0)
    resting = soft.frame().version
    run_for(world, 0.5)
    assert soft.frame().version == resting
    soft.set_wind((0.0, 0.0, 3.0))
    run_for(world, 0.5)
    assert soft.frame().version > resting


def test_wind_pushes_a_hanging_cloth(world):
    still, _, _ = hanging(world, at=(0.0, 2.0, 0.0))
    blown, _, _ = hanging(world, at=(4.0, 2.0, 0.0))
    blown.set_wind((0.0, 0.0, 2.0))
    run_for(world, 3.0)
    push = blown.vertices()[:, 2].mean() - still.vertices()[:, 2].mean()
    assert push > 0.1


def test_a_cloth_pinned_to_a_body_follows_it(world):
    carrier = world.add_kinematic(None, proxy=Proxy.box((0.1, 0.1, 0.1)),
                                  translation=(0.0, 2.0, 0.0))
    cloth = SoftBodySpec.cloth(0.6, 0.6, 7, 7, mass=0.2, linear_damping=2.0)
    a, b, _, _ = cloth.corner_indices()
    soft = world.add_soft_body(cloth, position=(0.0, 2.0, 0.3),
                               pins=([a, b], [(-0.3, 0.0, 0.0), (0.3, 0.0, 0.0)]),
                               pin_bodies=carrier)
    run_for(world, 0.5)
    carrier.set_transform(translation=(1.0, 2.0, 0.0))
    run_for(world, 0.5)
    assert soft.vertices()[a] == pytest.approx((0.7, 2.0, 0.0), abs=2e-3)
    soft.unpin()
    run_for(world, 1.0)
    assert soft.vertices()[a][1] < 1.5


def test_pins_change_at_run_time(world):
    soft, corners, _ = hanging(world)
    run_for(world, 0.5)
    soft.pin([corners[0]], [(0.0, 3.0, 0.0)])
    run_for(world, 1.0)
    assert soft.vertices()[corners[0]] == pytest.approx((0.0, 3.0, 0.0), abs=1e-3)
    with pytest.raises(ValueError, match='pinned vertex'):
        soft.pin([500], [(0, 0, 0)])
    with pytest.raises(ValueError, match='finite'):
        soft.pin([0], [(math.nan, 0, 0)])
    with pytest.raises(ValueError, match='one body'):
        soft.pin([0, 1], np.zeros((2, 3)), [None])
    with pytest.raises(ValueError, match='wind'):
        soft.set_wind((math.inf, 0, 0))


def test_a_cloth_drapes_over_a_sphere(world):
    world.add_static(None, proxy=Proxy.sphere(0.5), translation=(0.0, 0.5, 0.0))
    cloth = SoftBodySpec.cloth(2.0, 2.0, 21, 21, mass=1.0, vertex_radius=0.01, friction=0.6)
    soft = world.add_soft_body(cloth, position=(0.0, 1.3, 0.0))
    run_for(world, 3.0)
    vertices = soft.vertices()
    assert np.linalg.norm(vertices - (0.0, 0.5, 0.0), axis=1).min() > 0.49
    assert vertices[len(vertices) // 2][1] == pytest.approx(1.01, abs=0.03)


def test_a_soft_body_is_removed_like_a_body(world):
    soft, _, _ = hanging(world)
    run_for(world, 0.1)
    before = world.counts.bodies
    soft.remove()
    soft.remove()
    run_for(world, 0.1)
    assert world.counts.bodies == before - 1
    assert not soft.alive and soft.frame() is None
    soft.set_wind((1.0, 0.0, 0.0))      # a removed body's commands go nowhere


def test_a_spec_is_required(world):
    with pytest.raises(TypeError, match='SoftBodySpec'):
        world.add_soft_body('cloth')
    with pytest.raises(ValueError, match='quaternion'):
        world.add_soft_body(SoftBodySpec.ball(), rotation=(0, 0, 0, 0))


def test_the_costs_name_the_soft_bodies(world):
    hanging(world)
    run_for(world, 0.5)
    costs = world.deformable_costs()
    assert costs['soft bodies'] == 1.0 and costs['soft bodies ms'] > 0.0


def test_an_engine_without_soft_bodies_says_so():
    physics = Physics(PhysicsDefinition(mode='inline'))
    physics._engine.soft_bodies = False     # noqa: SLF001 an engine that declares no soft bodies
    try:
        with pytest.raises(EngineUnavailable, match='soft bodies need the jolt engine'):
            physics.add_soft_body(SoftBodySpec.ball())
    finally:
        physics.close()
