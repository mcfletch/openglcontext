"""The handler table: who hears an event, in the order registered, at a cost set by the event's bodies."""
import numpy as np
import pytest

from OpenGLContext.physics import handlers as handlers_module
from OpenGLContext.physics.handlers import Handler, HandlerTable
from OpenGLContext.physics.records import PhysicsEvent

_ZERO = np.zeros(3)


def event(a, b, kind='contact', phase='begin', approach=1.0):
    return PhysicsEvent(kind, phase, a, b, _ZERO, _ZERO, approach, 0.0, 0.0, 0.0, 0.0, 0, 0.0)


def keep(*functions):
    """The functions, held here so the table's weak references stay alive."""
    return list(functions)


def test_the_audience_is_the_handlers_of_either_body_and_of_every_body_in_order():
    table = HandlerTable()

    def on_a(hit): pass
    def on_all(hit): pass
    def on_b(hit): pass
    def on_other(hit): pass
    def on_trigger(hit): pass

    held = keep(on_a, on_all, on_b, on_other, on_trigger)
    first = table.add(Handler('hit', on_a, bodies=[1]))
    every = table.add(Handler('hit', on_all))
    second = table.add(Handler('hit', on_b, bodies=[2]))
    table.add(Handler('hit', on_other, bodies=[3]))
    table.add(Handler('enter', on_trigger, bodies=[1]))
    assert table.audience(event(1, 2), physics=False) == [(first, 0), (every, 0), (second, 1)]
    assert table.audience(event(2, 1), physics=False) == [(first, 1), (every, 0), (second, 0)]
    assert table.audience(event(1, 2), physics=True) == []
    assert held


def test_a_handler_on_both_bodies_hears_once_and_the_other_filter_holds():
    table = HandlerTable()

    def both(hit): pass
    def only_with_five(hit): pass

    held = keep(both, only_with_five)
    pair = table.add(Handler('hit', both, bodies=[1, 2]))
    table.add(Handler('hit', only_with_five, bodies=[1], other=[5]))
    assert table.audience(event(1, 2), physics=False) == [(pair, 0)]
    assert held


def test_cancelled_forgotten_and_collected_handlers_are_not_heard():
    table = HandlerTable()

    def on_one(hit): pass
    def on_two(hit): pass

    held = keep(on_one)
    one = table.add(Handler('hit', on_one, bodies=[1, 4]))
    table.add(Handler('hit', on_two, bodies=[2]))
    del on_two
    table.prune()
    assert table.audience(event(2, 3), physics=False) == []
    table.forget_body(1)
    assert table.audience(event(1, 3), physics=False) == []
    assert table.audience(event(4, 3), physics=False) == [(one, 0)]
    one.cancel()
    assert table.audience(event(4, 3), physics=False) == []
    assert held


def test_finding_the_audience_costs_what_the_event_names_not_every_handler(check_scaling, monkeypatch):
    calls = [0]
    hears = Handler.hears

    def counted(self, event, side):
        calls[0] += 1
        return hears(self, event, side)

    monkeypatch.setattr(handlers_module.Handler, 'hears', counted)
    rng = np.random.default_rng(3)

    def prepare(n):
        table = HandlerTable()
        functions = []
        for uid in range(n):
            def on_hit(hit): pass
            functions.append(on_hit)
            table.add(Handler('hit', on_hit, bodies=[uid]))
        table.add(Handler('hit', functions[0]))
        pairs = rng.integers(0, n, size=(200, 2))
        events = [event(int(a), int(b)) for a, b in pairs]

        def work():
            calls[0] = 0
            for one in events:
                table.audience(one, physics=False)
            return calls[0]
        work.functions = functions      # the table holds them weakly
        return work

    check_scaling(prepare, n=250, most=1.5, measure='count')
