"""The per-vertex-colour shader shares the lit shader's lighting math
and now samples shadows.

Two guarantees:

1. Source structure -- ``vrml97_lighting.frag`` and ``vrml97_vertex_color.frag``
   both pull their attenuation / spot / per-light math from the shared
   ``_vrml97_lighting_inc.glsl`` (so the two can't silently drift), and the
   vertex-colour shader now includes the shadow machinery it previously lacked.

2. Behaviour (needs GL) -- a per-vertex-coloured wall rendered through the
   vertex_color program is *darker where a caster shadows it*. We render the wall
   with and without the caster from a pinned viewpoint and compare the mean
   brightness of the still-visible grey wall pixels; before 2a the vertex-colour
   shader had no shadow code and the two means matched.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root
SHADER_DIR = os.path.join(str(tests_root(__file__).parent),
                          'OpenGLContext', 'shaders')


def _read(name):
    with open(os.path.join(SHADER_DIR, name)) as fh:
        return fh.read()


def test_shared_lighting_include_exists():
    inc = _read('_vrml97_lighting_inc.glsl')
    # The shared math must expose calcLight taking a per-light shadow factor.
    assert 'calcLight' in inc
    assert 'shadowFactor' in inc
    assert 'calcAttenuation' in inc and 'calcSpotEffect' in inc


def test_both_lit_shaders_use_shared_include():
    for name in ('vrml97_lighting.frag', 'vrml97_vertex_color.frag'):
        src = _read(name)
        assert '#include "_vrml97_lighting_inc.glsl"' in src, name
        # Neither shader should still carry its own copy of the math.
        assert 'float calcAttenuation' not in src, name
        assert 'vec3 calcLight' not in src, name


def test_vertex_color_shader_samples_shadows():
    src = _read('vrml97_vertex_color.frag')
    # The shadow machinery (enums, samplers, resolveShadows) is now wired in.
    assert '#include "_lights_inc.glsl"' in src
    assert '#include "_shadow_inc.glsl"' in src
    assert 'resolveShadows(' in src
    # The shadow factor is threaded into every light contribution.
    assert 'lightShadow[i]' in src


DRIVER = r'''
import os, sys
os.environ.update(OPENGLCONTEXT_PROFILE='core', OPENGLCONTEXT_BACKEND='glfw',
    OPENGLCONTEXT_DISABLE_FPS_DISPLAY='1', OPENGLCONTEXT_SHADOWS='1',
    OPENGLCONTEXT_SHADOW_CASCADES='1')
WITH_CASTER = 'caster' in sys.argv
try:
    import glfw, numpy as np
    # The engine's own reader, not a bare glReadPixels: it binds the default
    # framebuffer and selects the buffer the frame is actually in first, and a
    # post-process pass leaves its own FBO bound -- reading that one back gives
    # a black frame.
    from OpenGLContext.capture import read_back_buffer
    from OpenGLContext import testingcontext
    Base = testingcontext.getInteractive()
    from OpenGLContext.scenegraph import basenodes as b

    N, S = 24, 6.0
    coords, colors, idx = [], [], []
    for j in range(N + 1):
        for i in range(N + 1):
            coords.append(((i / N - 0.5) * S, (j / N - 0.5) * S, -4.0))
            colors.append((0.8, 0.8, 0.8))
    for j in range(N):
        for i in range(N):
            a = j * (N + 1) + i
            idx += [a, a + 1, a + N + 2, a + N + 1, -1]

    class C(Base):
        def OnInit(self):
            wall = b.Shape(geometry=b.IndexedFaceSet(
                    coord=b.Coordinate(point=coords), color=b.Color(color=colors),
                    colorPerVertex=True, coordIndex=idx, solid=False),
                appearance=b.Appearance(material=b.Material(diffuseColor=(1, 1, 1))))
            kids = [b.Viewpoint(position=(0, 0, 7)),
                    b.SpotLight(location=(0, 0, 5), direction=(0, 0, -1),
                                cutOffAngle=1.5, on=True), wall]
            if WITH_CASTER:
                kids.append(b.Transform(translation=(0, 0, 0.5), children=[
                    b.Shape(geometry=b.Box(size=(1.5, 1.5, 0.3)),
                            appearance=b.Appearance(material=b.Material(diffuseColor=(1, 0, 0))))]))
            self.sg = b.sceneGraph(children=kids)

    inst = C(); inst.deferRedraw = True
    try: glfw.swap_interval(0)
    except Exception: pass
    for _ in range(9):
        glfw.poll_events(); inst.OnDraw(force=1)
    # Read between the render and the swap: after a swap the back buffer holds
    # whatever the driver last left there, which is often black.
    arr = inst.drawAndReadFrame(read_back_buffer)[0].astype(float)
    r, g, bl = arr[..., 0], arr[..., 1], arr[..., 2]
    grey = (np.abs(r - g) < 25) & (np.abs(g - bl) < 25) & (arr.sum(2) > 60)
    n = int(grey.sum())
    mean = float(arr.sum(2)[grey].mean()) if n else 0.0
    sys.stdout.write('%d %f\n' % (n, mean)); sys.stdout.flush()
except SystemExit:
    raise
except BaseException as e:
    sys.stderr.write('NOGL %r\n' % (e,)); import traceback; traceback.print_exc(); os._exit(3)
os._exit(0)
'''


def _run(*args):
    # Clean env so a leaked OPENGLCONTEXT_* setting from another test module can't
    # change how the wall renders; the DRIVER sets the variables it needs itself.
    from OpenGLContext.testing.gl_env import gl_subprocess_env
    return subprocess.run([sys.executable, '-c', DRIVER, *args],
                          capture_output=True, text=True, timeout=180,
                          env=gl_subprocess_env())


def test_vertex_color_wall_is_shadowed_by_a_caster():
    lit = _run()
    shd = _run('caster')
    for proc in (lit, shd):
        if proc.returncode == 3:
            pytest.skip('no usable GL context: %s'
                        % proc.stderr.strip().splitlines()[-1:])
        assert proc.returncode == 0, proc.stderr
    lit_n, lit_mean = lit.stdout.split()
    shd_n, shd_mean = shd.stdout.split()
    lit_n, lit_mean = int(lit_n), float(lit_mean)
    shd_n, shd_mean = int(shd_n), float(shd_mean)
    assert lit_n > 20000, 'wall not visible without caster: %s' % lit.stderr
    assert shd_n > 10000, 'wall not visible with caster: %s' % shd.stderr
    # The wall pixels the caster does NOT occlude are still visible; with shadows
    # wired in they are meaningfully darker on average than the unshadowed wall.
    assert shd_mean < lit_mean * 0.95, (
        'per-vertex-coloured wall not shadowed by the caster: '
        'lit mean=%.1f vs shadowed mean=%.1f' % (lit_mean, shd_mean))
