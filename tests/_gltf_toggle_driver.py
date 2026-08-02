"""Subprocess driver for test_gltf_view_physics_toggle (not a test itself).

Runs one walk/free-fly toggle scenario against the oglc-gltf viewer in an isolated
process (multiple GL contexts can't coexist in one process), asserts the invariants,
and prints ``TOGGLE_OK`` on success.  Usage: ``_gltf_toggle_driver.py MODEL MODE``
where MODE is ``physics`` (start walking, via ``--physics``), ``nophysics``, or
``walk`` (drive the declared movement modes with real key events and check the
avatar actually moves).

The viewer defaults to free-fly (an isolated/floorless model would otherwise drop
the avatar past the geometry), so the walk scenario opts in with ``--physics``.
"""
import os
import sys

os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')

import numpy as np

from OpenGLContext.bin import view


def _cam(ctx):
    return np.asarray(ctx.platform.position[:3], dtype='d').copy()


def main():
    model = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'physics'
    argv = [model] + (['--no-physics'] if mode == 'nophysics' else ['--physics'])
    view.TestContext.options = view.parse_args(argv)
    ctx = view.TestContext()

    # The interactive path loads the model on a background thread and applies it
    # (and, in walk mode, enables physics) from OnIdle. Pump the idle handler until
    # the real scene has replaced the empty "Loading..." placeholder, so the
    # assertions below see the finished state rather than a load-in-progress.
    import time
    deadline = time.time() + 30.0
    while not ctx.sceneLoaded and time.time() < deadline:
        ctx.OnIdle()
        time.sleep(0.02)
    assert ctx.sceneLoaded, 'model did not finish loading within 30s'

    if mode == 'physics':
        # starts walking: physics owns the camera, the Smooth navigator is unbound
        assert ctx.physicsWalking, 'expected to start in walk mode'
        assert ctx.physicsPlatform is not None
        assert ctx.movementManager is None, 'Smooth manager should be unbound'
        assert ctx._freeManager is not None

        before = _cam(ctx)
        ctx.togglePhysics()                       # -> free-fly
        assert not ctx.physicsWalking
        assert ctx.movementManager is ctx._freeManager, 'Smooth should be rebound'
        assert np.allclose(before, _cam(ctx), atol=1e-6), \
            ('camera jumped on toggle-off', before, _cam(ctx))

        ctx.OnIdle()                                # free-fly: no physics step
        assert not ctx.physicsWalking

        # fly away, then toggle walk on: avatar reseats at the flown-to camera
        target = _cam(ctx) + np.array([2.0, 2.0, 2.0])
        ctx.platform.setPosition(tuple(target))
        ctx.togglePhysics()                       # -> walk (safe-bind)
        assert ctx.physicsWalking
        assert ctx.movementManager is None
        eye = np.asarray(ctx.physicsPlatform.character.eye(), dtype='d')
        assert np.linalg.norm((eye - target)[[0, 2]]) < 1.0, \
            ('avatar did not reseat at camera', eye, target)
    elif mode == 'walk':
        # The declared movement modes, driven by real key events: the sampler is
        # fed from event dispatch, a mode reads it once per frame, and the
        # character controller is what moves.
        assert ctx.physicsWalking, 'expected to start in walk mode'
        assert ctx.getNavigation() is not None, 'no navigation manager'
        assert ctx.getNavigationPlatform() is ctx.physicsPlatform

        from OpenGLContext.events.keyboardevents import KeyboardEvent

        def key(name, state):
            event = KeyboardEvent()
            event.name = name
            event.state = state
            return event

        start = np.asarray(ctx.physicsPlatform.character.position, dtype='d').copy()
        ctx.ProcessEvent(key('w', 1))
        for _ in range(40):
            ctx.OnIdle()
            time.sleep(0.005)
        moved = np.asarray(ctx.physicsPlatform.character.position, dtype='d') - start
        assert np.linalg.norm(moved[[0, 2]]) > 1e-3, ('holding w moved nothing',
                                                      moved)

        ctx.ProcessEvent(key('w', 0))
        for _ in range(5):
            ctx.OnIdle()
        here = np.asarray(ctx.physicsPlatform.character.position, dtype='d').copy()
        for _ in range(20):
            ctx.OnIdle()
            time.sleep(0.005)
        after = np.asarray(ctx.physicsPlatform.character.position, dtype='d')
        assert np.linalg.norm((after - here)[[0, 2]]) < 1e-3, \
            ('released w kept moving', here, after)

        # The mode in force is published for anything watching it.
        assert ctx.contextDefinition.movementMode is not None
        assert ctx.contextDefinition.movementMode.name == 'walk'
        ctx.togglePhysicsFly(None)
        assert ctx.contextDefinition.movementMode.name == 'fly'
        assert ctx.physicsPlatform.character.flying
    else:
        # --no-physics: starts free-fly, physics not built; 'g' builds it lazily
        assert not ctx.physicsWalking
        assert ctx.physicsPlatform is None
        assert ctx.movementManager is ctx._freeManager

        ctx.togglePhysics()                       # lazily builds + enables walk
        assert ctx.physicsWalking
        assert ctx.physicsPlatform is not None
        assert ctx.movementManager is None

        ctx.togglePhysics()                       # back to free-fly
        assert not ctx.physicsWalking
        assert ctx.movementManager is ctx._freeManager

    import glfw
    if getattr(ctx, 'window', None):
        glfw.destroy_window(ctx.window)
    sys.stdout.write('TOGGLE_OK\n')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
