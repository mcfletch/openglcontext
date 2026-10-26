"""A swept sphere is tested against a fixed body only at the steps its box reaches that body's, and
travels exactly as far as when it was tested against every candidate at every step."""
import numpy as np
import pytest
from omi_physics import model
from omi_physics.body import SphereProxy
from omi_physics.collide import collide
from omi_physics.world import PhysicsWorld

from OpenGLContext.physics import queries
from OpenGLContext.physics.queries import _BISECTIONS, _candidates, _proxy, sweep_sphere


def every_candidate_every_step(world, origin, direction, distance, radius, skip=()):
    """The sweep as it is defined: each candidate tested at each step, then halved to the touch."""
    start = np.asarray(origin, dtype='d')
    heading = np.asarray(direction, dtype='d')
    length = float(np.linalg.norm(heading))
    if length == 0.0 or distance <= 0.0:
        return None
    heading = heading / length
    end = start + heading * distance
    near = _candidates(world, np.minimum(start, end) - radius, np.maximum(start, end) + radius, skip)
    if not near:
        return None

    def touching(travelled):
        probe = SphereProxy(start + heading * travelled, radius)
        return any(collide(-1, j, probe, _proxy(world, j)) for j in near)

    if touching(0.0):
        return 0.0
    step = max(radius * 0.5, distance / 2048.0)
    clear, travelled = 0.0, step
    while clear < distance:
        travelled = min(travelled, distance)
        if touching(travelled):
            low, high = clear, travelled
            for _ in range(_BISECTIONS):
                middle = (low + high) / 2.0
                if touching(middle):
                    high = middle
                else:
                    low = middle
            return high
        clear, travelled = travelled, travelled + step
    return None


def scattered(seed: int) -> PhysicsWorld:
    """Fixed boxes, balls, capsules and a mesh, and a moving crate or two."""
    rng = np.random.default_rng(seed)
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    shapes = [world.add_shape(model.Shape.box(tuple(rng.uniform(0.3, 3.0, 3)))) for _ in range(3)]
    shapes.append(world.add_shape(model.Shape.sphere(float(rng.uniform(0.2, 1.0)))))
    shapes.append(world.add_shape(model.Shape.capsule(height=1.0, radius=0.3)))
    points = rng.uniform(-1.0, 1.0, (6, 3))
    shapes.append(world.add_shape(model.Shape.trimesh(points, [(0, 1, 2), (3, 4, 5), (0, 2, 4)])))
    for handle in range(int(rng.integers(10, 30))):
        turn = rng.normal(size=4)
        world.add_body(model.Motion(type=model.STATIC),
                       collider=model.Collider(shape=int(rng.choice(shapes))),
                       position=tuple(rng.uniform(-8.0, 8.0, 3)),
                       orientation=tuple(turn / np.linalg.norm(turn)), handle=handle + 1)
    for handle in range(int(rng.integers(0, 3))):
        world.add_body(model.Motion(type=model.DYNAMIC, mass=1.0,
                                    linearVelocity=tuple(rng.uniform(-2.0, 2.0, 3))),
                       collider=model.Collider(shape=shapes[0]),
                       position=tuple(rng.uniform(-8.0, 8.0, 3)), handle=100 + handle)
    world.step(1.0 / 60.0)          # the crates' boxes lag their poses by the step
    return world


@pytest.mark.parametrize('seed', range(40))
def test_a_sweep_travels_as_far_as_one_tested_against_every_candidate_at_every_step(seed):
    world = scattered(seed)
    rng = np.random.default_rng(500 + seed)
    stopped = 0
    for _ in range(60):
        origin = rng.uniform(-8.0, 8.0, 3)
        direction = rng.normal(size=3)
        distance, radius = float(rng.uniform(0.5, 20.0)), float(rng.uniform(0.05, 1.0))
        wanted = every_candidate_every_step(world, origin, direction, distance, radius)
        assert sweep_sphere(world, origin, direction, distance, radius) == wanted
        stopped += wanted is not None
    assert stopped


def test_a_fixed_body_is_tested_only_where_the_sphere_reaches_it(monkeypatch):
    world = PhysicsWorld(gravity=model.Gravity(gravity=0.0))
    wall = world.add_shape(model.Shape.box((1.0, 4.0, 4.0)))
    world.add_body(model.Motion(type=model.STATIC), collider=model.Collider(shape=wall),
                   position=(18.0, 0.0, 0.0), handle=1)
    world.refit_aabbs()
    asked = []
    monkeypatch.setattr(queries, 'collide', lambda *a: asked.append(a) or collide(*a))
    found = sweep_sphere(world, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), 20.0, 0.25)
    assert found == pytest.approx(17.25, abs=1e-3)
    # The steps of 0.125 m from 17.2 m on, and the halvings: not the 137 steps before them.
    assert len(asked) < 2 + 14 + 4
