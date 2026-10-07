"""X3D's event utilities and KeySensor, as the engine runs them

The behaviours are pyvrml97's (:mod:`vrml.x3d.runtime`,
:mod:`vrml.x3d.followers`). Each timed node here is :class:`EngineTimed`, on
the engine's clock (:func:`~OpenGLContext.events.systemtime.systemTime`)
whether or not it is in a scene. Each follower, once bound to a context,
moves a step each frame through the context's render queue while it is
moving (:class:`Ticked`); a `TimeTrigger` sends the engine's time; a `KeySensor`
observes every keyboard event of each context it is bound to
(:meth:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin.observeEvents`),
under X3D's names for the keys (:func:`x3d_key`), and a `StringSensor` every
character typed (`keypress` events). A `LoadSensor` is polled by each
context's time manager (:class:`Polled`), as the engine's `TimeSensor` is.
"""
from __future__ import annotations

from typing import Any, Optional

import weakref

from vrml.x3d import followers, loadsensor, runtime, timing

from OpenGLContext.events import systemtime
from OpenGLContext.events.renderqueue import DEFER

__all__ = ['ColorChaser', 'ColorDamper', 'CoordinateChaser', 'CoordinateDamper', 'ENGINE_KEYS',
           'EngineTimed', 'KeySensor', 'LoadSensor', 'OrientationChaser', 'OrientationDamper', 'PositionChaser',
           'Polled', 'Polling', 'PositionChaser2D', 'PositionDamper', 'PositionDamper2D', 'ScalarChaser',
           'ScalarDamper', 'StringSensor', 'TexCoordChaser2D', 'TexCoordDamper2D', 'Ticked',
           'TimeTrigger', 'x3d_key']

#: The engine's names for the keys X3D names otherwise.
ENGINE_KEYS = {
    **{'<F%d>' % number: 'F%d' % number for number in range(1, 13)},
    '<home>': 'HOME', '<end>': 'END', '<pageup>': 'PGUP', '<pagedown>': 'PGDN',
    '<up>': 'UP', '<down>': 'DOWN', '<left>': 'LEFT', '<right>': 'RIGHT',
    '<shift>': 'SHIFT', '<ctrl>': 'CONTROL', '<alt>': 'ALT',
    '<return>': '\n', '<tab>': '\t', '<backspace>': '\b', '<delete>': '\x7f',
    '<escape>': '\x1b',
}


def x3d_key(name: str) -> Optional[str]:
    """X3D's name for the engine's key `name`; None for one X3D does not report"""
    found = ENGINE_KEYS.get(name)
    if found is not None:
        return found
    return name if len(name) == 1 else None


class Polling:
    """A node as one of a time manager's generators, holding neither

    Each poll calls the node's ``advance`` with the engine's time; a node
    that has been collected is removed from the manager.
    """

    def __init__(self, node: Any, manager: Any) -> None:
        self.node = weakref.ref(node)
        self.manager = weakref.ref(manager)

    def poll(self, realTime: float) -> int:
        """Advance the node to `realTime`; how many events it sent (0 or 1)"""
        node = self.node()
        if node is None:
            manager = self.manager()
            if manager is not None:
                manager.removeEventGenerator(self)
            return 0
        return int(node.advance(realTime))


class Polled:
    """A node polled by the time manager of each context it is bound to"""

    def bind(self, context: Any) -> bool:
        """Be polled by `context`'s time manager"""
        manager = context.getTimeManager()
        polled = self.__dict__.setdefault('_polledBy', weakref.WeakSet())
        if manager not in polled:
            polled.add(manager)
            manager.addEventGenerator(Polling(self, manager))
        return True


class EngineTimed(timing.Timed):
    """A node timed on the engine's clock"""

    def now(self) -> float:
        """The engine's time, in seconds"""
        return systemtime.systemTime()


class TimeTrigger(EngineTimed, runtime.TimeTrigger):
    """Sends the engine's time for each boolean it receives"""


