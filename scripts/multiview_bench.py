#! /usr/bin/env python
"""What a layout of several views costs, measured against one view.

Draws the same scene through one view and through a four-view quad, once for
every strategy this driver can run, and reports the frame time and the draw
calls each took. What an editor wants to know before it opens four views on a
world: how much slower its frame becomes, and how much of that the shared
strategies take back.

::

    scripts/multiview_bench.py --model lantern.glb
    scripts/multiview_bench.py --boxes 400 --frames 120 --size 1280 960

The frame time is the median over the measured frames, after ``--warmup``
frames that are thrown away, so a first frame that compiles programs and
uploads buffers is not counted. Run it on an idle machine: it is a wall-clock
measurement, and the summary says which GPU answered.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import Any, List, Optional, Sequence, Tuple

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
os.environ.setdefault('OPENGLCONTEXT_DISABLE_FPS_DISPLAY', '1')
# Image-based lighting that adapts to the frame rate would change what is
# drawn while the frame rate is what is being measured.
os.environ.setdefault('OPENGLCONTEXT_IBL', 'analytic')

import numpy as np  # noqa: E402

from OpenGLContext import testingcontext  # noqa: E402
from OpenGLContext.edit.quadview import QuadView  # noqa: E402
from OpenGLContext.passes import multiview, renderpass  # noqa: E402
from OpenGLContext.scenegraph import basenodes  # noqa: E402


class Result:
    """One case's numbers: the frame times it measured and the draws it counted."""

    def __init__(self, name: str, times: Sequence[float], draws: int,
                 strategy: Optional[str]) -> None:
        self.name = name
        self.times = list(times)
        self.draws = draws
        self.strategy = strategy

    @property
    def median_ms(self) -> float:
        return statistics.median(self.times) * 1000.0

    @property
    def fastest_ms(self) -> float:
        return min(self.times) * 1000.0


def scene_of(model: Optional[str], boxes: int) -> Tuple[list, Any, Any]:
    """``(children, minimum, maximum)``: the scene to draw and the box around it."""
    children: List[Any] = [
        basenodes.Background(skyColor=[(0.15, 0.17, 0.2)]),
        basenodes.DirectionalLight(direction=(-0.4, -0.6, -1.0), intensity=1.0),
    ]
    if model:
        from OpenGLContext.loaders.gltf import load_gltf
        scene = load_gltf(model)
        children.append(scene.group)
        return children, np.asarray(scene.minimum, 'd'), np.asarray(scene.maximum, 'd')
    side = int(np.ceil(boxes ** (1.0 / 3.0)))
    step = 2.5
    placed = 0
    for x in range(side):
        for y in range(side):
            for z in range(side):
                if placed >= boxes:
                    break
                placed += 1
                children.append(basenodes.Transform(
                    translation=(x * step, y * step, z * step),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(1, 1, 1)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(
                                (x + 1) / side, (y + 1) / side, (z + 1) / side))))]))
    extent = (side - 1) * step
    return children, np.zeros(3) - 1.0, np.array([extent, extent, extent]) + 1.0


def measure(children: list, bounds: Tuple[Any, Any], views: int,
            strategy: Optional[str], size: Tuple[int, int],
            frames: int, warmup: int) -> Result:
    """Render one case and answer what it cost.

    ``views`` is 1 for a single view of the scene or 4 for the editor's quad;
    ``strategy`` pins how a multi-view frame is drawn.
    """
    Base: Any = testingcontext.getInteractive()
    times: List[float] = []
    counted: List[int] = []

    class _Bench(Base):
        from OpenGLContext.contextdefinition import ContextDefinition
        contextDefinition = ContextDefinition(size=size)

        def OnInit(self) -> None:
            self.sg = basenodes.sceneGraph(children=children)
            if strategy is not None:
                self.contextDefinition.multiview = strategy
            if views > 1:
                self.quad = QuadView()
                self.viewLayout = self.quad.layout
                self.quad.layout.arrange(*self.getViewPort())
                self.quad.frame(*bounds)
            else:
                from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
                from OpenGLContext.views import ViewLayout
                orbit = OrbitView(nearest=1e-3, furthest=1e7)
                orbit.frame_box(bounds[0], bounds[1], size)
                self.viewLayout = ViewLayout.single(
                    OrbitViewPlatform(orbit, size), name='single')

        def OnIdle(self, *arguments: Any) -> None:
            if len(times) >= frames + warmup:
                self.ContextMainLoop and self.setCurrent()
                raise SystemExit(0)
            started = time.perf_counter()
            self.OnDraw(force=1)
            times.append(time.perf_counter() - started)
            flat = renderpass.FLAT
            counted.append(int(getattr(flat.stats, 'draws', 0)) if flat else 0)

    try:
        _Bench.ContextMainLoop()
    except SystemExit:
        pass
    measured = times[warmup:] or times
    draws = counted[-1] if counted else 0
    name = '1 view' if views == 1 else '%d views, %s' % (views, strategy or 'auto')
    return Result(name, measured, draws, strategy)


def report(results: Sequence[Result]) -> str:
    """The table, with each case against the single-view one."""
    base = results[0]
    lines = ['%-26s %10s %10s %8s %9s' % (
        'case', 'median ms', 'best ms', 'draws', 'vs 1 view')]
    for result in results:
        lines.append('%-26s %10.2f %10.2f %8d %8.2fx' % (
            result.name, result.median_ms, result.fastest_ms, result.draws,
            result.median_ms / base.median_ms if base.median_ms else float('nan')))
    return '\n'.join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--model', help='a glTF/GLB file to draw')
    parser.add_argument('--boxes', type=int, default=400,
                        help='boxes in the generated scene, where no model is given')
    parser.add_argument('--frames', type=int, default=60, help='frames measured per case')
    parser.add_argument('--warmup', type=int, default=20, help='frames thrown away first')
    parser.add_argument('--size', type=int, nargs=2, default=(1280, 960),
                        metavar=('WIDTH', 'HEIGHT'))
    parser.add_argument('--strategy', action='append', dest='strategies',
                        help='only this strategy (repeatable); default is every '
                             'one this driver can run')
    options = parser.parse_args(argv)

    children, low, high = scene_of(options.model, options.boxes)
    size = (int(options.size[0]), int(options.size[1]))
    results = [measure(children, (low, high), 1, None, size,
                       options.frames, options.warmup)]
    found = multiview.MultiviewCapabilities.detect()
    runnable = [name for name in found.available() if name in multiview.IMPLEMENTED]
    wanted = options.strategies or runnable
    for strategy in wanted:
        if strategy not in runnable:
            print('%s: this driver cannot run it' % (strategy,), file=sys.stderr)
            continue
        results.append(measure(children, (low, high), 4, strategy, size,
                               options.frames, options.warmup))
    from OpenGLContext.testing.glcontext import describe_gl
    print('%s' % (describe_gl(),))
    print('scene: %s, %d frames of %dx%d' % (
        options.model or '%d boxes' % options.boxes, options.frames, size[0], size[1]))
    print(report(results))
    return 0


if __name__ == '__main__':
    sys.exit(main())
