"""What a frame costs per object, held to a figure (GL).

A scene's frame time is very nearly linear in the number of objects in it
rather than in what is in them, so the number worth tracking is the slope: the
processor time one more object adds to every frame. This renders a field of
shadow-casting level-of-detail chains at two sizes and reads the slope off the
difference, which cancels the fixed cost of a frame.

Milliseconds are a claim about the machine as much as about the engine, so the
timing check carries ``performance`` and the whole file carries ``serial``.
What does not depend on the machine is the *work* a frame does, and that is
what the rest of these assert: how many times a path is asked where it is, how
many casters have their world geometry derived, and how many times the scene's
levels are chosen. Those are what the milliseconds follow from, and a
regression shows in them first and identically everywhere.

Skips (not fails) when no usable GL context can be created.
"""
import json
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

pytestmark = pytest.mark.serial

HARNESS = os.path.join(str(tests_root(__file__)), 'helpers',
                       '_frame_cost_harness.py')

#: The two sizes the slope is read between. Far enough apart that the
#: difference is the objects rather than the noise.
SMALL = 60
LARGE = 360
FRAMES = 90

#: Processor time one more object may add to a frame. Generous against the
#: measured figure, because this has to pass on a slow machine too; what it is
#: here to catch is a change that puts a per-object cost back into the frame,
#: which shows up as a multiple rather than as a few percent.
CEILING_US = 45.0


def _run(objects, camera='still'):
    """The harness's reading, or None where this machine cannot render at all.

    Only exit 3 -- the harness's own "no GL" -- is a reason to go without a
    measurement. Anything else is the harness failing, and is raised with what
    it said: a run that quietly skips is a gate reporting green while measuring
    nothing.
    """
    done = subprocess.run(
        [sys.executable, HARNESS, str(objects), str(FRAMES), camera],
        capture_output=True, text=True, timeout=600)
    if done.returncode == 3:
        return None
    if done.returncode != 0:
        raise AssertionError(
            'the frame-cost harness (%d objects, %s) exited %d:\n%s'
            % (objects, camera, done.returncode, done.stderr[-2000:]))
    for line in reversed(done.stdout.strip().splitlines()):
        if line.strip().startswith('{'):
            return json.loads(line.strip())
    raise AssertionError(
        'the frame-cost harness (%d objects, %s) exited 0 but printed no '
        'reading:\nstdout: %s\nstderr: %s'
        % (objects, camera, done.stdout[-1000:], done.stderr[-2000:]))


def _reading(objects, camera='still'):
    found = _run(objects, camera)
    if found is None:
        pytest.skip('no usable GL context for the frame-cost harness')
    return found


@pytest.fixture(scope='module')
def still():
    return _reading(SMALL), _reading(LARGE)


@pytest.fixture(scope='module')
def moving():
    return _reading(LARGE, 'moving')


class TestWhatAFrameWorksOutPerObject:
    """The same answer on any machine: how much a frame does, not how fast."""

    def test_a_path_is_asked_where_it_is_twice_a_frame_at_most(self, still):
        """Once by the gather, once by the level choice, and no third time.

        Every renderable path goes through one walk of the scene, which the
        frustum cull, the shadow caster pool and the draw all read. Level
        selection runs before that walk -- it has to, since a level change
        replaces the subtree the walk covers -- so its own paths are asked
        separately. A third asking would mean something walked the scene again.
        """
        for reading in still:
            objects = reading['objects']
            assert reading['world_matrices'] <= 2 * objects + 8, reading

    def test_a_still_scene_derives_no_caster_geometry(self, still):
        """Nothing moved, so every caster's world geometry already stands."""
        for reading in still:
            assert reading['caster_derivations'] == 0, reading

    def test_a_still_scene_chooses_no_levels(self, still):
        """Neither the camera nor anything in the scene has moved."""
        for reading in still:
            assert reading['level_choices'] == 0, reading

    def test_a_moving_camera_chooses_levels_once_a_frame(self, moving):
        """Once for the whole scene, rather than once per node."""
        assert moving['level_choices'] == 1.0, moving

    def test_a_moving_camera_still_reuses_its_casters(self, moving):
        """The camera is not what a caster's world geometry depends on.

        A level changing over brings new geometry with it, so this is not
        nothing; it is far less than the scene.
        """
        assert moving['caster_derivations'] < moving['objects'] / 4.0, moving


@pytest.mark.performance
class TestWhatAFrameCostsPerObject:
    def test_the_cost_per_object_is_under_its_ceiling(self, still):
        small, large = still
        per_object = ((large['median_ms'] - small['median_ms'])
                      / (large['objects'] - small['objects']) * 1000.0)
        assert per_object < CEILING_US, (
            '%.1f us of frame time per object, over the %.0f us ceiling: '
            '%d objects in %.2f ms, %d in %.2f'
            % (per_object, CEILING_US, small['objects'], small['median_ms'],
               large['objects'], large['median_ms']))

    def test_a_still_scene_is_not_dearer_than_a_moving_one(self, still, moving):
        """The shortcuts a still scene takes must actually pay."""
        assert still[1]['median_ms'] <= moving['median_ms'], (
            'still=%.2fms moving=%.2fms at %d objects'
            % (still[1]['median_ms'], moving['median_ms'], LARGE))
