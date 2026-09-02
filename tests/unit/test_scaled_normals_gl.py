"""How brightly a scaled shape is lit, in the compatibility profile (needs GL).

The fixed-function pipeline transforms a normal by the inverse transpose of
the modelview, which for a uniform scale ``s`` divides its length by ``s``.
Unless the GL is told to renormalize, a shape under a ``Transform`` with
``scale`` is lit as though ``N.L`` were ``1/s`` times what it is: half size
means twice the diffuse light, and a scaled-up shape goes dark.

The core-profile shaders never had this -- they ``normalize()`` the transformed
normal in the vertex shader -- so the two profiles disagreed about a scaled
scene, which is what these pin.

Each scenario renders a sphere facing a head-on directional light and reports
the centre pixel's luminance. The pixel at the centre is the point whose normal
faces the camera, so the shading there does not depend on how large the sphere
is drawn -- only on whether the normal is unit length. Skips (not fails) when
GL is unavailable.
"""
import subprocess
import sys

import pytest

from OpenGLContext import renderoptions

DRIVER = r'''
import os, sys
SCALE = float(sys.argv[1])
PROFILE = sys.argv[2]
os.environ['OPENGLCONTEXT_PROFILE'] = PROFILE
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
STATE = {'gl_ok': False, 'lum': -1.0}
try:
    import glfw
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes

    class C(Base):
        def OnInit(self):
            shape = basenodes.Shape(
                geometry=basenodes.Sphere(radius=1.0),
                appearance=basenodes.Appearance(
                    material=basenodes.Material(
                        diffuseColor=(0.4, 0.4, 0.4), ambientIntensity=0.0)),
            )
            self.sg = basenodes.sceneGraph(children=[
                basenodes.DirectionalLight(direction=(0, 0, -1), intensity=1.0),
                basenodes.Transform(scale=(SCALE, SCALE, SCALE),
                                    children=[shape]),
            ])

    inst = C()
    inst.deferRedraw = True
    try:
        glfw.swap_interval(0)
    except Exception:
        pass
    w, h = inst.getViewPort()
    for _ in range(6):
        glfw.poll_events()
        inst.OnDraw(force=1)
    STATE['gl_ok'] = True
    import numpy as np
    px = glReadPixels(w // 2, h // 2, 1, 1, GL_RGB, GL_UNSIGNED_BYTE)
    flat = np.frombuffer(bytes(px), dtype=np.uint8).reshape(-1)
    STATE['lum'] = sum(int(v) for v in flat[:3]) / 3.0
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,))
    import traceback; traceback.print_exc()
    os._exit(3)

# stderr, and flushed: os._exit discards whatever is still buffered.
sys.stderr.write('LUM=%.3f\n' % STATE['lum'])
sys.stderr.flush()
os._exit(0 if STATE['gl_ok'] else 3)
'''


def luminance(scale, profile):
    # What this measures is a pixel, so the render has to be decided by the
    # call rather than by whatever the session is carrying: importing
    # OpenGLContext.bin.view puts the viewer's PBR renderer and its IBL
    # intensity into os.environ for the rest of the run, and a sphere lit
    # through the uber-shader with a light probe is not the sphere this reasons
    # about. The driver pins the rest for itself.
    proc = subprocess.run([sys.executable, '-c', DRIVER, str(scale), profile],
                          capture_output=True, text=True, timeout=120,
                          env=renderoptions.clean_environment())
    if proc.returncode == 3:
        pytest.skip('no usable GL context: %s'
                    % proc.stderr.strip().splitlines()[-1:])
    assert proc.returncode == 0, (
        'render failed at scale %r in %s\nstdout:\n%s\nstderr:\n%s'
        % (scale, profile, proc.stdout, proc.stderr))
    for line in proc.stderr.splitlines():
        if line.startswith('LUM='):
            return float(line[4:])
    raise AssertionError('driver reported no luminance:\n%s' % proc.stderr)


@pytest.mark.parametrize('profile', ['compatibility', 'core'])
@pytest.mark.parametrize('scale', [0.5, 2.0])
def test_scale_does_not_change_how_brightly_a_surface_is_lit(profile, scale):
    """The point facing the light is as bright whatever size it is drawn."""
    plain = luminance(1.0, profile)
    assert plain > 20.0, 'the unscaled sphere has to be lit for this to mean anything'

    scaled = luminance(scale, profile)

    assert scaled == pytest.approx(plain, abs=4.0), (
        'scale %s changed the lit value from %.1f to %.1f in the %s profile'
        % (scale, plain, scaled, profile))


def test_the_two_profiles_agree_about_a_scaled_scene():
    """Whatever the profile, a half-size sphere is lit the same."""
    assert luminance(0.5, 'compatibility') == pytest.approx(
        luminance(0.5, 'core'), abs=6.0)
