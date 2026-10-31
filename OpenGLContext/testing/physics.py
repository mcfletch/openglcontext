"""Test-only access to what a physics service's engine holds.

A test that checks what the engine itself holds (its shapes, masses,
materials, joints, step) reads it here: :func:`settle`, :func:`holds`,
:func:`shape_kind`, :func:`mass`, :func:`material`, :func:`joint_count`,
:func:`step_dt`, :func:`world_position`, :func:`event_backlog`,
:func:`wait_ticks` and the rest read the Jolt engine's world. A game reads
bodies through :class:`~OpenGLContext.physics.body.Body` handles and
:meth:`Physics.poses <OpenGLContext.physics.service.Physics.poses>`, which
answer the same on every engine. Nothing here is exported by
:mod:`OpenGLContext.physics`.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['event_backlog', 'filter_count', 'holds', 'idle', 'joint_count', 'mass', 'material',
           'material_count', 'material_index', 'pair_friction', 'settle', 'shape_count', 'shape_kind',
           'step_dt', 'stepping', 'ticks', 'wait_ticks', 'world_position']

#: Seconds :func:`settle` and :func:`wait_ticks` wait for a world stepping on its own.
WAIT = 5.0


def settle(physics: Physics) -> None:
    """Have the engine take the commands made so far.

    A world in lockstep runs one tick, and a free-running one is waited for
    until a snapshot includes them. Raises AssertionError where it has not
    within :data:`WAIT` seconds, as a world that is stopped or paused never does.
    """
    engine: Any = physics._engine
    world = engine.world
    seq = int(world.submitted_seq)
    if world.lockstep:
        world.run_ticks(1)
        return
    deadline = time.monotonic() + WAIT
    while True:
        latest = world.latest()
        if latest is not None and latest.includes(seq):
            return
        left = deadline - time.monotonic()
        if left <= 0.0 or not world.wait_tick(world.tick + 1, left):
            raise AssertionError('the world did not take the commands made up to sequence %d '
                                 'in %g s' % (seq, WAIT))


def wait_ticks(physics: Physics, count: int) -> bool:
    """Wait for ``count`` more ticks of a world stepping on its own; False if they do not come."""
    engine: Any = physics._engine
    world = engine.world
    return bool(world.wait_tick(world.tick + count, WAIT))


def idle(physics: Physics) -> bool:
    """Whether a world stepping on its own has nothing to do and is waiting, using no time."""
    engine: Any = physics._engine
    return bool(engine.world.stats()['idle'])


def stepping(physics: Physics) -> bool:
    """Whether a thread of the engine is stepping the world."""
    engine: Any = physics._engine
    return bool(engine.world.stats()['running'])


def ticks(physics: Physics) -> int:
    """How many steps the engine's thread has taken."""
    engine: Any = physics._engine
    return int(engine.world.tick)


def holds(physics: Physics, body: Body) -> bool:
    """Whether the engine holds ``body``, once the commands made so far are taken."""
    settle(physics)
    engine: Any = physics._engine
    return engine.jolt_uid(body.uid) is not None


def shape_kind(physics: Physics, body: Body) -> str:
    """The kind of shape the engine gave ``body``: ``box``, ``sphere``, ``capsule``, ``cylinder``,
    ``convex``, ``mesh``, ``heightfield`` or ``compound``."""
    settle(physics)
    engine: Any = physics._engine
    import pyjoltphysics as pj  # noqa: PLC0415 only a Jolt world needs it

    jolt = engine.jolt_uid(body.uid)
    for (uid, _moving), shape_id in engine._shapes.items():
        if body.proxy is not None and uid == body.proxy.uid:
            kind = pj.ShapeKind(engine.world.shape_info(shape_id).kind)
            return kind.name.lower() if jolt is not None else ''
    return ''


def shape_count(physics: Physics) -> int:
    """How many shapes the engine has made for the bodies it holds."""
    settle(physics)
    engine: Any = physics._engine
    return len(engine._shapes)


def mass(physics: Physics, body: Body) -> float:
    """The mass Jolt holds for ``body``, in kilograms; 0 for a body that is not dynamic.

    Measured between ticks: an impulse is applied and the change of velocity
    it makes read back, then the opposite impulse puts the velocity back. The
    impulse is about the mass asked for times 1 m/s, so the change is about
    1 m/s whatever the mass.
    """
    settle(physics)
    if body.kind != 'dynamic':
        return 0.0
    engine: Any = physics._engine
    world = engine.world
    ids = np.array([engine.jolt_uid(body.uid)], dtype=np.uint32)
    push = np.array([[max(float(engine.given[body.uid][0]), 1e-3), 0.0, 0.0]])
    before = float(world.bodies_state(ids).linear_velocity[0][0])
    world.add_impulses(ids, push)
    world.flush()
    after = float(world.bodies_state(ids).linear_velocity[0][0])
    world.add_impulses(ids, -push)
    world.flush()
    return float(push[0, 0]) / (after - before)


def material(physics: Physics, body: Body) -> Any:
    """The engine's material of ``body`` as an object with ``staticFriction``, ``dynamicFriction``
    and ``restitution``; None where it has the engine's default."""
    settle(physics)
    engine: Any = physics._engine
    from OpenGLContext.physics.types import Material  # noqa: PLC0415 the service's own record

    index = engine.given[body.uid][1]
    row = engine.world.materials[index]
    found = Material(staticFriction=row.static_friction, dynamicFriction=row.dynamic_friction,
                     restitution=row.restitution)
    return None if found == Material() else found


def material_index(physics: Physics, body: Body) -> int:
    """The engine's index of the material ``body`` has."""
    settle(physics)
    engine: Any = physics._engine
    return int(engine.given[body.uid][1])


def material_count(physics: Physics) -> int:
    """How many materials the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    return len(engine.world.materials) - 1


def pair_friction(physics: Physics, first: Body, second: Body) -> tuple[float, float] | None:
    """The static and dynamic friction a pair entry gives ``first`` and ``second``; None with none."""
    settle(physics)
    engine: Any = physics._engine
    found = engine.world.materials.pairing(engine.given[first.uid][1], engine.given[second.uid][1])
    return None if found is None else (float(found[0]), float(found[1]))


def filter_count(physics: Physics) -> int:
    """How many collision filters the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    return len(engine._filters)


def joint_count(physics: Physics) -> int:
    """How many joints the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    return len(engine._joints)


def event_backlog(physics: Physics) -> tuple[int, int]:
    """The contact and state events the engine holds that the service has not taken, and how
    many it has dropped for want of room."""
    engine: Any = physics._engine
    stats = engine.world.stats()
    return int(stats['events_held']), int(stats['events_dropped'])


def step_dt(physics: Physics) -> float:
    """The engine's fixed step, in seconds."""
    return float(physics._engine.step_dt)


def world_position(physics: Physics, body: Body) -> Any:
    """Where the engine holds ``body`` once the commands made so far are taken."""
    settle(physics)
    engine: Any = physics._engine
    return engine.live_poses([body.uid])[body.uid].position

