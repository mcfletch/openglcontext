"""A changing reason, kept as the stretches over which each one held."""
import doctest

import pytest

from OpenGLContext.telemetry import stretches
from OpenGLContext.telemetry.stretches import Held, Stretch


def test_the_examples_in_the_module_hold():
    assert doctest.testmod(stretches).failed == 0


def test_one_reason_throughout_is_one_stretch():
    kept = Stretch(holds=0.5)
    for _ in range(10):
        assert kept.hold('too close', 0.1, at=5.0, gap=2.0) is None
    done = kept.end()
    assert (done.why, done.at, done.fields) == ('too close', 5.0, {'gap': 2.0})
    assert done.seconds == pytest.approx(1.0)


def test_a_reason_that_holds_long_enough_ends_the_one_before():
    kept = Stretch(holds=0.3)
    kept.hold('too close', 1.0, at=0.0)
    ended = [kept.hold('lane not clear', 0.1, at=10.0) for _ in range(3)]
    assert ended[:2] == [None, None]
    assert ended[2].why == 'too close'
    assert kept.open.why == 'lane not clear' and kept.open.at == 10.0


def test_a_reason_that_goes_back_sooner_is_folded_into_the_stretch():
    kept = Stretch(holds=0.5)
    kept.hold('too close', 1.0, at=0.0)
    kept.hold('lane not clear', 0.2, at=1.0)
    kept.hold('too close', 0.1, at=2.0)
    done = kept.end()
    assert done.why == 'too close' and done.also == {'lane not clear'}
    assert done.seconds == pytest.approx(1.3)


def test_a_stretch_shorter_than_the_hold_is_none():
    kept = Stretch(holds=1.0)
    kept.hold('too close', 0.5)
    assert kept.end() is None


def test_a_stretch_is_announced_once_it_has_held():
    kept = Stretch(holds=0.3)
    kept.hold('refused', 0.2)
    assert not kept.announce()
    kept.hold('refused', 0.2)
    assert kept.announce()
    assert not kept.announce()


def test_a_step_backwards_in_time_adds_nothing():
    kept = Stretch(holds=0.0)
    kept.hold('too close', -1.0)
    assert kept.end().seconds == 0.0


def test_where_a_stretch_began_is_optional():
    assert Held('too close').at == 0.0
