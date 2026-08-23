"""Visual-regression smoke test: physics demos render and capture (GL subprocess).

Each demo doubles as its phase's visual test (plan §Demos).  We run a few key
demos through the auto-exit/capture harness and assert they exit cleanly and
produce a non-blank frame — this covers the debug-render overlay (test 17) and
the frame-loop coupling (test 18).  Skipped when no GL target is available.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.glcontext import gl_available
from OpenGLContext.testing.paths import tests_root
HERE = str(tests_root(__file__))
ROOT = os.path.dirname(HERE)
DEMOS = ['physics_room_drop', 'physics_cook_view', 'physics_navigate',
         'physics_bounce', 'physics_triggers']


gl = pytest.mark.skipif(not gl_available(), reason='no GL target available')


@gl
@pytest.mark.parametrize('demo', DEMOS)
def test_demo_renders_a_nonblank_frame(demo, tmp_path):
    env = dict(os.environ)
    env.update(
        OPENGLCONTEXT_BACKEND='glfw',
        OPENGLCONTEXT_AUTO_EXIT_FRAMES='40',
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR=str(tmp_path),
        OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME=demo,
    )
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, demo + '.py')],
        cwd=ROOT, env=env, timeout=90,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout.decode('utf-8', 'replace')[-2000:]
    png = tmp_path / (demo + '.png')
    assert png.exists(), 'no screenshot captured'
    # a rendered scene compresses to more than a flat/blank frame
    assert png.stat().st_size > 2000


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