class KeySensor(runtime.KeySensor):
    """The keys of each context the sensor is bound to"""

    def bind(self, context: Any) -> bool:
        """Observe `context`'s keyboard events while this sensor lives"""
        context.observeEvents('keyboard', self.onKeyboard)
        return True

    def onKeyboard(self, event: Any) -> None:
        """A keyboard event, sent on under its X3D name"""
        name = x3d_key(event.name)
        if name is None:
            return
        if event.state:
            self.keyDown(name)
        else:
            self.keyUp(name)


class StringSensor(runtime.StringSensor):
    """The characters typed into each context the sensor is bound to"""

    def bind(self, context: Any) -> bool:
        """Observe `context`'s character input while this sensor lives"""
        context.observeEvents('keypress', self.onKeypress)
        return True

    def onKeypress(self, event: Any) -> None:
        """A character typed, sent on as X3D's character"""
        character = x3d_key(event.name)
        if character is not None and character not in runtime.ACTION_KEYS \
                and character not in runtime.MODIFIER_KEYS:
            self.typed(character)


class Ticked(EngineTimed):
    """A follower moved each frame, on the engine's clock, while it is moving

    Bound to contexts, it queues a step on each one's render queue when it
    starts to move; each step asks to be made again on that context's next
    frame until the follower comes to rest, and asks that context for a
    frame. Stepping twice in a frame moves it once: a chaser's place is a
    function of the time, and a damper's next step is from where it is now.
    """

    advance: Any
    moving: Any

    def bind(self, context: Any) -> bool:
        """Tick through `context`, starting now where the follower is already moving"""
        contexts = self.__dict__.setdefault('_contexts', [])
        if not any(reference() is context for reference in contexts):
            contexts.append(weakref.ref(context))
        if self.advance(self.now()):
            self.wake()
        return True

    def _live(self) -> "list[Any]":
        return [found for found in (reference() for reference in
                                    self.__dict__.get('_contexts', ())) if found is not None]

    def wake(self) -> None:
        """Queue a step on each bound context that has none queued"""
        queued: "weakref.WeakSet[Any]" = self.__dict__.setdefault('_queued', weakref.WeakSet())
        for context in self._live():
            if context not in queued:
                queued.add(context)
                context.renderQueue.call(self.tick, context)

    def tick(self, context: Any) -> Any:
        """One frame's step through `context`; DEFER while the follower is still moving"""
        moving = self.advance(self.now())
        context.triggerRedraw(1)
        if moving:
            return DEFER
        self.__dict__['_queued'].discard(context)
        return None


class ColorChaser(Ticked, followers.ColorChaser):
    """A colour chased on the engine's clock"""


class ColorDamper(Ticked, followers.ColorDamper):
    """A colour damped on the engine's clock"""


class CoordinateChaser(Ticked, followers.CoordinateChaser):
    """Points chased on the engine's clock"""


class CoordinateDamper(Ticked, followers.CoordinateDamper):
    """Points damped on the engine's clock"""


class OrientationChaser(Ticked, followers.OrientationChaser):
    """A rotation chased on the engine's clock"""


class OrientationDamper(Ticked, followers.OrientationDamper):
    """A rotation damped on the engine's clock"""


class PositionChaser(Ticked, followers.PositionChaser):
    """A position chased on the engine's clock"""


class PositionDamper(Ticked, followers.PositionDamper):
    """A position damped on the engine's clock"""


class PositionChaser2D(Ticked, followers.PositionChaser2D):
    """A 2D position chased on the engine's clock"""


class PositionDamper2D(Ticked, followers.PositionDamper2D):
    """A 2D position damped on the engine's clock"""


class ScalarChaser(Ticked, followers.ScalarChaser):
    """A number chased on the engine's clock"""


class ScalarDamper(Ticked, followers.ScalarDamper):
    """A number damped on the engine's clock"""


class TexCoordChaser2D(Ticked, followers.TexCoordChaser2D):
    """Texture coordinates chased on the engine's clock"""


class TexCoordDamper2D(Ticked, followers.TexCoordDamper2D):
    """Texture coordinates damped on the engine's clock"""


class LoadSensor(Polled, EngineTimed, loadsensor.LoadSensor):
    """A LoadSensor polled by each context it is bound to"""

    def advance(self, now: float) -> bool:
        """Report the children's loading at `now`; whether anything was sent"""
        return self.observe(now)
