"""X3D's event utilities and KeySensor, as the engine runs them

The behaviours are pyvrml97's (:mod:`vrml.x3d.runtime`). Here a
`TimeTrigger` sends the engine's time
(:func:`~OpenGLContext.events.systemtime.systemTime`); a `KeySensor`
observes every keyboard event of each context it is bound to
(:meth:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin.observeEvents`),
under X3D's names for the keys (:func:`x3d_key`), and a `StringSensor` every
character typed (`keypress` events).
"""
from __future__ import annotations

from typing import Any, Optional

from vrml.x3d import runtime

from OpenGLContext.events import systemtime

__all__ = ['ENGINE_KEYS', 'KeySensor', 'StringSensor', 'TimeTrigger', 'x3d_key']

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


class TimeTrigger(runtime.TimeTrigger):
    """Sends the engine's time for each boolean it receives"""

    def on_set_boolean(self, _value: Any) -> None:
        self.triggerTime = systemtime.systemTime()


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
