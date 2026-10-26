"""The first-person navigation tutorial: the keys walk the character and the camera stays at its eyes.

The context comes from whichever backend the run is on, keys arrive through the
engine's own input records (:mod:`OpenGLContext.events.synthetic`), and frames
are drawn on a fixed clock, so the walker covers the same ground on every machine.
"""
import numpy as np
import pytest
import tests.tutorials.physics.physics_navigate as nav

from OpenGLContext.events import synthetic
from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.video.clock import FixedStepClock

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


@pytest.fixture
def navigator(monkeypatch):
    """The tutorial on a fixed clock, its world stepped in the frame, let go afterwards."""
    monkeypatch.setenv('OPENGLCONTEXT_PHYSICS_MODE', 'inline')
    with FixedStepClock(60, start=0.0) as clock:
        context = nav.TestContext()
        context.deferRedraw = True
        context.clock = clock
        try:
            yield context
        finally:
            context.releaseWindow()


def _key(context, name, state=1):
    """One key transition, as the engine's own input record spells it."""
    synthetic.dispatch(context, {'type': 'keyboard', 'key': name,
                                 'state': state, 'modifiers': [0, 0, 0]})


def _frames(context, count):
    for _ in range(count):
        context.clock.advance()
        context.runRenderQueue()
        context.OnDraw(force=1)


@gl
def test_the_free_navigator_gives_up_the_camera(navigator):
    assert navigator.movementManager is None


@gl
def test_the_camera_is_at_the_walkers_eyes(navigator):
    _frames(navigator, 30)
    assert np.allclose(navigator.platform.position[:3], navigator.hero.eye, atol=1e-3)


@gl
def test_holding_w_walks_the_character_forward_and_the_camera_goes_with_it(navigator):
    _frames(navigator, 10)
    start = np.array(navigator.hero.position)
    _key(navigator, 'w', 1)
    _frames(navigator, 60)
    _key(navigator, 'w', 0)
    moved = np.array(navigator.hero.position) - start
    assert moved[2] < -2.0                                    # yaw 0 walks along -Z
    assert abs(moved[0]) < 0.3
    assert np.allclose(navigator.platform.position[:3], navigator.hero.eye, atol=1e-3)


@gl
def test_q_turns_left_and_e_turns_right(navigator):
    platform = navigator.walker.platform
    _key(navigator, 'q', 1)
    _frames(navigator, 20)
    _key(navigator, 'q', 0)
    assert platform.yaw < 0.0
    platform.yaw = 0.0
    _key(navigator, 'e', 1)
    _frames(navigator, 20)
    _key(navigator, 'e', 0)
    assert platform.yaw > 0.0


@gl
def test_f_flies_and_walks_again(navigator):
    navigator.on_fly(None)
    assert navigator.hero.controller.flying
    navigator.on_fly(None)
    assert not navigator.hero.controller.flying
