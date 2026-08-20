"""One input event as a plain record, and back again.

Three things want to talk about an input event as *data* rather than as an
object: a telemetry recording writing down what the player did
(:mod:`OpenGLContext.telemetry`), a replay putting it back, and a test script
driving an application from outside it
(:mod:`OpenGLContext.testing.event_injector`).  They share this vocabulary so a
record written by one is understood by the others -- a session recorded from a
game can be replayed by a test, and a test's script can be read by the same
report that reads a session.

A record is a JSON-safe mapping whose ``type`` says which input it is::

    {'type': 'keyboard',    'key': 'w', 'state': 1, 'modifiers': [0, 0, 0]}
    {'type': 'keypress',    'key': 'W', 'modifiers': [1, 0, 0]}
    {'type': 'mousebutton', 'button': 0, 'state': 1, 'x': 100, 'y': 200,
                            'modifiers': [0, 0, 0], 'pick': True}
    {'type': 'mousemove',   'buttons': [0], 'x': 100, 'y': 200,
                            'modifiers': [0, 0, 0], 'pick': True}
    {'type': 'pointer',        'x': 100, 'y': 200}
    {'type': 'pointer-origin'}
    {'type': 'resize',      'width': 800, 'height': 600}

The last three have no event object behind them, because the engine has no
event for them: pointer motion reaches the movement sampler directly (see
:meth:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin.recordPointerMotion`)
and a resize reaches ``OnResize``.  :func:`build` answers ``None`` for those and
:func:`dispatch` delivers them by calling what a backend calls.

``pick`` says the pointer event went to the selection pass, which is the route a
real click takes: it is delivered once the buffer has resolved what is under the
cursor, carrying the node paths with it.  Without the flag the event goes
straight to its manager with no picked paths, which needs no render and reaches
context-level handlers only -- the cheaper choice when a test is about the
handler rather than about the route to it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from OpenGLContext.events.keyboardevents import KeyboardEvent, KeypressEvent
from OpenGLContext.events.mouseevents import MouseButtonEvent, MouseMoveEvent

log = logging.getLogger(__name__)

__all__ = ['KINDS', 'build', 'describe', 'dispatch']

#: Every ``type`` this module understands.
KINDS = ('keyboard', 'keypress', 'mousebutton', 'mousemove',
         'pointer', 'pointer-origin', 'resize')

#: The event classes, by the ``type`` an engine event already calls itself.
_CLASSES = {
    'keyboard': KeyboardEvent,
    'keypress': KeypressEvent,
    'mousebutton': MouseButtonEvent,
    'mousemove': MouseMoveEvent,
}


def _modifiers(event: Any) -> list:
    return [int(bool(flag)) for flag in (event.getModifiers() or (0, 0, 0))]


def describe(event: Any) -> Optional[Dict[str, Any]]:
    """``event`` as a record, or ``None`` if it is not an input event.

    Only what a replay needs to produce the same event again: an event also
    carries the paths a pick resolved, the matrices of the frame it was
    delivered on and the nodes it has visited, none of which is *input* -- they
    are what the engine made of the input, and re-deriving them is the whole
    point of running the session again.
    """
    kind = getattr(event, 'type', None)
    if kind not in _CLASSES:
        return None
    record: Dict[str, Any] = {'type': kind, 'modifiers': _modifiers(event)}
    if kind in ('keyboard', 'keypress'):
        record['key'] = event.name
        if kind == 'keyboard':
            record['state'] = int(event.state)
        return record
    point = event.getPickPoint() or (0.0, 0.0)
    record['x'], record['y'] = point[0], point[1]
    if kind == 'mousebutton':
        record['button'] = int(event.button)
        record['state'] = int(event.state)
    else:
        record['buttons'] = [int(button) for button in event.getButtons()]
    return record


def build(record: Dict[str, Any]) -> Optional[Any]:
    """The engine event ``record`` describes, or ``None`` if it describes none.

    The caller sets ``context`` on what comes back; :func:`dispatch` does.
    """
    factory = _CLASSES.get(str(record.get('type', '')))
    if factory is None:
        return None
    event: Any = factory()
    event.modifiers = tuple(record.get('modifiers') or (0, 0, 0))
    if factory in (KeyboardEvent, KeypressEvent):
        event.name = record.get('key', '')
        if factory is KeyboardEvent:
            event.state = int(record.get('state', 1))
        return event
    event.pickPoint = (float(record.get('x', 0)), float(record.get('y', 0)))
    if factory is MouseButtonEvent:
        event.button = int(record.get('button', 0))
        event.state = int(record.get('state', 1))
    else:
        event.buttons = tuple(record.get('buttons') or ())
    return event


def dispatch(context: Any, record: Dict[str, Any]) -> bool:
    """Deliver ``record`` to ``context`` the way the platform would have.

    Answers whether it was delivered.  A context that has no entry point for
    an input -- a bare one with no movement sampler, for instance -- is a
    ``False`` and a debug line, never an error: a replay is diagnostic
    equipment, and one input it cannot place must not end the session.
    """
    kind = record.get('type')
    if kind == 'pointer':
        return _call(context, 'recordPointerMotion',
                     record.get('x', 0), record.get('y', 0))
    if kind == 'pointer-origin':
        return _call(context, 'forgetPointerOrigin')
    if kind == 'resize':
        return _call(context, 'OnResize',
                     int(record.get('width', 0)), int(record.get('height', 0)))
    event = build(record)
    if event is None:
        log.debug('no input event for %r', kind)
        return False
    event.context = context
    if kind in ('keyboard', 'keypress'):
        return _call(context, 'ProcessEvent', event)
    if record.get('pick'):
        if not _call(context, 'addPickEvent', event):
            return False
        _call(context, 'triggerPick')
        return True
    # No select-render pass ran, so there are no picked node paths; an empty
    # set routes the event to anonymous context-level handlers only.
    event.setObjectPaths([])
    manager = getattr(context, 'getEventManager', lambda kind: None)(kind)
    if manager is None:
        log.debug('no %s manager to deliver to', kind)
        return False
    manager.ProcessEvent(event)
    return True


def _call(context: Any, name: str, *arguments: Any) -> bool:
    """Call one of the context's entry points, if it has it."""
    method = getattr(context, name, None)
    if method is None:
        log.debug('context has no %s to deliver to', name)
        return False
    method(*arguments)
    return True
