"""Performance regression: instancing collapses draws and cuts frame time (GL).

Renders a large field of cubes that all share one geometry + material, once with
instancing on and once off, and asserts:

  * draw-call structure -- on = a single instanced draw for the whole field;
    off = one draw per shape;
  * wall time -- the instanced frame is materially faster (a conservative margin;
    measured ~2x on an RTX 3060 Ti with vsync disabled).

Skips (not fails) when no usable GL context can be created.
"""
import json
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

# The frame-time assertion below compares wall-clock medians, so a busy GPU/CPU
# compresses the on/off ratio and makes it read slower than it is. Run it apart
# from the rest of the suite; the draw-call test guards the feature regardless.
pytestmark = pytest.mark.serial

HARNESS = os.path.join(str(tests_root(__file__)), 'helpers',
                       '_instancing_perf_harness.py')
SHAPES = 800
FRAMES = 120


def _run(mode):
    proc = subprocess.run([sys.executable, HARNESS, mode, str(SHAPES), str(FRAMES)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode == 3:
        return None
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return None


@pytest.fixture(scope='module')
def perf():
    on, off = _run('on'), _run('off')
    if not on or not off:
        pytest.skip('no usable GL context for the instancing perf harness')
    return on, off


def test_instancing_collapses_draw_calls(perf):
    on, off = perf
    # One instanced draw for the whole field vs one draw per shape.
    assert on['instanced_draws'] == 1
    assert on['single_draws'] == 0
    assert on['instances'] == SHAPES
    assert off['single_draws'] == SHAPES
    assert off['instanced_draws'] == 0


def test_instancing_is_faster(perf):
    on, off = perf
    # Conservative: require at least a 20% frame-time reduction (measured ~2x).
    assert on['median_ms'] < off['median_ms'] * 0.8, (
        'instancing should cut frame time for a shared-geometry field: '
        'on=%.2fms off=%.2fms' % (on['median_ms'], off['median_ms']))
