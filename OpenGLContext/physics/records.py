"""The plain data a physics service moves between threads.

Everything here is made of numbers, strings, NumPy arrays and other records, so
the same traffic can cross a thread today and a process boundary later.

:class:`Command`
    One change to the world, from any thread to the worker.
:class:`BodySpec`
    What the worker needs to make one body.
:class:`Snapshot`
    The poses and velocities of the bodies that move, published after a tick.
:class:`PhysicsEvent`
    One contact, trigger or state change, naming bodies by id.
:class:`Step`
    One fixed step, as the step hooks receive it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

import numpy as np
from omi_physics import model

from OpenGLContext.physics.proxy import Proxy

__all__ = ['BodySpec', 'Command', 'PhysicsEvent', 'Snapshot', 'Step']


class Command(NamedTuple):
    """One change to the world.

    ``op`` names the change, ``uid`` the body it is for (0 for the world), and
    ``args`` carries its numbers. ``seq`` is assigned when the command is
    submitted; a snapshot reports the highest ``seq`` it includes, so a reader
    can tell whether a write of its own is in the pose it is looking at.
    """
    op: str
    uid: int
    args: tuple[Any, ...] = ()
    seq: int = 0


@dataclass(frozen=True, slots=True)
class BodySpec:
    """The body ``uid`` to make.

    ``kind`` is ``'static'``, ``'dynamic'``, ``'kinematic'`` or ``'trigger'``.
    ``orientation`` is a unit quaternion ``(x, y, z, w)``. ``material`` is a
    preset or defined name, a :class:`~omi_physics.model.Material`, or None for
    the world's default.
    """
    uid: int
    kind: str
    proxy: Proxy
    motion: model.Motion
    position: tuple[float, ...] = (0.0, 0.0, 0.0)
    orientation: tuple[float, ...] = (0.0, 0.0, 0.0, 1.0)
    material: Any = None
    collision_filter: int = -1
    report: bool = False
    sensor: bool = False


@dataclass(frozen=True, slots=True)
class Step:
    """One fixed step: its length, its index and the simulation time it began at."""
    dt: float
    index: int
    time: float


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The bodies that move, as they stood when it was published.

    Row ``rows[uid]`` of each array is body ``uid``. Static bodies and triggers
    do not move and are not listed. ``axis_angle`` is ``(x, y, z, angle)``;
    ``dynamic`` is false for a kinematic body. ``applied_seq`` is the highest
    command sequence the world had applied.
    """
    version: int
    step: int
    time: float
    applied_seq: int
    rows: dict[int, int]
    position: np.ndarray
    axis_angle: np.ndarray
    linear_velocity: np.ndarray
    angular_velocity: np.ndarray
    awake: np.ndarray
    dynamic: np.ndarray


@dataclass(frozen=True, slots=True)
class PhysicsEvent:
    """One thing that happened in a step, naming bodies by id.

    ``kind`` is ``'contact'``, ``'trigger'``, ``'hit'`` or ``'state'``. For a
    contact ``a`` and ``b`` are the pair with ``normal`` running from ``a`` to
    ``b``; for a trigger ``a`` is the trigger and ``b`` what entered it; for a
    state change (``'sleep'`` or ``'wake'``) ``a`` is the body and ``b`` None.
    ``step`` and ``time`` say when, in the world's own count of steps and
    seconds.
    """
    kind: str
    phase: str
    a: int
    b: int | None
    point: np.ndarray
    normal: np.ndarray
    approach: float
    impulse: float
    friction_impulse: float
    slip: float
    depth: float
    step: int
    time: float
    solved: bool = True
    reason: str | None = None
    payload: Any = field(default=None, compare=False)
