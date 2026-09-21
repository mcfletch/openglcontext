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

#: How many readings each mode gets, the two taken turn about.  Two is what it
#: takes for a moment of machine state to land on one reading rather than on
#: the comparison; see `_both`.
ROUNDS = 2

#: How far above the other a converged reading may sit before the collapsed
#: draws are making the frame worse.  At `SHAPES` the two modes measure the
#: same gather, so their medians land within noise of one another; what is
#: being watched for there is instancing becoming the expensive path, which is
#: a multiple and not a percent.
CONVERGED_MARGIN = 1.10


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
    """The best reading each way, or a skip where there is no GL to have them.

    Turn about, and the best of each rather than one apiece: the two modes are
    separate subprocesses, so anything the machine does between them lands on
    one of the readings and not the other, and a ratio taken across that drift
    is measuring the drift.  Run straight after the rest of the suite, a single
    pair had `on` reading 2.37 ms against a 1.84-2.13 it takes on a machine
    that has been left alone -- enough to put the ratio the wrong side of the
    bar with the draws collapsing exactly as they should.  The quickest reading
    is the one least spent on something else, which is what makes it the
    comparable one.
    """
    best: dict[str, dict] = {}
    for _ in range(ROUNDS):
        for mode in ('on', 'off'):
            reading = _run(mode, shapes)
            if reading is None:
                pytest.skip('no usable GL context for the instancing perf harness')
            if (mode not in best
                    or reading['median_ms'] < best[mode]['median_ms']):
                best[mode] = reading
    return best['on'], best['off']


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
    # With a margin, because two readings that converge are within the noise of
    # each other and a strict ordering between them decides on that noise --
    # which is a coin toss rather than a claim about the engine. What "worse"
    # means here is measurably worse.
    assert on['median_ms'] <= off['median_ms'] * CONVERGED_MARGIN, (
        'instancing should not cost frame time: on=%.2fms off=%.2fms, over the '
        '%.0f%% a converged reading may sit above the other'
        % (on['median_ms'], off['median_ms'], (CONVERGED_MARGIN - 1.0) * 100.0))
