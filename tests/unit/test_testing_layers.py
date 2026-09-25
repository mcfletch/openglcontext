"""``check_failing_layer`` passes a guarded layer and fails one retried every frame."""
import logging

import pytest

from OpenGLContext.passes.layerguard import LayerGuard
from OpenGLContext.testing.layers import (
    LayerNotIsolated,
    check_failing_layer,
    drive_failing_layer,
)

log = logging.getLogger(__name__)


class _Context:
    def __init__(self):
        self.redraws = 0

    def triggerRedraw(self, force=0):  # noqa: ARG002 the signature of the triggerRedraw it stands in for
        self.redraws += 1


class _Pass:
    """A frame with one optional layer, guarded or not."""

    def __init__(self, guarded=True, asks=False, context=None):
        self.guard = LayerGuard('glow', logger=log) if guarded else None
        self.asks, self.context = asks, context
        self.frames = 0

    def glow(self):
        return 'glow'

    def frame(self):
        self.frames += 1
        if self.guard is not None:
            self.guard.run(self.glow)
        else:
            try:
                self.glow()
            except Exception:
                log.exception('the glow failed')
        if self.asks:
            self.context.triggerRedraw(0)


def test_a_guarded_layer_is_tried_once_and_reported_once():
    passing = _Pass()
    run = check_failing_layer(passing.frame, passing, 'glow', frames=6)
    assert (run.attempts, run.reports, run.asked, run.drawn) == (1, 1, 0, 6)
    assert passing.glow() == 'glow'           # put back afterwards


def test_a_layer_retried_every_frame_fails():
    passing = _Pass(guarded=False)
    with pytest.raises(LayerNotIsolated, match='entered 5 times in 5 frames.*reported 5 times'):
        check_failing_layer(passing.frame, passing, 'glow', frames=5)


def test_a_layer_asking_for_frames_after_it_failed_fails():
    context = _Context()
    passing = _Pass(asks=True, context=context)
    with pytest.raises(LayerNotIsolated, match='asked for 4 frames'):
        check_failing_layer(passing.frame, passing, 'glow', frames=4, context=context)
    assert context.triggerRedraw.__func__ is _Context.triggerRedraw


def test_a_layer_on_the_class_is_put_back_on_the_class():
    passing = _Pass()
    run = drive_failing_layer(passing.frame, _Pass, 'glow', frames=3)
    assert run.attempts == 1
    assert 'glow' in vars(_Pass) and 'glow' not in vars(passing)


def test_a_frame_the_failure_stops_fails_the_test():
    def frame():
        passing.glow()
    passing = _Pass()
    with pytest.raises(Exception, match='fails, as check_failing_layer makes it'):
        drive_failing_layer(frame, passing, 'glow')
    assert passing.glow() == 'glow'


def test_the_plugin_offers_it_as_a_fixture(check_failing_layer):
    passing = _Pass()
    assert check_failing_layer(passing.frame, passing, 'glow', frames=3).attempts == 1
