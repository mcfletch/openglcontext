"""Collision subscriptions: a callback for a body's collisions, on the main thread.

A :class:`CollisionEvents` belongs to each
:class:`~OpenGLContext.physics.manager.PhysicsManager`, as ``manager.events``.
A game subscribes a callback for one body, several bodies or every body::

    def thud(hit):
        audio.play(clip, position=hit.point, gain=min(1.0, hit.approach / 4.0))

    manager.events.subscribe(thud, body=crate, phases=('begin', 'persist'), above=0.5)
    manager.events.subscribe(on_pickup, body=pad, kinds=('trigger',))
    manager.events.subscribe(on_any_hit)                     # every body

and each callback receives one :class:`Collision` per collision, with the
scenegraph objects resolved and the normal turned to face the subscribed body.

The physics world records its events on every step
(:mod:`omi_physics.contactevents`), so a frame that ran four steps delivers
what happened on all four. The manager delivers them once a frame, after it has
written the frame's poses to the scene, in step order and on the thread that
called :meth:`~OpenGLContext.physics.manager.PhysicsManager.advance`. A
threaded manager delivers the events published with the snapshot it adopts, so
the two behave the same.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from itertools import chain
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from omi_physics.contactevents import BodyRef, ContactEvent, TriggerEvent

if TYPE_CHECKING:
    from omi_physics.raycast import RayHit
    from omi_physics.world import PhysicsWorld

    from .manager import PhysicsManager

__all__ = ['Collision', 'CollisionEvents', 'HitEvent', 'Subscription']

log = logging.getLogger(__name__)

KINDS = ('contact', 'trigger', 'hit')
#: What a subscription receives when it names no phases: the first phase of
#: each kind, which is a meeting rather than a continuing one.
STARTING_PHASES = ('begin', 'enter')
_PHASES = {
    'contact': ('begin', 'persist', 'end'),
    'trigger': ('enter', 'stay', 'exit'),
    'hit': ('begin',),
}
_STATIC = 0
_ZERO = np.zeros(3)
_ZERO.flags.writeable = False


@dataclass(frozen=True, slots=True)
class HitEvent:
    """A hitscan shot reported with :meth:`CollisionEvents.report_hit`."""
    target: BodyRef
    source: BodyRef | None
    point: np.ndarray
    #: The direction the round travelled, unit length.
    direction: np.ndarray
    speed: float
    impulse: float
    payload: Any
    step: int
    time: float

    kind = 'hit'
    phase = 'begin'


@dataclass(frozen=True, slots=True)
class Collision:
    """One collision, as the subscribed body sees it.

    ``normal`` points from ``other`` into ``body``: the direction ``body`` was
    pushed. For a trigger event it is zero, since an overlap has no direction,
    and ``point`` is where the body that entered was on the step it did.
    """
    #: ``'contact'``, ``'trigger'`` or ``'hit'``.
    kind: str
    #: ``'begin'``, ``'persist'`` or ``'end'`` for a contact; ``'enter'``,
    #: ``'stay'`` or ``'exit'`` for a trigger; ``'begin'`` for a hit.
    phase: str
    #: The subscribed side: the :class:`PhysicsBody` registered with the
    #: manager, or the :class:`~omi_physics.contactevents.BodyRef` of a body
    #: added to the world without one.
    body: Any
    #: The other side, resolved the same way. For a hit, the ``source`` given
    #: to :meth:`CollisionEvents.report_hit`, which may be None.
    other: Any
    #: The ``Transform`` each side drives, or None.
    node: Any
    other_node: Any
    point: np.ndarray
    normal: np.ndarray
    #: Closing speed along the normal before the solve, m/s. The round's
    #: speed for a hit; zero for a trigger and on an ``'end'``.
    approach: float
    #: Normal impulse, N·s: what a breaking strength compares against.
    impulse: float
    #: Friction impulse, N·s, and sliding speed, m/s: scraping.
    friction_impulse: float
    slip: float
    #: Deepest penetration, m.
    depth: float
    #: Simulation time of the step, s: when to schedule a sound.
    time: float
    #: False where a contact filter let the pair pass through each other.
    solved: bool
    #: On an ``'end'``, ``'separated'`` or ``'removed'``.
    reason: str | None
    #: Whatever the shooter passed to :meth:`CollisionEvents.report_hit`.
    payload: Any
    #: The event this was made from: a
    #: :class:`~omi_physics.contactevents.ContactEvent`,
    #: :class:`~omi_physics.contactevents.TriggerEvent` or :class:`HitEvent`.
    event: Any = field(repr=False)


@dataclass(eq=False)
class Subscription:
    """A callback and what it asked to hear. :meth:`cancel` stops it."""
    callback: Callable[[Collision], Any]
    #: The bodies it covers, or None for every body.
    bodies: set[BodyRef] | None
    among: frozenset[BodyRef] | None
    kinds: frozenset[str]
    phases: frozenset[str]
    above: float
    skip_static: bool
    #: False once cancelled, or once every body it covered has been removed.
    active: bool = True
    _detach: Callable[[], None] | None = field(default=None, repr=False)

    def cancel(self) -> None:
        """Stop calling the callback. Cancelling twice is harmless."""
        if self._detach is not None:
            self._detach()
            self._detach = None
        self.active = False

    def wants(self, kind: str, phase: str) -> bool:
        """Whether this subscription asked for ``kind`` events in ``phase``."""
        return kind in self.kinds and phase in self.phases


class CollisionEvents:
    """The subscriptions of one physics manager, and their delivery.

    Callbacks are held strongly, so a lambda subscribed here is called; the
    :class:`Subscription` returned by :meth:`subscribe` is how one is let go.
    """

    def __init__(self, manager: PhysicsManager) -> None:
        self.manager = manager
        self._by_body: dict[BodyRef, list[Subscription]] = {}
        self._everything: list[Subscription] = []
        self._hits: list[HitEvent] = []
        #: Whether anything has subscribed, so the events the manager drains
        #: from the world each frame are dispatched here.
        self.draining = False

    @property
    def world(self) -> PhysicsWorld:
        """The manager's physics world."""
        return self.manager.world

    # -- subscribing -------------------------------------------------------
    def subscribe(self, callback: Callable[[Collision], Any], *, body: Any = None,
                  among: Any = None, kinds: Iterable[str] = ('contact',),
                  phases: Iterable[str] | None = None, above: float = 0.0,
                  skip_static: bool = False, immediate: bool = False
                  ) -> Subscription:
        """Call ``callback(collision)`` for each matching collision; return the :class:`Subscription`.

        ``body`` is a :class:`PhysicsBody`, the ``Transform`` one drives, a
        :class:`~omi_physics.contactevents.BodyRef`, a body index, or an
        iterable of any of them. None subscribes to every body. A pair whose
        two bodies are both covered is delivered once, turned to face the
        lower-indexed of the two.

        ``among`` narrows the other side to those bodies, named the same way:
        "did I hit one of these".

        ``kinds`` is any of ``'contact'``, ``'trigger'`` and ``'hit'``.
        ``phases`` is any of ``'begin'``, ``'persist'`` and ``'end'`` for
        contacts, ``'enter'``, ``'stay'`` and ``'exit'`` for triggers; left
        out, it is ``'begin'`` and ``'enter'``. Asking for ``'persist'`` or
        ``'stay'`` makes the world record them on every step for every
        touching pair it reports, which costs an object per pair per step.

        ``above`` is the closing speed, in m/s, a ``'begin'`` or ``'persist'``
        contact must exceed to be delivered. A body resting on the floor
        closes on it by about ``g·dt`` on every step (0.08 m/s at 120 Hz), so a
        landing sound wants ``above`` past that. An ``'end'`` always passes.

        ``skip_static`` leaves out collisions with static bodies: what a body
        hit rather than what it landed on.

        ``immediate`` calls ``callback`` inside the physics step, before the
        next one, for logic that must act between steps. The rules of
        :meth:`~omi_physics.world.PhysicsWorld.add_contact_listener` apply: the
        callback may change the world and must not touch the scenegraph.
        Contacts only; refused by a threaded manager, whose steps run on
        another thread.

        A subscription on bodies ends when the last of them is removed, after
        its ``'end'`` events are delivered.
        """
        kinds = frozenset(kinds)
        unknown = kinds - set(KINDS)
        if unknown:
            raise ValueError('unknown collision kinds %s; choose from %s'
                             % (sorted(unknown), KINDS))
        phases = frozenset(STARTING_PHASES if phases is None else phases)
        known = {phase for kind in kinds for phase in _PHASES[kind]}
        if not phases & known:
            raise ValueError('none of the phases %s belong to the kinds %s'
                             % (sorted(phases), sorted(kinds)))
        refs = None if body is None else set(self.resolve(body))
        subscription = Subscription(
            callback, refs, None if among is None else frozenset(self.resolve(among)),
            kinds, phases, float(above), bool(skip_static))
        if immediate:
            self._check_immediate(subscription)
        # Flags first, so the listener an immediate subscription adds finds
        # the world already recording what it asked about.
        self._report(refs, phases)
        if immediate:
            self._listen(subscription)
        else:
            self._index(subscription)
        return subscription

    def resolve(self, target: Any) -> list[BodyRef]:
        """The :class:`BodyRef` of each body ``target`` names.

        Accepts what :meth:`subscribe`'s ``body`` accepts.
        """
        world = self.world
        if isinstance(target, BodyRef):
            return [target]
        if isinstance(target, (int, np.integer)):
            return [world.ref(int(target))]
        index = getattr(target, 'index', None)
        if index is not None and hasattr(target, 'register'):
            return [world.ref(index)]
        found = self.manager.body_for(target)
        if found is not None and found.index is not None:
            return [world.ref(found.index)]
        if isinstance(target, Iterable) and not isinstance(target, (str, bytes)):
            return [ref for item in target for ref in self.resolve(item)]
        raise TypeError('%r names no body in this physics world' % (target,))

    def _index(self, subscription: Subscription) -> None:
        """File ``subscription`` under each body it covers, for :meth:`dispatch`."""
        self.draining = True
        if subscription.bodies is None:
            self._everything.append(subscription)
        else:
            for ref in subscription.bodies:
                self._by_body.setdefault(ref, []).append(subscription)
        subscription._detach = lambda: self._drop(subscription)

    def _report(self, refs: set[BodyRef] | None, phases: frozenset[str]) -> None:
        """Have the world record what a new subscription asks about."""
        world = self.world
        with self.manager.with_world():
            if refs is None:
                world.contact_reporting = 'all'
            else:
                for ref in refs:
                    world.report_contacts(ref.index)
                if world.contact_reporting == 'off':
                    world.contact_reporting = 'flagged'
            if phases & {'persist', 'stay'}:
                world.report_persist = True

    def _check_immediate(self, subscription: Subscription) -> None:
        """Refuse an immediate subscription this manager cannot run."""
        if not self.manager.steps_on_this_thread:
            raise ValueError('an immediate subscription would run on the physics '
                             'thread; use world.add_contact_listener for that')
        if subscription.kinds != {'contact'}:
            raise ValueError('an immediate subscription hears contacts only')

    def _listen(self, subscription: Subscription) -> None:
        """Run ``subscription`` as a contact listener inside the step."""

        def listener(event: ContactEvent) -> None:
            for heard, side in self._audience(event, (subscription,)):
                self._call(heard, self._collision(event, side))

        world = self.world
        world.add_contact_listener(listener)
        subscription._detach = lambda: world.remove_contact_listener(listener)

    def _drop(self, subscription: Subscription) -> None:
        """Take ``subscription`` out of the index."""
        if subscription in self._everything:
            self._everything.remove(subscription)
        for ref in list(subscription.bodies or ()):
            listed = self._by_body.get(ref)
            if listed and subscription in listed:
                listed.remove(subscription)
                if not listed:
                    del self._by_body[ref]

    # -- hits ----------------------------------------------------------------
    def report_hit(self, hit: RayHit, *, source: Any = None, direction: Any = None,
                   impulse: float = 0.0, speed: float = 0.0,
                   payload: Any = None) -> HitEvent:
        """Deliver a hitscan hit to the struck body's subscribers, and push it.

        ``hit`` is what :func:`omi_physics.raycast.raycast` returned. The
        struck body's subscriptions that ask for ``'hit'`` receive a
        :class:`Collision` with ``kind='hit'`` and ``phase='begin'``, turned
        to face it the same way a contact is: ``normal`` is the direction the
        round travelled.

        ``source`` is the shooter, named as :meth:`subscribe` names a body, or
        None. ``direction`` is the round's heading; left out, it is taken from
        the surface normal the ray met. ``impulse`` is applied to the body at
        the hit point, in N·s along ``direction``, and ``speed`` is reported
        as the event's ``approach``. ``payload`` is handed to the subscriber
        as it is: the weapon, the damage, the team.

        The event is delivered with the next frame's dispatch, ahead of that
        frame's contacts. On a :class:`PhysicsManager` those all happened
        after the hit; a threaded manager's frame can also carry contacts from
        ticks published before it. The impulse is applied under the manager's
        :meth:`~OpenGLContext.physics.manager.PhysicsManager.with_world`.
        Returns the event.
        """
        world = self.world
        target = world.ref(hit.body)
        heading = -np.asarray(hit.normal, dtype='d') if direction is None \
            else np.asarray(direction, dtype='d')
        length = float(np.linalg.norm(heading))
        heading = heading / length if length > 0.0 else heading
        point = np.asarray(hit.point, dtype='d')
        if impulse:
            push = heading * float(impulse)
            with self.manager.with_world():
                world.apply_impulse(hit.body, push)
                arm = point - world.position[hit.body]
                world.apply_angular_impulse(hit.body, np.cross(arm, push))
        shooter = None if source is None else self.resolve(source)[0]
        event = HitEvent(target, shooter, point, heading, float(speed),
                         float(impulse), payload, world.step_count, world.time)
        if self.draining:
            self._hits.append(event)
        return event

    # -- delivery ------------------------------------------------------------
    def dispatch(self, events: Iterable[Any]) -> None:
        """Call the subscribers of each event in ``events``, in order.

        Queued hits go first. Subscriptions whose bodies have all left the
        world are ended once their events have been delivered.
        """
        hits, self._hits = self._hits, []
        for batch in (hits, events):
            for event in batch:
                for subscription, side in self._audience(event):
                    self._call(subscription, self._collision(event, side))
        self._prune()

    def _audience(self, event: Any, pool: Iterable[Subscription] | None = None
                  ) -> list[tuple[Subscription, int]]:
        """Who hears ``event``, and from which side (0 or 1) of it.

        ``pool`` limits the answer to those subscriptions; otherwise every
        subscription filed under either body, and every world-wide one, is
        considered. A subscription covering both sides hears the first.
        """
        sides = self._sides(event)
        heard: list[tuple[Subscription, int]] = []
        seen: set[int] = set()
        for side, ref in enumerate(sides):
            if ref is None:
                continue
            candidates = pool if pool is not None else chain(
                self._by_body.get(ref, ()), self._everything)
            for subscription in candidates:
                if id(subscription) in seen or not subscription.active:
                    continue
                if subscription.bodies is not None and ref not in subscription.bodies:
                    continue
                if self._passes(subscription, event, sides[1 - side]):
                    seen.add(id(subscription))
                    heard.append((subscription, side))
        return heard

    @staticmethod
    def _sides(event: Any) -> tuple[BodyRef | None, BodyRef | None]:
        """The two bodies of ``event``; a hit is heard only by its target."""
        if isinstance(event, ContactEvent):
            return event.a, event.b
        if isinstance(event, TriggerEvent):
            return event.trigger, event.other
        return event.target, None

    def _passes(self, subscription: Subscription, event: Any,
                other: BodyRef | None) -> bool:
        """Whether ``event`` is one ``subscription`` asked for, from its side."""
        if not subscription.wants(event.kind, event.phase):
            return False
        if subscription.among is not None and other not in subscription.among:
            return False
        if (subscription.skip_static and other is not None
                and self._is_static(other)):
            return False
        if event.phase in ('begin', 'persist') and event.kind == 'contact':
            return bool(event.approach > subscription.above)
        return True

    def _is_static(self, ref: BodyRef) -> bool:
        """Whether ``ref`` is a static body; a removed one no longer is anything."""
        world = self.world
        return world.alive(ref) and int(world.motion_type[ref.index]) == _STATIC

    def _collision(self, event: Any, side: int) -> Collision:
        """``event`` as seen from its ``side``."""
        if isinstance(event, ContactEvent):
            mine, theirs = (event.a, event.b) if side == 0 else (event.b, event.a)
            # The event's normal runs from a to b, pushing b; a is pushed back.
            normal = -event.normal if side == 0 else event.normal
            return self._build(event, mine, theirs, event.point, normal,
                               event.approach, event.impulse, event.friction_impulse,
                               event.slip, event.depth, event.solved, event.reason, None)
        if isinstance(event, TriggerEvent):
            mine, theirs = ((event.trigger, event.other) if side == 0
                            else (event.other, event.trigger))
            return self._build(event, mine, theirs, event.point, _ZERO, 0.0, 0.0,
                               0.0, 0.0, 0.0, True, None, None)
        return self._build(event, event.target, event.source, event.point,
                           event.direction, event.speed, event.impulse, 0.0, 0.0,
                           0.0, True, None, event.payload)

    def _build(self, event: Any, mine: BodyRef, theirs: BodyRef | None,
               point: np.ndarray, normal: np.ndarray, approach: float,
               impulse: float, friction: float, slip: float, depth: float,
               solved: bool, reason: str | None, payload: Any) -> Collision:
        body = self.manager.handle(mine)
        other = None if theirs is None else self.manager.handle(theirs)
        return Collision(
            event.kind, event.phase, body, other, getattr(body, 'transform', None),
            getattr(other, 'transform', None), point, normal, approach, impulse,
            friction, slip, depth, event.time, solved, reason, payload, event)

    @staticmethod
    def _call(subscription: Subscription, collision: Collision) -> None:
        """Call one subscriber, logging rather than raising what it raises."""
        try:
            subscription.callback(collision)
        except Exception:
            log.exception('collision callback %r failed on %r',
                          subscription.callback, collision)

    def _prune(self) -> None:
        """End the subscriptions whose bodies have all been removed."""
        world = self.world
        for ref in [ref for ref in self._by_body if not world.alive(ref)]:
            for subscription in self._by_body.pop(ref):
                if subscription.bodies is not None:
                    subscription.bodies.discard(ref)
                    if not subscription.bodies:
                        subscription.active = False
