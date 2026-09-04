"""Performance regression: instancing collapses draws and cuts frame time (GL).

Renders a large field of cubes that all share one geometry + material, once with
instancing on and once off, and asserts:

  * draw-call structure -- on = a single instanced draw for the whole field;
    off = one draw per shape;
  * wall time -- the instanced frame is materially faster (a conservative margin;
    measured ~2x on an RTX 3060 Ti with vsync disabled).

The time is measured **up to the buffer swap and no further**, with the GPU
caught up: a swap blocks until the compositor wants another frame, and a
compositor that throttles it to the display -- as a Wayland one does, whatever
`swap_interval(0)` asked for -- makes both modes come out at the frame interval
and drives the ratio between them to 1. See the harness's `SwapBuffers`.

Skips (not fails) when no usable GL context can be created.
"""
import json
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

# The frame-time assertions below compare wall-clock medians, so a busy GPU/CPU
# compresses the on/off ratio and makes it read slower than it is. Run them apart
# from the rest of the suite; the draw-call test guards the feature regardless.
# This is a general hazard rather than a quirk of this file: any assertion about
# wall-clock time is a claim about the machine as much as about the code -- which
# is also why those two carry `performance`, and are passed over where the
# machine rasterises on the CPU.
pytestmark = pytest.mark.serial

HARNESS = os.path.join(str(tests_root(__file__)), 'helpers',
                       '_instancing_perf_harness.py')

#: How many cubes the draw-structure check uses.  Large, because what it is
#: asserting is that a *field* collapses to one draw.
SHAPES = 800

#: How many the frame-time check uses.  Smaller on purpose: the pass builds one
#: model-view matrix per shape in Python every frame whether or not the draws
#: are collapsed, and by 800 that shared cost is most of the frame -- so the
#: two modes converge on it and the ratio between them says more about the
#: gather than about the draws.  At this size the draw submission is what
#: dominates, which is the thing instancing changes.
TIMED_SHAPES = 200
FRAMES = 120


def _run(mode, shapes=SHAPES):
    """The harness's reading, or None where this machine cannot render at all.

    Only exit 3 -- the harness's own "no GL" -- is a reason to go without a
    measurement. Anything else is the harness failing, and is raised with what
    it said: a run that quietly skips is a performance gate reporting green
    while measuring nothing, which is the one thing it must never do.
    """
    proc = subprocess.run([sys.executable, HARNESS, mode, str(shapes), str(FRAMES)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode == 3:
        return None
    if proc.returncode != 0:
        raise AssertionError(
            'the instancing harness (%s, %d shapes) exited %d:\n%s'
            % (mode, shapes, proc.returncode, proc.stderr[-2000:]))
    for line in reversed(proc.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith('{'):
            try:
                return json.loads(line)
            except ValueError:
                continue
    raise AssertionError(
        'the instancing harness (%s, %d shapes) exited 0 but printed no '
        'reading:\nstdout: %s\nstderr: %s'
        % (mode, shapes, proc.stdout[-1000:], proc.stderr[-2000:]))


def _both(shapes):
    """One reading each way, or a skip where there is no GL to have them with."""
    on, off = _run('on', shapes), _run('off', shapes)
    if on is None or off is None:
        pytest.skip('no usable GL context for the instancing perf harness')
    return on, off


@pytest.fixture(scope='module')
def perf():
    return _both(SHAPES)


@pytest.fixture(scope='module')
def timed():
    return _both(TIMED_SHAPES)


def test_instancing_collapses_draw_calls(perf):
    on, off = perf
    # One instanced draw for the whole field vs one draw per shape.
    assert on['instanced_draws'] == 1
    assert on['single_draws'] == 0
    assert on['instances'] == SHAPES
    assert off['single_draws'] == SHAPES
    assert off['instanced_draws'] == 0


@pytest.mark.performance
def test_instancing_is_faster(timed):
    on, off = timed
    # Conservative: require at least a 20% frame-time reduction (measured ~2x).
    assert on['median_ms'] < off['median_ms'] * 0.8, (
        'instancing should cut frame time for a shared-geometry field: '
        'on=%.2fms off=%.2fms' % (on['median_ms'], off['median_ms']))


@pytest.mark.performance
def test_instancing_is_never_slower_even_at_scale(perf):
    """At 800 shapes the per-frame gather is most of the cost and the two
    modes converge on it, so the *margin* is not worth asserting there — but
    collapsing the draws must never make a frame worse."""
    on, off = perf
    assert on['median_ms'] <= off['median_ms'], (
        'instancing should not cost frame time: on=%.2fms off=%.2fms'
        % (on['median_ms'], off['median_ms']))
