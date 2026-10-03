"""The built-in studio environment fills non-metals gently.

With no environment authored, the pass lights the scene from a procedural
studio: bright reflections for metal, and diffuse light and reflection for
everything else.  Left at the studio's own brightness that lifts a floor to
near white and the shadow of a spotlight on it is a few percent darker, so the
scene reads as unshadowed.  What the built-in environment gives a non-metal is
scaled down (:data:`OpenGLContext.passes.ibl.STUDIO_FILL`); a metal's reflection
and an environment the scene supplies are used at their own strength.
"""
import os
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.passes import ibl
from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root

ROOT = os.path.dirname(str(tests_root(__file__)))


class TestDiffuseScale:
    def test_analytic_is_always_the_studio(self):
        assert ibl.fill_scale('analytic', None) == ibl.STUDIO_FILL

    def test_full_with_the_procedural_probe_is_the_studio(self):
        probe = SimpleNamespace(studio=True)
        assert ibl.fill_scale('full', probe) == ibl.STUDIO_FILL

    def test_full_with_an_authored_environment_is_unscaled(self):
        probe = SimpleNamespace(studio=False)
        assert ibl.fill_scale('full', probe) == 1.0

    @pytest.mark.parametrize('mode,probe', [
        ('analytic', None), ('full', SimpleNamespace(studio=True))])
    def test_a_scene_with_no_lights_keeps_the_studio_at_full_strength(self, mode, probe):
        """The studio and the default headlight are all the light there is."""
        assert ibl.fill_scale(mode, probe, scene_lit=False) == 1.0

    def test_off_is_unscaled(self):
        assert ibl.fill_scale('off', None) == 1.0

    def test_the_studio_is_dimmer_than_the_environment_it_stands_in_for(self):
        assert 0.0 < ibl.STUDIO_FILL < 1.0

    def test_a_probe_is_the_studio_until_an_environment_is_built_from_a_source(self):
        assert ibl.IBLProbe().studio is True


@pytest.mark.skipif(not gl_available(), reason='no GL target available')
def test_the_probe_irradiance_of_a_uniform_sky_is_its_radiance():
    """The irradiance map holds E/PI, so the analytic path uses the radiance
    where it stands in for it."""
    from OpenGLContext.testing.glcontext import hidden_window
    ibl.set_equirect_env(np.ones((32, 64, 3), 'f'))
    try:
        with hidden_window():
            probe = ibl.IBLProbe()
            assert probe.ensure_built()
            irradiance, _ = probe.read_layer(0)
            assert float(np.mean(irradiance[2])) == pytest.approx(1.0, abs=0.02)
            assert probe.studio is False
    finally:
        ibl.set_equirect_env(None)


#: A matte floor with a cube standing on it, under a shadow-casting spotlight.
#: Prints nothing; the frame is captured and the test reads it.
SCRIPT = textwrap.dedent('''
    import os, sys
    os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
    os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
    os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
    os.environ['OPENGLCONTEXT_HIDDEN'] = '1'
    os.environ['OPENGLCONTEXT_NO_VSYNC'] = '1'
    os.environ['OPENGLCONTEXT_SHADOWS'] = sys.argv[3]
    os.environ['OPENGLCONTEXT_SHADOW_CASCADES'] = '1'
    os.environ['OPENGLCONTEXT_IBL'] = sys.argv[1]
    os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] = '12'
    os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR'] = sys.argv[2]
    os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME'] = 'floor'

    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph.basenodes import (
        Appearance, Box, Material, Shape, SpotLight, Transform, sceneGraph)

    from OpenGLContext.passes.pbrpass import PBRShaderProgram
    _set_ibl_mode = PBRShaderProgram.set_ibl_mode
    def _report(self, mode_code, intensity=1.0, fill=1.0):
        print('FILL', fill)
        return _set_ibl_mode(self, mode_code, intensity, fill)
    PBRShaderProgram.set_ibl_mode = _report

    Base = testingcontext.getInteractive('glfw')
    LAMPS = [] if sys.argv[4] == 'none' else [SpotLight(
        location=(3, 5, 3), direction=(-3, -5, -3), color=(1, 1, 1),
        intensity=1 if sys.argv[4] == 'lamp' else 0, castShadows=True)]

    def block(size, at, colour):
        return Transform(translation=at, children=[Shape(
            geometry=Box(size=size),
            appearance=Appearance(material=Material(diffuseColor=colour)))])

    class TestContext(Base):
        initialPosition = (0, 2, 6)
        def OnInit(self):
            Base.OnInit(self)
            self.sg = sceneGraph(children=[
                *LAMPS,
                block((8, .05, 8), (0, 0, 0), (.7, .7, .7)),
                block((1, 1, 1), (0, .525, 0), (.7, .7, .7)),
            ])

    TestContext.ContextMainLoop(size=(160, 160))
''')


def _frame(mode, shadows, tmp_path):
    """The captured frame, as luminance."""
    shot = tmp_path / 'floor.png'
    shot.unlink(missing_ok=True)
    proc = subprocess.run(
        [sys.executable, '-c', SCRIPT, mode, str(tmp_path), shadows, 'lamp'],
        cwd=ROOT, timeout=180,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not shot.exists():
        raise AssertionError(proc.stdout.decode('utf-8', 'replace')[-2000:])
    return np.asarray(Image.open(shot).convert('L'), dtype=float)


def _shadow_depth(mode, tmp_path):
    """How many levels of 255 the shadow takes off the brightest-hit pixel."""
    lit = _frame(mode, '0', tmp_path)
    shadowed = _frame(mode, '1', tmp_path)
    return float((lit - shadowed).max())


#: Levels of 255.
DEPTH = 40

gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


@gl
@pytest.mark.slow
class TestAShadowOnTheFloorShowsUnderTheStudio:
    @pytest.mark.parametrize('mode', ['full', 'analytic'])
    def test_the_shadow_is_clearly_darker_than_the_lit_floor(self, mode, tmp_path):
        depth = _shadow_depth(mode, tmp_path)
        assert depth >= DEPTH, (
            '%s: the shadow darkens the floor by %.0f of 255 levels, so it is '
            'lost under the environment light' % (mode, depth))


@gl
@pytest.mark.slow
@pytest.mark.parametrize('lamp,expected', [
    ('none', {1.0}), ('dark', {ibl.STUDIO_FILL}), ('lamp', {ibl.STUDIO_FILL})])
def test_the_pass_scales_the_studio_only_for_a_scene_with_lights(lamp, expected, tmp_path):
    """A lamp of no intensity is still the scene's own light; no lamp leaves the
    studio and the default headlight as the only light."""
    proc = subprocess.run(
        [sys.executable, '-c', SCRIPT, 'full', str(tmp_path), '0', lamp],
        cwd=ROOT, timeout=180, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        check=False)
    seen = {float(line.split()[1])
            for line in proc.stdout.decode('utf-8', 'replace').splitlines()
            if line.startswith('FILL ')}
    assert seen == expected
