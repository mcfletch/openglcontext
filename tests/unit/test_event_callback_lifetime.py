"""Registered callbacks are held weakly, and the caller owns the strong reference.

This is deliberate, not a defect: it is what lets a node or a context be
collected without first unbinding every handler it registered. It is also the
usual explanation for "my key binding does nothing and nothing is logged", so
the contract is pinned here -- both halves of it, so that neither the weakness
nor the survival of a properly-held handler can be changed unnoticed.
"""
import gc

import pytest

from OpenGLContext.events import eventmanager


class Recorder:
    """A plain object whose bound method can be registered as a handler."""

    def __init__(self):
        self.seen = []

    def handle(self, event=None):
        self.seen.append(event)


@pytest.fixture
def manager():
    """A bare event manager, with its class-level registrations kept isolated."""
    class Manager(eventmanager.EventManager):
        type = 'test-lifetime'
    yield Manager
    Manager.registerCallback('k', function=None)


def deliver(manager, key='k'):
    """Dispatch one event through the manager's own path; count the handlers hit.

    This goes through ``sendExact`` rather than poking the registration tables,
    so it exercises the same delivery a real event takes.
    """
    from pydispatch import dispatcher
    return len(dispatcher.sendExact((manager.type, 0, key), None, None))


def test_a_handler_held_by_a_live_object_keeps_working(manager):
    recorder = Recorder()
    manager.registerCallback('k', function=recorder.handle)
    assert deliver(manager) == 1
    gc.collect()
    assert deliver(manager) == 1                    # still there after a collection
    assert len(recorder.seen) == 2


def test_a_handler_with_no_owner_is_collected(manager):
    # The classic silent failure: a lambda built inline has no other reference,
    # so it is gone before the first event is ever dispatched.
    manager.registerCallback('k', function=lambda event=None: None)
    gc.collect()
    assert deliver(manager) == 0


def test_keeping_a_reference_is_what_rescues_a_closure(manager):
    seen = []
    handler = lambda event=None: seen.append(event)  # noqa: E731
    kept = [handler]                                 # the caller's strong reference
    manager.registerCallback('k', function=handler)
    del handler
    gc.collect()
    assert deliver(manager) == 1
    assert len(seen) == 1
    assert kept                                      # the reference is the point


def test_dropping_the_owner_unbinds_without_an_explicit_deregister(manager):
    # The reason the weakness exists: an object that goes away takes its
    # handlers with it, so nothing has to unbind them first.
    recorder = Recorder()
    manager.registerCallback('k', function=recorder.handle)
    assert deliver(manager) == 1
    del recorder
    gc.collect()
    assert deliver(manager) == 0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
