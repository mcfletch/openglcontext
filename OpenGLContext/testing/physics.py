"""Test-only access to what a physics service's engine holds.

A test that checks what the engine itself holds (its shapes, masses,
materials, joints, step) reads it here. :func:`settle`, :func:`holds`,
:func:`shape_kind`, :func:`mass`, :func:`material`, :func:`joint_count`,
:func:`step_dt`, :func:`world_position` and :func:`wait_ticks` answer on
either engine; :func:`inspect`, :func:`slot_of`, :func:`body_at` and
:func:`run` reach the omi_physics world and go away with it. A game reads
bodies through :class:`~OpenGLContext.physics.body.Body` handles and
:meth:`Physics.poses <OpenGLContext.physics.service.Physics.poses>`, which
answer the same on every engine. Nothing here is exported by
:mod:`OpenGLContext.physics`.
"""
from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.service import Physics

__all__ = ['body_at', 'filter_count', 'holds', 'idle', 'inspect', 'joint_count', 'mass', 'material', 'run', 'settle',
           'material_count', 'material_index', 'pair_friction', 'shape_count', 'shape_kind', 'slot_of', 'step_dt', 'stepping', 'wait_ticks',
           'world_position']

#: Seconds :func:`settle` and :func:`wait_ticks` wait for a world stepping on its own.
WAIT = 5.0


def settle(physics: Physics) -> None:
    """Have the engine take the commands made so far.

    The omi engine applies them; a Jolt world in lockstep runs one tick, and
    a free-running one is waited for until a snapshot includes them.
    """
    engine: Any = physics._engine
    if engine.name == 'omi':
        if engine.mode == 'thread' and engine.worker.thread_id is not None:
            engine.worker.settle(WAIT)
        else:
            engine.worker.flush()
        return
    world = engine.world
    seq = int(world.submitted_seq)
    if world.lockstep:
        world.run_ticks(1)
    else:
        deadline = world.tick + int(WAIT * float(physics.definition.tickHz))
        while world.wait_tick(world.tick + 1, WAIT):
            latest = world.latest()
            if latest is not None and latest.includes(seq) or world.tick > deadline:
                break


def wait_ticks(physics: Physics, count: int) -> bool:
    """Wait for ``count`` more ticks of a world stepping on its own; False if they do not come."""
    engine: Any = physics._engine
    if engine.name == 'omi':
        return bool(engine.worker.wait_ticks(count, WAIT))
    world = engine.world
    return bool(world.wait_tick(world.tick + count, WAIT))


def idle(physics: Physics) -> bool:
    """Whether a world stepping on its own has nothing to do and is waiting, using no time."""
    engine: Any = physics._engine
    if engine.name == 'omi':
        return bool(engine.worker.idle)
    return bool(engine.world.stats()['idle'])


def stepping(physics: Physics) -> bool:
    """Whether a thread of the engine is stepping the world."""
    engine: Any = physics._engine
    if engine.name == 'omi':
        return engine.worker.__dict__.get('_thread') is not None and engine.worker.thread_id is not None
    return bool(engine.world.stats()['running'])


def holds(physics: Physics, body: Body) -> bool:
    """Whether the engine holds ``body``, once the commands made so far are taken."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        return body.uid in engine.runtime
    return engine.jolt_uid(body.uid) is not None


def shape_kind(physics: Physics, body: Body) -> str:
    """The kind of shape the engine gave ``body``: ``box``, ``sphere``, ``capsule``, ``cylinder``,
    ``convex``, ``mesh``, ``heightfield`` or ``compound``."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        world = runtime.world
        found = str(world.shapes[int(world.collider_shape[runtime.entry(body.uid).index])].type)
        return {'trimesh': 'mesh'}.get(found, found)
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
    if engine.name == 'omi':
        return len(engine.runtime.world.shapes)
    return len(engine._shapes)


def mass(physics: Physics, body: Body) -> float:
    """The mass the engine gave ``body``, in kilograms."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        return float(runtime.world.mass[runtime.entry(body.uid).index])
    return float(engine.given[body.uid][0])


def material(physics: Physics, body: Body) -> Any:
    """The engine's material of ``body`` as an object with ``staticFriction``, ``dynamicFriction``
    and ``restitution``; None where it has the engine's default."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        world = runtime.world
        index = int(world.collider_material[runtime.entry(body.uid).index])
        return None if index < 0 else world.material_for(index)
    from OpenGLContext.physics.types import Material  # noqa: PLC0415 the service's own record

    index = engine.given[body.uid][1]
    row = engine.world.materials[index]
    found = Material(staticFriction=row.static_friction, dynamicFriction=row.dynamic_friction,
                     restitution=row.restitution)
    return None if found == Material() else found


def material_index(physics: Physics, body: Body) -> int:
    """The engine's index of the material ``body`` has; the engine's default is -1 on omi."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        return int(runtime.world.collider_material[runtime.entry(body.uid).index])
    return int(engine.given[body.uid][1])


def material_count(physics: Physics) -> int:
    """How many materials the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        return len(engine.runtime.world.materials)
    return len(engine.world.materials) - 1


def pair_friction(physics: Physics, first: Body, second: Body) -> tuple[float, float] | None:
    """The static and dynamic friction a pair entry gives ``first`` and ``second``; None with none."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        world = runtime.world

        def index(body: Body) -> int:
            return int(world.collider_material[runtime.entry(body.uid).index])

        found = world.pair_friction_for(index(first), index(second))
        return None if found is None else (float(found[0]), float(found[1]))
    found = engine.world.materials.pairing(engine.given[first.uid][1], engine.given[second.uid][1])
    return None if found is None else (float(found[0]), float(found[1]))


def filter_count(physics: Physics) -> int:
    """How many collision filters the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        return len(engine.runtime.world.filters)
    return len(engine._filters)


def joint_count(physics: Physics) -> int:
    """How many joints the engine holds."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        return len(engine.runtime.joints)
    return len(engine._joints)


def step_dt(physics: Physics) -> float:
    """The engine's fixed step, in seconds."""
    return float(physics._engine.step_dt)


def world_position(physics: Physics, body: Body) -> Any:
    """Where the engine holds ``body`` once the commands made so far are taken."""
    settle(physics)
    engine: Any = physics._engine
    if engine.name == 'omi':
        runtime = engine.runtime
        return runtime.world.position[runtime.entry(body.uid).index].copy()
    return engine.live_poses([body.uid])[body.uid].position


def inspect(physics: Physics) -> Any:
    """The omi_physics ``PhysicsWorld`` of an inline ``physics``, each waiting stand-in written.

    Raises RuntimeError for a service whose world steps on its own thread.
    """
    return physics._engine_world()


def slot_of(physics: Physics, body: Body) -> int:
    """The row ``body`` has in the arrays of :func:`inspect`'s world, waiting commands applied first.

    Raises KeyError for a body the world does not hold.
    """
    return physics._slot_of(body)


def body_at(physics: Physics, slot: int) -> Body | None:
    """The body in row ``slot`` of :func:`inspect`'s world, or None for a row no body has."""
    return physics._body_at(slot)


def run(physics: Physics, function: Callable[[Any], Any]) -> concurrent.futures.Future[Any]:
    """Call ``function(world)`` with the omi_physics world on the stepping thread; the future holds its answer.

    A world with no thread running is reached on the calling thread, at once.
    """
    return physics._run(function)
