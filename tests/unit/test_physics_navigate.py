"""Regression test for the physics_navigate camera-driver conflict (GL, in-process).

``ViewPlatformMixin`` binds a default ``Smooth`` movement manager (arrow keys) to
``context.platform``.  ``PhysicsViewPlatform`` now owns the camera and rewrites it
every frame from the solved capsule via ``nav.apply()``.  With both bound the two
fight: while a built-in-nav key is held its interpolator glides the camera (its
timer fires from ``DoEventCascade``, after ``nav.apply``); the instant the timer
stops, ``nav.apply`` reasserts the character pose and the camera snaps back to the
last character (auto-walk) location.  The demo must unbind the default manager.

Nothing here names a windowing toolkit: the context comes from whichever backend
the run is on, keys arrive through the engine's own input records
(:mod:`OpenGLContext.events.synthetic`), and the window is let go through
``releaseWindow``, which every backend answers to.  What is under test is the
demo's camera wiring, and pinning it to one backend meant a run on another was
four failures about a GL context two window systems were fighting over.
"""
import time

import numpy as np
import pytest

from OpenGLContext.events import synthetic
from OpenGLContext.testing.glcontext import gl_available

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


@pytest.fixture
def navigator():
    """The demo, on whatever backend this run uses, let go afterwards"""
    import tests.physics_navigate as nav

    context = nav.TestContext()
    try:
        yield context
    finally:
        context.releaseWindow()


def _key(context, name, state=1):
    """One key transition, as the engine's own input record spells it"""
    synthetic.dispatch(context, {'type': 'keyboard', 'key': name,
                                 'state': state, 'modifiers': [0, 0, 0]})


@gl
def test_navigate_unbinds_default_movement_manager(navigator):
    # The built-in Smooth manager is the second writer that caused the snap.
    assert navigator.movementManager is None


@gl
def test_builtin_nav_key_does_not_move_or_snap_the_camera(navigator):
    """Holding a built-in-nav arrow key must not glide or snap the camera.

    Parks the character (auto off, no demo-key input) and drives the built-in
    ``<down>`` arrow across several rendered frames, then releases it.  The
    rendered camera must stay locked to the (stationary) character the whole time
    -- no glide while held, and therefore no snap-back on release.
    """
    character = navigator.platform_nav.character.position
    rendered = []

    def cameraDepth():
        return float(navigator.platform.position[2])

    def frame():
        # mirror the MainLoop: OnIdle (nav.apply) then OnDraw (DoEventCascade
        # runs any movement-manager interpolators, then renders).
        navigator._auto = False                 # keep the character parked
        navigator.OnIdle()
        navigator.OnDraw(force=1)

    # settle one frame so nav.apply seats the camera on the character
    frame()
    start = cameraDepth()
    assert abs(start - float(character[2])) < 1e-6

    # hold <down> (built-in Smooth 'backward') for a stretch of frames.  A held
    # key arrives as a key-down per repeat, which is what this sends.
    for _ in range(30):
        _key(navigator, '<down>', 1)
        frame()
        rendered.append(cameraDepth())
    _key(navigator, '<down>', 0)
    for _ in range(30):
        frame()
        rendered.append(cameraDepth())

    # character never moved, so the camera must never leave it
    assert float(character[2]) == pytest.approx(
        float(navigator.platform_nav.character.position[2]))
    assert max(abs(depth - start) for depth in rendered) < 1e-3, (
        'built-in nav moved/snapped the camera: %r'
        % ([round(depth, 3) for depth in rendered],))


@gl
def test_holding_a_movement_key_keeps_driving_movement(navigator):
    """A held key keeps driving movement.

    Movement must bind to 'keyboard' (key-down) events, which key-repeat
    re-emits, not 'keypress' (typed character) events, which fire once.  A
    repeat *is* another key-down, so a second one has to keep the key's
    timestamp fresh -- otherwise holding w stops after HOLD and you slide back.
    What supplies the repeats where a platform does not is
    ``eventhandlermixin.HeldKeyMixin``; see `test_backend_parity.py`.
    """
    _key(navigator, 'w', 1)
    first = navigator._keys.get('w')
    assert first is not None, "held key 'w' not registered from a keyboard event"
    assert navigator._auto is False, (
        'a movement key should take over from auto-walk')

    end = time.time() + 0.02            # advance the clock a hair
    while time.time() < end:
        pass
    _key(navigator, 'w', 1)             # the repeat
    second = navigator._keys.get('w')
    assert second is not None and second > first, (
        'a key-repeat did not sustain the held key')


@gl
def test_qe_turn_directions_match_docs(navigator):
    """q turns left (yaw decreases), e turns right (yaw increases), per the help."""
    navigator._auto = False
    nav = navigator.platform_nav
    now = time.time()

    nav.yaw = 0.0
    navigator._keys = {'q': now}
    navigator._manual(now, nav, 0.05)
    assert nav.yaw < 0.0, 'q should turn left (yaw < 0)'

    nav.yaw = 0.0
    navigator._keys = {'e': now}
    navigator._manual(now, nav, 0.05)
    assert nav.yaw > 0.0, 'e should turn right (yaw > 0)'


@gl
def test_it_runs_on_whatever_backend_the_suite_is_using(navigator):
    """Which is the point of the rest of the file being toolkit-neutral."""
    assert navigator.getViewPort()[0] > 0
    assert np.isfinite(np.asarray(navigator.platform.position, 'd')).all()
