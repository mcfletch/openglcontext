"""Things stepped once a frame, and calls made after a delay, on one frame clock."""
import pytest

from OpenGLContext.events.animations import Animations


class Model:
    """Stands for a CharacterModel: something with ``update(dt)``."""

    def __init__(self):
        self.steps = []

    def update(self, dt):
        self.steps.append(dt)


def test_a_model_is_stepped_by_the_time_since_the_last_frame():
    animations = Animations(longest=1.0)
    model = Model()
    animations.animate(model)
    animations.frame(10.0)
    animations.frame(10.25)
    animations.frame(10.5)
    assert model.steps == [0.0, 0.25, 0.25]


def test_a_callable_is_called_with_the_step():
    animations = Animations(longest=1.0)
    seen = []
    animations.animate(seen.append)
    animations.frame(1.0)
    animations.frame(1.5)
    assert seen == [0.0, 0.5]


def test_a_long_frame_is_cut_to_the_longest_step():
    animations = Animations(longest=0.1)
    model = Model()
    animations.animate(model)
    animations.frame(0.0)
    animations.frame(5.0)
    assert model.steps == [0.0, 0.1]


def test_a_stopped_animation_is_no_longer_stepped():
    animations = Animations()
    model = Model()
    handle = animations.animate(model)
    animations.frame(0.0)
    handle.stop()
    handle.stop()
    animations.frame(1.0)
    assert model.steps == [0.0]
    assert not handle.running


def test_frame_answers_whether_anything_is_animating_or_waiting():
    animations = Animations()
    assert animations.frame(0.0) is False
    handle = animations.animate(Model())
    assert animations.frame(0.1) is True
    handle.stop()
    assert animations.frame(0.2) is False
    animations.after(1.0, lambda: None)
    assert animations.frame(0.3) is True


def test_a_delayed_call_is_made_once_its_seconds_have_passed():
    animations = Animations(longest=1.0)
    calls = []
    animations.frame(0.0)
    animations.after(1.0, lambda: calls.append('rested'))
    animations.frame(0.5)
    assert calls == []
    animations.frame(1.0)
    animations.frame(1.6)
    assert calls == ['rested']
    animations.frame(3.0)
    assert calls == ['rested']


def test_a_cancelled_delay_is_never_made():
    animations = Animations()
    calls = []
    animations.frame(0.0)
    handle = animations.after(0.5, lambda: calls.append('no'))
    handle.stop()
    animations.frame(1.0)
    assert calls == []


def test_a_delay_counts_the_steps_and_so_waits_out_a_long_frame():
    animations = Animations(longest=0.1)
    calls = []
    animations.frame(0.0)
    animations.after(0.25, lambda: calls.append(1))
    animations.frame(10.0)                         # one step of 0.1 s
    assert calls == []
    animations.frame(10.1)
    animations.frame(10.2)
    assert calls == [1]


def test_an_animation_added_by_a_step_starts_on_the_next_frame():
    animations = Animations(longest=1.0)
    later = Model()

    def first(dt):
        animations.animate(later)

    animations.animate(first)
    animations.frame(0.0)
    assert later.steps == []
    animations.frame(0.5)
    assert later.steps == [0.5]


def test_a_delay_of_less_than_nothing_is_refused():
    with pytest.raises(ValueError):
        Animations().after(-1.0, lambda: None)
