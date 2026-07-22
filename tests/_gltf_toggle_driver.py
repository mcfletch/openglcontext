"""Subprocess driver for test_gltf_view_physics_toggle (not a test itself).

Runs one walk/free-fly toggle scenario against the oglc-gltf viewer in an isolated
process (multiple GL contexts can't coexist in one process), asserts the invariants,
and prints ``TOGGLE_OK`` on success.  Usage: ``_gltf_toggle_driver.py MODEL MODE``
where MODE is ``physics`` (start walking, via ``--physics``) or ``nophysics``.

The viewer defaults to free-fly (an isolated/floorless model would otherwise drop
the avatar past the geometry), so the walk scenario opts in with ``--physics``.
"""
import os
import sys

os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')

import numpy as np

from OpenGLContext.bin import gltf_view


def _cam(ctx):
    return np.asarray(ctx.platform.position[:3], dtype='d').copy()


def main():
    model = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'physics'
    argv = [model] + (['--no-physics'] if mode == 'nophysics' else ['--physics'])
    gltf_view.TestContext.config = gltf_view.parse_args(argv)
    ctx = gltf_view.TestContext()

    # The interactive path loads the model on a background thread and applies it
    # (and, in walk mode, enables physics) from OnIdle. Pump the idle handler until
    # the real scene has replaced the empty "Loading..." placeholder, so the
    # assertions below see the finished state rather than a load-in-progress.
    import time
    deadline = time.time() + 30.0
    while not ctx._scene_loaded and time.time() < deadline:
        ctx.OnIdle()
        time.sleep(0.02)
    assert ctx._scene_loaded, 'model did not finish loading within 30s'

    if mode == 'physics':
        # starts walking: physics owns the camera, the Smooth navigator is unbound
        assert ctx._physics_on, 'expected to start in walk mode'
        assert ctx._physics is not None
        assert ctx.movementManager is None, 'Smooth manager should be unbound'
        assert ctx._free_manager is not None

        before = _cam(ctx)
        ctx._toggle_physics()                       # -> free-fly
        assert not ctx._physics_on
        assert ctx.movementManager is ctx._free_manager, 'Smooth should be rebound'
        assert np.allclose(before, _cam(ctx), atol=1e-6), \
            ('camera jumped on toggle-off', before, _cam(ctx))

        ctx.OnIdle()                                # free-fly: no physics step
        assert not ctx._physics_on

        # fly away, then toggle walk on: avatar reseats at the flown-to camera
        target = _cam(ctx) + np.array([2.0, 2.0, 2.0])
        ctx.platform.setPosition(tuple(target))
        ctx._toggle_physics()                       # -> walk (safe-bind)
        assert ctx._physics_on
        assert ctx.movementManager is None
        eye = np.asarray(ctx._physics.character.eye(), dtype='d')
        assert np.linalg.norm((eye - target)[[0, 2]]) < 1.0, \
            ('avatar did not reseat at camera', eye, target)
    else:
        # --no-physics: starts free-fly, physics not built; 'g' builds it lazily
        assert not ctx._physics_on
        assert ctx._physics is None
        assert ctx.movementManager is ctx._free_manager

        ctx._toggle_physics()                       # lazily builds + enables walk
        assert ctx._physics_on
        assert ctx._physics is not None
        assert ctx.movementManager is None

        ctx._toggle_physics()                       # back to free-fly
        assert not ctx._physics_on
        assert ctx.movementManager is ctx._free_manager

    import glfw
    if getattr(ctx, 'window', None):
        glfw.destroy_window(ctx.window)
    sys.stdout.write('TOGGLE_OK\n')
    sys.stdout.flush()


if __name__ == '__main__':
    main()
