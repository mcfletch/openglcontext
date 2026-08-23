"""Regression test for the physics_navigate camera-driver conflict (GL, in-process).

``ViewPlatformMixin`` binds a default ``Smooth`` movement manager (arrow keys) to
``context.platform``.  ``PhysicsViewPlatform`` now owns the camera and rewrites it
every frame from the solved capsule via ``nav.apply()``.  With both bound the two
fight: while a built-in-nav key is held its interpolator glides the camera (its
timer fires from ``DoEventCascade``, after ``nav.apply``); the instant the timer
stops, ``nav.apply`` reasserts the character pose and the camera snaps back to the
last character (auto-walk) location.  The demo must unbind the default manager.
"""
import os
import numpy as np
import pytest

from OpenGLContext.testing.glcontext import gl_available


gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


def _make_context():
    os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
    from OpenGLContext import testingcontext        # noqa: F401  (sets base class)
    import tests.physics_navigate as nav
    return nav.TestContext()


@gl
def test_navigate_unbinds_default_movement_manager():
    ctx = _make_context()
    try:
        # The built-in Smooth manager is the second writer that caused the snap.
        assert ctx.movementManager is None
    finally:
        import glfw
        if getattr(ctx, 'window', None):
            glfw.destroy_window(ctx.window)


@gl
def test_builtin_nav_key_does_not_move_or_snap_the_camera():
    """Holding a built-in-nav arrow key must not glide or snap the camera.

    Parks the character (auto off, no demo-key input) and drives the built-in
    ``<down>`` arrow across several rendered frames, then releases it.  The
    rendered camera must stay locked to the (stationary) character the whole time
    -- no glide while held, and therefore no snap-back on release.
    """
    import glfw
    ctx = _make_context()
    try:
        char = ctx.platform_nav.character.position
        rendered = []

        def cam_z():
            return float(ctx.platform.position[2])

        def frame():
            # mirror the MainLoop: OnIdle (nav.apply) then OnDraw (DoEventCascade
            # runs any movement-manager interpolators, then renders).
            ctx._auto = False                       # keep the character parked
            ctx.OnIdle()
            ctx.OnDraw(force=1)

        # settle one frame so nav.apply seats the camera on the character
        frame()
        start = cam_z()
        assert abs(start - float(char[2])) < 1e-6

        # hold <down> (built-in Smooth 'backward') for a stretch of frames
        for i in range(30):
            ctx.glfwOnKey(ctx.window, glfw.KEY_DOWN, 0, glfw.PRESS, 0)
            frame()
            rendered.append(cam_z())
        # release and let any interpolator run out
        ctx.glfwOnKey(ctx.window, glfw.KEY_DOWN, 0, glfw.RELEASE, 0)
        for i in range(30):
            frame()
            rendered.append(cam_z())

        # character never moved, so the camera must never leave it
        assert float(char[2]) == pytest.approx(float(ctx.platform_nav.character.position[2]))
        assert max(abs(z - start) for z in rendered) < 1e-3, (
            'built-in nav moved/snapped the camera: %r' % (
                [round(z, 3) for z in rendered],))
    finally:
        if getattr(ctx, 'window', None):
            glfw.destroy_window(ctx.window)


@gl
def test_holding_a_movement_key_repeats():
    """A held key keeps driving movement via key-repeat.

    Movement must bind to 'keyboard' (key-down) events, which key-repeat re-emits,
    not 'keypress' (typed character) events, which fire once. A single press plus a
    ``pumpKeyRepeats`` tick (as the main loop runs each frame) must keep the key's
    timestamp fresh -- otherwise holding w stops after HOLD and you slide back."""
    import glfw
    import time
    ctx = _make_context()
    try:
        ctx.keyRepeatDelay = 0.0
        ctx.keyRepeatInterval = 0.0
        # one physical key-down for 'w'; the handler must fire from the keyboard
        # event (proving movement is not on the character/'keypress' channel)
        ctx.glfwOnKey(ctx.window, glfw.KEY_W, 0, glfw.PRESS, 0)
        t1 = ctx._keys.get('w')
        assert t1 is not None, "held key 'w' not registered from a keyboard event"
        assert ctx._auto is False, "a movement key should take over from auto-walk"
        # advance the clock a hair, then let key-repeat run with no new press
        end = time.time() + 0.02
        while time.time() < end:
            pass
        ctx.pumpKeyRepeats()
        t2 = ctx._keys.get('w')
        assert t2 is not None and t2 > t1, "key-repeat did not sustain the held key"
    finally:
        if getattr(ctx, 'window', None):
            glfw.destroy_window(ctx.window)


@gl
def test_qe_turn_directions_match_docs():
    """q turns left (yaw decreases), e turns right (yaw increases), per the help."""
    import glfw
    import time
    ctx = _make_context()
    try:
        ctx._auto = False
        nav = ctx.platform_nav
        now = time.time()

        nav.yaw = 0.0
        ctx._keys = {'q': now}
        ctx._manual(now, nav, 0.05)
        assert nav.yaw < 0.0, "q should turn left (yaw < 0)"

        nav.yaw = 0.0
        ctx._keys = {'e': now}
        ctx._manual(now, nav, 0.05)
        assert nav.yaw > 0.0, "e should turn right (yaw > 0)"
    finally:
        if getattr(ctx, 'window', None):
            glfw.destroy_window(ctx.window)
