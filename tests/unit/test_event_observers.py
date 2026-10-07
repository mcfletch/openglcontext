"""An observer sees every event of a type, whatever handles it.

``observeEvents`` is for something that watches a whole stream -- an X3D
``KeySensor`` hears every key, including ones a program has bound to its own
handlers -- rather than taking part in dispatch. It is told of each event
before the handlers are, and is held weakly, as handlers are.
"""
import gc

import pytest

from OpenGLContext.events import keyboardevents
from OpenGLContext.events.eventhandlermixin import EventHandlerMixin
from OpenGLContext.interactivecontext import InteractiveContext


class _Host(EventHandlerMixin):
    drawing = False

    def __init__(self):
        self.initializeEventManagers()


@pytest.fixture
def host():
    _Host.EventManagerClasses = InteractiveContext.EventManagerClasses
    return _Host()


def key(name, state=1):
    event = keyboardevents.KeyboardEvent()
    event.name = name
    event.state = state
    return event


class Watcher:
    def __init__(self):
        self.seen = []

    def watch(self, event):
        self.seen.append((event.name, event.state))


class TestObservers:
    def test_an_observer_sees_every_event_of_its_type(self, host):
        watcher = Watcher()
        host.observeEvents('keyboard', watcher.watch)
        host.ProcessEvent(key('a'))
        host.ProcessEvent(key('a', 0))
        assert watcher.seen == [('a', 1), ('a', 0)]

    def test_it_sees_events_a_handler_takes(self, host):
        watcher, handled = Watcher(), Watcher()
        host.addEventHandler('keyboard', name='q', state=1, function=handled.watch)
        host.observeEvents('keyboard', watcher.watch)
        host.ProcessEvent(key('q'))
        assert watcher.seen == handled.seen == [('q', 1)]

    def test_it_sees_no_other_type(self, host):
        watcher = Watcher()
        host.observeEvents('keypress', watcher.watch)
        host.ProcessEvent(key('a'))
        assert watcher.seen == []

    def test_it_is_held_weakly(self, host):
        watcher = Watcher()
        host.observeEvents('keyboard', watcher.watch)
        del watcher
        gc.collect()
        host.ProcessEvent(key('a'))
        assert host.observersOf('keyboard') == []

    def test_it_can_stop(self, host):
        watcher = Watcher()
        host.observeEvents('keyboard', watcher.watch)
        host.observeEvents('keyboard', watcher.watch, stop=True)
        host.ProcessEvent(key('a'))
        assert watcher.seen == []

    def test_observing_twice_is_once(self, host):
        watcher = Watcher()
        host.observeEvents('keyboard', watcher.watch)
        host.observeEvents('keyboard', watcher.watch)
        host.ProcessEvent(key('a'))
        assert watcher.seen == [('a', 1)]
