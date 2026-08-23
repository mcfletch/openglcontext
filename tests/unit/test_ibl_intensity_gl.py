"""The environment-intensity control reaches both environment paths
(``OPENGLCONTEXT_IBL_INTENSITY`` / ``ContextDefinition.iblIntensity``).

The setting scales the ambient/environment term so a shadow-casting key light
reads against it instead of being lifted by full-strength ambient.  There are
two paths that term can come from -- the prefiltered probe (``full``) and the
procedural approximation (``analytic``) -- and ``auto`` picks between them from
what the machine can do, degrading from one to the other while the program is
running.

So a control that works in only one of them is a control that stops working
part-way through a session, on some machines and not others.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

ROOT = os.path.dirname(str(tests_root(__file__)))

#: Render a smooth dielectric lit only by the environment, and report the mean
#: of the frame.  A dielectric's ambient is nearly all the specular lobe, which
#: is the term the analytic path was leaving unscaled.
SCRIPT = textwrap.dedent('''
    import os, sys
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
    os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
    os.environ['OPENGLCONTEXT_IBL'] = sys.argv[1]
    os.environ['OPENGLCONTEXT_IBL_INTENSITY'] = sys.argv[2]
    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '12'
    os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR'] = sys.argv[3]
    os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME'] = 'probe'

    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import Shape, Transform, sceneGraph
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    from OpenGLContext.scenegraph.quadrics import Sphere
    from OpenGLContext.scenegraph.appearance import Appearance

    Base = testingcontext.getInteractive('glfw')

    class TestContext(Base):
        initialPosition = (0, 0, 4)
        def OnInit(self):
            Base.OnInit(self)
            ball = Shape(
                geometry=Sphere(radius=1.4),
                appearance=Appearance(material=PBRMaterial(
                    baseColor=(0.02, 0.05, 0.07), metallic=0.0, roughness=0.06)))
            self.sg = sceneGraph(children=[Transform(children=[ball])])

    TestContext.ContextMainLoop(size=(120, 120))
''')


gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


def _brightness(mode, intensity, tmp_path):
    """Mean of the rendered frame, or None where nothing was captured."""
    proc = subprocess.run(
        [sys.executable, '-c', SCRIPT, mode, intensity, str(tmp_path)],
        cwd=ROOT, timeout=180,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    shot = tmp_path / 'probe.png'
    if not shot.exists():
        raise AssertionError(proc.stdout.decode('utf-8', 'replace')[-2000:])
    from PIL import Image
    import numpy as np
    return float(np.asarray(Image.open(shot).convert('RGB')).mean())


@gl
@pytest.mark.slow
class TestTurningItDownDarkensTheAmbient:
    @pytest.mark.parametrize('mode', ['full', 'analytic'])
    def test_a_quarter_is_darker_than_full_strength(self, mode, tmp_path):
        bright = _brightness(mode, '1.0', tmp_path)
        dim = _brightness(mode, '0.25', tmp_path)
        assert dim < bright - 1.0, (
            '%s: iblIntensity 0.25 rendered %.1f against %.1f at 1.0, so the '
            'control does not reach this path' % (mode, dim, bright))
