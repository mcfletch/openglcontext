"""A frame asked for at a time, for what changes with time alone.

Headless: the context's own bookkeeping, against the session clock.
"""
from OpenGLContext.context import Context
from OpenGLContext.events import systemtime


def _context():
    return Context.__new__(Context)


def test_nothing_is_owed_until_asked():
    assert not _context().redrawFallsDue()


def test_a_frame_asked_for_later_is_not_owed_yet():
    context = _context()
    context.redrawAt(systemtime.systemTime() + 100.0)
    assert not context.redrawFallsDue()


def test_the_earliest_time_asked_for_stands():
    context = _context()
    now = systemtime.systemTime()
    context.redrawAt(now + 100.0)
    context.redrawAt(now + 50.0)
    context.redrawAt(now + 75.0)
    assert context.redrawDue == now + 50.0


def test_a_frame_whose_time_has_come_is_owed_once():
    context = _context()
    context.redrawAt(systemtime.systemTime() - 1.0)
    assert context.redrawFallsDue()
    assert not context.redrawFallsDue()
