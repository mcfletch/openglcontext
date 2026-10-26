"""Standing a world's props up in a physics world, and taking them down again.

A world's boulders are hundreds of bodies and a car touches one of them at a
time; the collision broadphase pays for every one it is holding. So the rule is
the one the ground follows: what is within reach is in the world, and what is
not is taken out again.

:class:`PropSource` is a collider source (:mod:`OpenGLContext.physics.sources`)
whose props near the focus are static bodies of a physics service::

    stones = PropSource(props, reach=60.0)
    physics.add_collider_source(stones, focus=lambda: car.position)

:class:`PropColliders` stands the same bodies up in a plain
:class:`omi_physics.world.PhysicsWorld`, for code with no service.

A prop's body comes from the prop's own measurements rather than from the mesh
in a tile. Tile geometry is level-of-detail geometry that arrives and leaves as
a camera moves, and a collider that came and went with it would be a rock a car
drives through at the moment the tile behind it swaps. The
:class:`~OpenGLContext.scenegraph.props.Prop` records travel in the tileset's
``extras``, which is the same reason the road does.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics import model

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.sources import Addition, Changes

if TYPE_CHECKING:
    from omi_physics.world import PhysicsWorld

    from OpenGLContext.scenegraph.props import Prop

__all__ = ['PropColliders', 'PropSource', 'REACH_METRES', 'SETTLED_METRES']

#: How far from the focus props are kept, in metres. Past this nothing is going
#: to reach one before the next update does.
REACH_METRES = 220.0

#: How far the focus moves before the set is chosen again, in metres. A stale
#: set is not a wrong one -- reach is generous -- so re-choosing every frame is
#: work for nothing.
SETTLED_METRES = 20.0


class PropSource:
    """Static bodies for the props near the focus, added and removed as it moves.

    A :class:`~OpenGLContext.physics.sources.ColliderSource`, keyed by each
    prop's index in ``props``.

    :param props: every :class:`~OpenGLContext.scenegraph.props.Prop` in the
        world. Held as given; nothing here writes to it.
    :param reach: how far from the focus props are kept, in metres.
    :param settled: how far the focus may move before the set is re-chosen.

    Props of one shape and size share one
    :class:`~OpenGLContext.physics.proxy.Proxy`, so the world holds that shape
    once.
    """

    def __init__(self, props: Sequence[Prop], reach: float = REACH_METRES,
                 settled: float = SETTLED_METRES) -> None:
        self.props = list(props)
        self.reach = float(reach)
        self.settled = float(settled)
        #: The props with a body now, in the order of ``props``.
        self.standing: list[Prop] = []
        #: The indices with a body, in the order they were stood up.
        self._held: dict[int, None] = {}
        self._at: np.ndarray | None = None
        self._proxies: dict[tuple[str, float, float], Proxy] = {}
        self._plan = np.asarray(
            [[p.position[0], p.position[2]] for p in self.props],
            dtype='d').reshape(-1, 2)

    @classmethod
    def baked(cls, extras: Any, channel: str, base: str, **named: Any) -> PropSource:
        """A source for the props a baked world carries in ``extras[channel]``.

        ``base`` is the tileset's directory or URL directory; the props are read
        in either form a world carries them
        (:func:`~OpenGLContext.loaders.tiles3d.props.baked_props`), and
        ``named`` is ``reach`` and ``settled`` as for the constructor.
        """
        from OpenGLContext.loaders.tiles3d.props import baked_props
        return cls(baked_props(extras, channel, base), **named)

    def update(self, focus: Sequence[float]) -> Changes:
        """The props to stand up and to take down now that the focus is at ``focus``."""
        at = np.asarray(focus, dtype='d').reshape(-1)[:3]
        if self._at is not None and float(np.hypot(
                at[0] - self._at[0], at[2] - self._at[2])) <= self.settled:
            return Changes()
        self._at = at.copy()
        if not len(self._plan):
            return Changes()
        near = np.nonzero(
            np.hypot(self._plan[:, 0] - at[0], self._plan[:, 1] - at[2])
            <= self.reach)[0]
        wanted = {int(index) for index in near}
        removed = [index for index in self._held if index not in wanted]
        for index in removed:
            del self._held[index]
        fresh = [index for index in sorted(wanted) if index not in self._held]
        self._held.update(dict.fromkeys(fresh))
        added = [self._stand(index) for index in fresh]
        self.standing = [self.props[index] for index in sorted(self._held)]
        return Changes(add=added, remove=removed)

    def clear(self) -> None:
        """Forget every prop, so the next update stands up what is within reach afresh."""
        self._held = {}
        self.standing = []
        self._at = None

    def _stand(self, index: int) -> Addition:
        """One prop as a static body, of the shape the prop says it is.

        A static box or sphere, not the drawn mesh: a triangle mesh per rock
        costs the broad and narrow phases. A ``box`` stops what hits it. A
        ``dome`` is a sphere as wide as the stone, sunk so its top is at the
        stone's height, so a wheel or walker goes over it; a stone taller than
        it is wide has its sphere resting on the ground, top at twice the
        radius.
        """
        prop = self.props[index]
        size = (prop.shape, float(prop.radius), float(prop.height))
        proxy = self._proxies.get(size)
        if proxy is None:
            proxy = self._proxies[size] = (
                Proxy.sphere(prop.radius) if prop.shape == 'dome' else
                Proxy.box((prop.radius * 2.0, prop.height, prop.radius * 2.0)))
        return Addition(index, proxy, tuple(np.asarray(prop.position, dtype='d') + _lift(prop)),
                        orientation=_yaw(prop.yaw))


class PropColliders:
    """The bodies of a :class:`PropSource` in a plain physics world, for code with no service.

    :param world: the physics world the props are added to and removed from.
    :param props: every :class:`~OpenGLContext.scenegraph.props.Prop` in the
        world. Held as given; nothing here writes to it.
    :param reach: how far from the point props are kept, in metres.
    :param settled: how far the point may move before the set is re-chosen.

    Call :meth:`update` with where the thing that might hit one is.
    """

    def __init__(self, world: PhysicsWorld, props: Sequence[Prop],
                 reach: float = REACH_METRES,
                 settled: float = SETTLED_METRES) -> None:
        self.world = world
        self.source = PropSource(props, reach=reach, settled=settled)
        self._bodies: dict[Any, int] = {}

    @classmethod
    def baked(cls, world: PhysicsWorld, extras: Any, channel: str, base: str,
              **named: Any) -> PropColliders:
        """Colliders for the props a baked world carries in ``extras[channel]``,
        read as :meth:`PropSource.baked` reads them."""
        from OpenGLContext.loaders.tiles3d.props import baked_props
        return cls(world, baked_props(extras, channel, base), **named)

    @property
    def props(self) -> list[Prop]:
        """Every prop in the world."""
        return self.source.props

    @property
    def standing(self) -> list[Prop]:
        """The props with a body in the world now."""
        return self.source.standing

    def update(self, position: Sequence[float]) -> None:
        """Hold the props within reach of here, and let go of the rest."""
        changes = self.source.update(position)
        for key in changes.remove:
            self.world.remove_body(self._bodies.pop(key))
        for item in changes.add:
            addition = item if isinstance(item, Addition) else Addition(*item)
            shape = self.world.add_shape(addition.proxy.shape)
            self._bodies[addition.key] = int(self.world.add_body(
                model.Motion(type=model.STATIC), collider=model.Collider(shape=shape),
                position=tuple(addition.position),
                orientation=addition.quaternion() or (0.0, 0.0, 0.0, 1.0)))

    def release(self) -> None:
        """Take every prop out of the physics world."""
        for body in self._bodies.values():
            self.world.remove_body(body)
        self._bodies.clear()
        self.source.clear()


def _lift(prop: Prop) -> np.ndarray:
    """From a prop's foot to the middle of its body."""
    if prop.shape == 'dome':
        return np.array([0.0, min(prop.height - prop.radius, prop.radius), 0.0])
    return np.array([0.0, prop.height / 2.0, 0.0])


def _yaw(angle: float) -> tuple[float, float, float, float]:
    """A rotation about the vertical, as the quaternion the world wants."""
    half = float(angle) / 2.0
    return (0.0, float(np.sin(half)), 0.0, float(np.cos(half)))
