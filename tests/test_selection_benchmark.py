#!/usr/bin/env python
"""Selection/Picking Performance Benchmark

This test measures the performance of the selection rendering system
with various scene complexities and simulated mouse events.

Usage:
    python tests/test_selection_benchmark.py [--objects N] [--events M] [--iterations I]

Environment:
    OPENGLCONTEXT_PROFILE=core    Use core profile (default)
    OPENGLCONTEXT_BACKEND=glfw    Use GLFW backend (default)
"""
import os
import sys
import time
import argparse
import json
from datetime import datetime
from pathlib import Path

# Force core profile and GLFW for consistent testing
os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.arrays import array, zeros
from OpenGLContext.events.mouseevents import MouseButtonEvent
import numpy as np
import random


class SelectionBenchmark:
    """Benchmark results collector."""

    def __init__(self, name: str, num_objects: int, num_events: int):
        self.name = name
        self.num_objects = num_objects
        self.num_events = num_events
        self.selection_times = []
        self.render_times = []
        self.total_frames = 0
        self.start_time = None
        self.end_time = None

    def record_selection(self, duration: float):
        self.selection_times.append(duration)

    def record_render(self, duration: float):
        self.render_times.append(duration)
        self.total_frames += 1

    def start(self):
        self.start_time = time.perf_counter()

    def stop(self):
        self.end_time = time.perf_counter()

    def summary(self) -> dict:
        if not self.render_times:
            return {'error': 'No render data collected'}

        render_times = np.array(self.render_times) * 1000  # Convert to ms
        total_time = self.end_time - self.start_time if self.end_time else 0

        return {
            'name': self.name,
            'num_objects': self.num_objects,
            'num_events': self.num_events,
            'total_frames': self.total_frames,
            'total_time_sec': total_time,
            'render': {
                'count': len(self.render_times),
                'mean_ms': float(np.mean(render_times)),
                'std_ms': float(np.std(render_times)),
                'min_ms': float(np.min(render_times)),
                'max_ms': float(np.max(render_times)),
                'median_ms': float(np.median(render_times)),
                'p95_ms': float(np.percentile(render_times, 95)),
                'p99_ms': float(np.percentile(render_times, 99)),
                'fps': self.total_frames / total_time if total_time > 0 else 0,
            }
        }


class SyntheticMouseEvent(MouseButtonEvent):
    """Synthetic mouse event for benchmarking."""

    def __init__(self, x, y, button=0, state=1):
        super().__init__()
        self.button = button
        self.state = state
        self.modifiers = (False, False, False)
        self.pickPoint = (x, y)

    def getKey(self):
        """Return the event key for the pick event dictionary."""
        return (self.button, self.state, self.modifiers)


