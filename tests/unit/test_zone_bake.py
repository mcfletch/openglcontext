"""Baking zones' image-based lights: the plan, the pass's choice, and a real bake.

:class:`~OpenGLContext.passes.zonebake.ZoneBakePlan` decides where the camera
stands and when a zone is finished, with no GL, so it is tested directly. The
bake itself runs offscreen in a subprocess (``tests/helpers/_zone_bake.py``),
from a context that asks for the PBR pass and the full probe on itself rather
than through the process environment.
"""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from OpenGLContext.passes import renderpass
from OpenGLContext.passes.zonebake import ZoneBakePlan
from OpenGLContext.testing.paths import tests_root

BAKE = os.path.join(str(tests_root(__file__)), 'helpers', '_zone_bake.py')


class TestThePlan:
    def test_it_stands_in_each_zone_in_turn(self):
        plan = ZoneBakePlan([('a', (0, 0, 0)), ('b', (5, 0, 0))], frames_per_zone=3)
        assert plan.current == ('a', (0, 0, 0))
        assert plan.step(settled=True) is True
        assert plan.current == ('b', (5, 0, 0))
        assert plan.step(settled=True) is True
        assert plan.current is None and plan.finished

    def test_a_zone_stays_current_until_its_captures_settle(self):
        plan = ZoneBakePlan([('a', (0, 0, 0))], frames_per_zone=5)
        assert plan.step(settled=False) is None
        assert plan.step(settled=False) is None
        assert plan.current == ('a', (0, 0, 0))
        assert plan.step(settled=True) is True

    def test_a_zone_that_never_settles_is_given_up_on(self):
        plan = ZoneBakePlan([('a', (0, 0, 0)), ('b', (1, 0, 0))], frames_per_zone=2)
        assert plan.step(settled=False) is None
        assert plan.step(settled=False) is False
        assert plan.current == ('b', (1, 0, 0))
        assert plan.missed == ['a']

    def test_how_far_it_has_got(self):
        plan = ZoneBakePlan([('a', (0, 0, 0)), ('b', (1, 0, 0))])
        assert plan.progress == (0, 2)
        plan.step(settled=True)
        assert plan.progress == (1, 2)

    def test_no_zones_is_finished_at_once(self):
        assert ZoneBakePlan([]).finished

    def test_a_zone_is_given_a_frame_at_least(self):
        with pytest.raises(ValueError):
            ZoneBakePlan([('a', (0, 0, 0))], frames_per_zone=0)


class TestAContextNamesItsRenderer:
    """A bake, a tool or a test asks for the PBR pass for its own context;
    the process environment is left as it was."""

    def test_the_context_asking_for_pbr_gets_it(self, monkeypatch):
        from OpenGLContext.passes import pbrpass
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)
        pbrpass.reset_renderer_cache()
        try:
            chosen = renderpass._core_flatpass_class(SimpleNamespace(renderer='pbr'))
            plain = renderpass._core_flatpass_class(SimpleNamespace(renderer=None))
        finally:
            pbrpass.reset_renderer_cache()
        assert chosen is pbrpass.PBRPass
        assert plain is not pbrpass.PBRPass


def test_a_zone_is_baked_offscreen_without_touching_the_environment():
    pytest.importorskip('OpenGL.EGL', exc_type=ImportError)
    done = subprocess.run([sys.executable, BAKE], capture_output=True, text=True,
                          timeout=240)
    lines = [line for line in done.stdout.splitlines() if line.startswith('BAKED ')]
    if not lines and 'EGL' in done.stderr:
        pytest.skip('no offscreen EGL context here: %s' % (done.stderr[-300:],))
    assert done.returncode == 0, done.stderr[-2000:]
    report = json.loads(lines[-1][len('BAKED '):])
    assert report['baked'] == 1
    assert report['is_zone'] == [True]
    assert report['irradiance_faces'] == [6]
    assert report['mip_levels'][0] >= 1
    assert report['finite'] == [True]
    assert report['progress'] == [[1, 1]]
    assert report['environment'] == []
