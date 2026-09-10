"""An event remembers where it has been, and that is what breaks ROUTE cycles.

``vrml.route.ROUTE._forward`` accepts any event object offering ``visited``: it
asks whether a destination field has already been reached on this event and
stops when it has.  An event whose record of that is write-only answers "no"
every time, so a cycle of ROUTEs is traversed until the interpreter runs out of
stack.
"""

import pytest
from vrml import fieldtypes, node, protofunctions
from vrml.route import ROUTE

from OpenGLContext.events.event import Event


class Relay(node.Node):
    """A node with one routable float, so two of them can make a cycle."""

    PROTO = 'Relay'
    value = fieldtypes.SFFloat('value', 1, 0.0)


class TestWhatVisitedAnswers:
    def test_an_unvisited_key_is_none(self):
        assert Event().visited(('node', 'field')) is None

    def test_registering_answers_what_was_there_before(self):
        event = Event()
        assert event.visited(('node', 'field'), 1) is None

    def test_a_visited_key_answers_what_was_registered(self):
        event = Event()
        event.visited(('node', 'field'), 1)
        assert event.visited(('node', 'field')) == 1

    def test_keys_are_kept_apart(self):
        event = Event()
        event.visited(('node', 'one'), 1)
        assert event.visited(('node', 'two')) is None


def test_a_cycle_of_routes_stops_instead_of_going_round_for_ever():
    """Two nodes routed to each other, with one of our events travelling."""
    first, second = Relay(), Relay()
    # Both routes are held: a ROUTE connects itself to the dispatcher by weak
    # reference, so one nothing refers to is collected before it can fire.
    outward = ROUTE(first, 'value', second, 'value')
    back = ROUTE(second, 'value', first, 'value')
    assert back.destination is first
    field = protofunctions.getField(first, 'value')
    try:
        outward.forward(signal=('set', field), sender=first,
                        event=Event(), value=1.0)
    except RecursionError:
        pytest.fail('the event never records where it has been, so the cycle '
                    'is traversed until the stack runs out')
    assert second.value == 1.0