class BenchmarkContext(BaseContext):
    """Context for benchmarking selection performance."""

    initialPosition = (0, 0, 50)
    num_objects = 1000
    num_events_per_frame = 10
    num_iterations = 100
    benchmark = None
    current_iteration = 0
    warmup_frames = 10
    _results = None

    def OnInit(self):
        """Create a scene with many objects for benchmarking."""
        print(f"Creating scene with {self.num_objects} objects...", flush=True)

        self.benchmark = SelectionBenchmark(
            name='baseline',
            num_objects=self.num_objects,
            num_events=self.num_events_per_frame
        )

        # Create grid of boxes
        children = []
        grid_size = int(np.ceil(np.sqrt(self.num_objects)))
        spacing = 2.0
        offset = (grid_size - 1) * spacing / 2

        for i in range(self.num_objects):
            x = (i % grid_size) * spacing - offset
            y = (i // grid_size) * spacing - offset
            z = random.uniform(-1, 1)

            # Vary colors for visual distinction
            r = (i % 10) / 10.0
            g = ((i // 10) % 10) / 10.0
            b = ((i // 100) % 10) / 10.0

            children.append(
                basenodes.Transform(
                    translation=(x, y, z),
                    children=[
                        basenodes.Shape(
                            appearance=basenodes.Appearance(
                                material=basenodes.Material(
                                    diffuseColor=(r, g, b),
                                )
                            ),
                            geometry=basenodes.Box(size=(0.8, 0.8, 0.8))
                        )
                    ]
                )
            )

        self.sg = basenodes.sceneGraph(children=children)
        print(f"Scene created with {len(children)} objects", flush=True)
        print(f"Running {self.num_iterations} iterations with {self.num_events_per_frame} pick events per frame", flush=True)

        # Get viewport size for generating random pick points
        self._viewport_size = None
        self._frame_start = None

    def OnIdle(self):
        """Drive the benchmark."""
        if self.current_iteration >= self.num_iterations + self.warmup_frames:
            print(f"Benchmark complete, finishing...", flush=True)
            self._finish_benchmark()
            return

        # Skip warmup frames
        if self.current_iteration < self.warmup_frames:
            self.current_iteration += 1
            self.triggerRedraw()
            return

        if self.current_iteration == self.warmup_frames:
            self.benchmark.start()
            print(f"Warmup complete, starting benchmark...", flush=True)

        self.current_iteration += 1

        # Print progress every 10 iterations
        if (self.current_iteration - self.warmup_frames) % 10 == 0:
            print(f"  Iteration {self.current_iteration - self.warmup_frames}/{self.num_iterations}", flush=True)

        # Inject pick events before triggering redraw
        self._inject_pick_events()

        self._frame_start = time.perf_counter()
        self.triggerRedraw()

    def OnDraw(self, force=0):
        """Override to measure timing."""
        # Call parent draw
        result = super().OnDraw(force=force)

        # Record timing after warmup
        if self._frame_start is not None and self.current_iteration > self.warmup_frames:
            frame_time = time.perf_counter() - self._frame_start
            self.benchmark.record_render(frame_time)

        return result

    def _inject_pick_events(self):
        """Inject simulated mouse pick events."""
        if self._viewport_size is None:
            self._viewport_size = self.getViewPort()

        width, height = int(self._viewport_size[0]), int(self._viewport_size[1])
        if not width or not height:
            return

        # Clear existing pick events
        self.pickEvents.clear()

        # Create pick events - mix of centered (likely to hit) and random (likely to miss)
        # This simulates realistic mouse movement over a scene
        center_x, center_y = width // 2, height // 2
        for i in range(self.num_events_per_frame):
            if i % 3 == 0:
                # Every 3rd pick is near center (likely to hit objects)
                x = center_x + random.randint(-width//4, width//4)
                y = center_y + random.randint(-height//4, height//4)
            else:
                # Other picks are random (may or may not hit)
                x = random.randint(10, width - 10)
                y = random.randint(10, height - 10)

            # Create a synthetic mouse event
            event = SyntheticMouseEvent(x, y, button=0, state=1)

            # Add to context's pick events with unique key
            key = (event.type, (i, x, y))
            self.pickEvents[key] = event

    def _finish_benchmark(self):
        """Finish the benchmark and report results."""
        self.benchmark.stop()
        results = self.benchmark.summary()

        if 'error' in results:
            print(f"Benchmark error: {results['error']}", flush=True)
            sys.stdout.flush()
            self.OnQuit()
            return

        print("\n" + "=" * 60, flush=True)
        print("SELECTION BENCHMARK RESULTS", flush=True)
        print("=" * 60, flush=True)
        print(f"Objects: {results['num_objects']}", flush=True)
        print(f"Pick events per frame: {results['num_events']}", flush=True)
        print(f"Total frames: {results['total_frames']}", flush=True)
        print(f"Total time: {results['total_time_sec']:.2f} seconds", flush=True)
        print(flush=True)
        print("Frame Render Performance (includes selection pass):", flush=True)
        print(f"  Mean:   {results['render']['mean_ms']:.2f} ms", flush=True)
        print(f"  Std:    {results['render']['std_ms']:.2f} ms", flush=True)
        print(f"  Min:    {results['render']['min_ms']:.2f} ms", flush=True)
        print(f"  Max:    {results['render']['max_ms']:.2f} ms", flush=True)
        print(f"  Median: {results['render']['median_ms']:.2f} ms", flush=True)
        print(f"  P95:    {results['render']['p95_ms']:.2f} ms", flush=True)
        print(f"  P99:    {results['render']['p99_ms']:.2f} ms", flush=True)
        print(f"  FPS:    {results['render']['fps']:.1f}", flush=True)
        print("=" * 60, flush=True)

        # Save results to file
        output_dir = Path(__file__).parent / 'benchmark_results'
        output_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f'selection_benchmark_{timestamp}.json'

        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {output_file}", flush=True)

        # Store for programmatic access
        BenchmarkContext._results = results

        # Ensure output is flushed before quitting
        sys.stdout.flush()
        sys.stderr.flush()

        # Exit
        self.OnQuit()


def run_benchmark(num_objects: int = 1000, num_events: int = 10,
                  num_iterations: int = 100) -> dict:
    """Run a single benchmark and return results."""
    BenchmarkContext.num_objects = num_objects
    BenchmarkContext.num_events_per_frame = num_events
    BenchmarkContext.num_iterations = num_iterations
    BenchmarkContext._results = None

    # Run the context main loop
    BenchmarkContext.ContextMainLoop()

    return BenchmarkContext._results or {}


def main():
    parser = argparse.ArgumentParser(
        description='Selection/Picking Performance Benchmark'
    )
    parser.add_argument(
        '--objects', '-o', type=int, default=1000,
        help='Number of objects in the scene (default: 1000)'
    )
    parser.add_argument(
        '--events', '-e', type=int, default=10,
        help='Number of pick events per frame (default: 10)'
    )
    parser.add_argument(
        '--iterations', '-i', type=int, default=100,
        help='Number of benchmark iterations (default: 100)'
    )

    args = parser.parse_args()

    print(f"Selection Benchmark")
    print(f"Profile: {os.environ.get('OPENGLCONTEXT_PROFILE', 'compatibility')}")
    print(f"Backend: {os.environ.get('OPENGLCONTEXT_BACKEND', 'default')}")
    print()

    run_benchmark(
        num_objects=args.objects,
        num_events=args.events,
        num_iterations=args.iterations
    )


if __name__ == '__main__':
    main()
