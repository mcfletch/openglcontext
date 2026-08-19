"""What a crowd of animated figures costs, and that the levers actually pull.

Every assertion here is a **ratio** between two ways of doing the same work in
the same run, never a wall-clock bound: a machine busy with the rest of the
suite slows both sides together, so the comparison holds where a stopwatch
would not. What the numbers come to on a given machine is the benchmark's job
(``tests/helpers/_crowd_perf_harness.py``), not this file's.
"""
import json
import os
import subprocess
import sys
import time

import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.character.crowd import Crowd
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
from OpenGLContext.testing.paths import tests_root
from tests.helpers._crowd_asset import crowd_character_glb

HARNESS = os.path.join(str(tests_root(__file__)), 'helpers',
                       '_crowd_perf_harness.py')

#: Enough figures for the per-call overhead a crowd removes to be most of the
#: cost, and few enough that building them is quick.
FIGURES = 48


@pytest.fixture(scope='module')
def build():
    return parse_gltf(crowd_character_glb(joints=57, vertices=1024, clips=6))


def _figures(build, count):
    models = []
    names = None
    for index in range(count):
        model = CharacterModel(load_gltf(document=build))
        model.mixer.pose_write = 'exposed'
        names = names or sorted(model.clips)
        model.play(names[index % len(names)])
        model.mixer.layers[0].tracks[0].time = 0.031 * index
        models.append(model)
    return models


def _seconds(work, frames=12):
    work()                              # once to warm the caches
    started = time.perf_counter()
    for _ in range(frames):
        work()
    return (time.perf_counter() - started) / frames


class TestPosingTogetherBeatsPosingOneAtATime:
    def test_a_crowd_costs_a_fraction_of_the_same_figures_apart(self, build):
        """The whole point of a crowd: one run of arithmetic, not N of them."""
        apart = _figures(build, FIGURES)
        together = _figures(build, FIGURES)
        crowd = Crowd(compute=False)
        for model in together:
            crowd.add(model)

        alone = _seconds(lambda: [m.update(1 / 60.0) for m in apart])
        batched = _seconds(lambda: crowd.update(1 / 60.0))

        assert batched * 4 < alone, (
            'posing %d figures together took %.3f ms against %.3f ms apart'
            % (FIGURES, batched * 1000, alone * 1000))

    def test_a_budget_poses_fewer_of_them_and_costs_less(self, build):
        crowd = Crowd(compute=False)
        for model in _figures(build, FIGURES):
            crowd.add(model)

        everyone = _seconds(lambda: crowd.update(1 / 60.0))
        third = _seconds(lambda: crowd.update(1 / 60.0, budget=FIGURES // 3))

        assert third < everyone


class TestScalingAgainstADriver:
    """The whole frame, offscreen, against a real GPU."""

    @staticmethod
    def _run(figures, frames, **options):
        args = [sys.executable, HARNESS, str(figures), str(frames)]
        args += ['%s=%s' % item for item in options.items()]
        result = subprocess.run(args, capture_output=True, text=True, timeout=900)
        if result.returncode != 0:
            raise AssertionError('crowd harness failed:\n%s\n%s'
                                 % (result.stdout[-3000:], result.stderr[-3000:]))
        return json.loads(result.stdout.strip().split('\n')[-1])

    @pytest.mark.slow
    def test_a_crowd_animates_for_less_than_the_same_figures_apart(self):
        together = self._run(120, 60, crowd=1)
        apart = self._run(120, 60, crowd=0)

        assert together['update_ms'] * 3 < apart['update_ms'], (together, apart)

    @pytest.mark.slow
    def test_the_animation_half_leaves_the_frame_to_the_drawing(self):
        """A hundred and twenty figures must not spend the frame being posed.

        Not a stopwatch on the machine: what is asserted is that animating them
        costs less than drawing them, which is where the work belongs once the
        pose pipeline is doing its job.
        """
        measured = self._run(120, 60, crowd=1)

        assert measured['update_ms'] < measured['draw_ms'], measured
