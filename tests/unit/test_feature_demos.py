"""Every documented feature has a demo, and every demo renders.

A feature with a documentation page and nothing to run is a feature the
reader has to take on trust.  Each demo below is the one its page points at,
so this module answers two questions at once: does the demo still run, and
does the page still name it.

The render is a smoke test rather than a visual comparison -- the demos that
are worth a pixel-exact baseline are picked up by the visual-regression suite
in ``tests/test_all_scripts.py``.  Here the bar is that the process exits
cleanly and the frame it captured is not blank, which is what catches an API
that moved under a demo nobody has run for a while.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

HERE = str(tests_root(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, 'docs')

#: demo module (in tests/) -> the documentation page that must point at it.
DEMOS = {
    'instancing_batched': 'instancing.html',
    'water_demo': 'water.html',
    'roads_demo': 'roads.html',
    'hud_demo': 'hud.html',
    'crowd_demo': 'characters.html',
    'navmesh_demo': 'navmesh.html',
    'editing_demo': 'editing.html',
    'recording_demo': 'recording.html',
    'telemetry_demo': 'telemetry.html',
    'bake_demo': 'baking.html',
}

#: Frames to run before the automatic exit captures.  Enough that a scene
#: which loads asynchronously or settles over a few frames has arrived.
FRAMES = '40'

#: Demos that open a sample model rather than building their geometry, and the
#: model each wants.  The asset cache makes the first run the only one that
#: needs the network, so these are skipped rather than failed where the file is
#: absent and cannot be fetched -- a machine with no network is not a machine
#: where the demo is broken.
NEEDS_MODEL = {'crowd_demo': 'CesiumMan'}


def _model_available(name):
    try:
        from OpenGLContext.loaders.gltf import sample_model_url
        from OpenGLContext.loaders.resolver import fetch_to_cache
    except Exception:
        return False
    try:
        return os.path.exists(fetch_to_cache(sample_model_url(name)))
    except Exception:
        return False


def _gl_available():
    try:
        import glfw
    except Exception:
        return False
    try:
        if not glfw.init():
            return False
        # GLFW window hints are sticky/process-global; reset them so a prior
        # core-profile test's profile cannot leak into this context.
        glfw.default_window_hints()
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        window = glfw.create_window(64, 64, 't', None, None)
        if not window:
            return False
        glfw.destroy_window(window)
        return True
    except Exception:
        return False


gl = pytest.mark.skipif(not _gl_available(), reason='no GL target available')


class TestEachDemoRenders:
    @gl
    @pytest.mark.slow
    @pytest.mark.parametrize('demo', sorted(DEMOS))
    def test_it_exits_cleanly_with_a_frame(self, demo, tmp_path):
        wanted = NEEDS_MODEL.get(demo)
        if wanted and not _model_available(wanted):
            pytest.skip('%s is not in the asset cache and cannot be fetched'
                        % wanted)
        env = dict(os.environ)
        env.update(
            OPENGLCONTEXT_BACKEND='glfw',
            OPENGLCONTEXT_HIDDEN='1',
            OPENGLCONTEXT_NO_VSYNC='1',
            OPENGLCONTEXT_AUTO_EXIT_FRAMES=FRAMES,
            OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
            OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME=demo,
        )
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, demo + '.py')],
            cwd=ROOT, env=env, timeout=300,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = proc.stdout.decode('utf-8', 'replace')
        assert proc.returncode == 0, output[-3000:]
        shot = tmp_path / (demo + '.png')
        assert shot.exists(), 'no screenshot captured\n' + output[-2000:]
        # A rendered scene compresses to more than a flat frame does.
        assert shot.stat().st_size > 2000, 'blank frame\n' + output[-2000:]


class TestEachDemoIsDocumented:
    """The page has to name the demo, or nobody finds it."""

    @pytest.mark.parametrize('demo,page', sorted(DEMOS.items()))
    def test_the_page_names_the_demo(self, demo, page):
        path = os.path.join(DOCS, page)
        if not os.path.exists(path):
            pytest.skip('docs/ not in this checkout')
        text = open(path, encoding='utf-8', errors='replace').read()
        assert 'tests/%s.py' % demo in text, (
            '%s does not tell the reader to run tests/%s.py' % (page, demo))

    @pytest.mark.parametrize('demo,page', sorted(DEMOS.items()))
    def test_the_page_shows_a_render(self, demo, page):
        path = os.path.join(DOCS, page)
        if not os.path.exists(path):
            pytest.skip('docs/ not in this checkout')
        text = open(path, encoding='utf-8', errors='replace').read()
        image = 'images/demos/%s.jpg' % demo
        assert image in text, '%s has no screenshot of the demo' % page
        assert os.path.exists(os.path.join(DOCS, image)), 'missing ' + image


class TestEveryDemoFileExists:
    @pytest.mark.parametrize('demo', sorted(DEMOS))
    def test_the_demo_is_present(self, demo):
        assert os.path.exists(os.path.join(HERE, demo + '.py'))
