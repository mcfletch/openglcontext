"""What the per-frame gather hands the rest of the frame.

`FlatPass.renderSet` is the first thing a frame does and the widest: every
renderable path in the scene passes through it, and what it produces is read
again by the shadow pass, by the level-of-detail selection and by the draw
itself.  These drive it with a real scenegraph and no GL context -- the gather
is arithmetic over the scenegraph's own caches, and nothing in it touches a
driver.
"""
import numpy as np
import pytest

from OpenGLContext import frustum
from OpenGLContext.passes._flat import FlatPass
from OpenGLContext.scenegraph import basenodes


def _shape(size=(2, 2, 2)):
    return basenodes.Shape(geometry=basenodes.Box(size=size))


def _scene(count=3, spacing=4.0):
    """A scenegraph of `count` boxes, each under its own Transform."""
    moves = [basenodes.Transform(translation=(index * spacing, 0, 0),
                                 children=[_shape()])
             for index in range(count)]
    return basenodes.sceneGraph(children=moves), moves


@pytest.fixture
def gather():
    """A pass over a three-box scene, with a frustum that keeps everything."""
    scene, moves = _scene()
    passing = FlatPass(scene, [])
    passing.frustum = frustum.Frustum(planes=np.zeros((0, 4), 'f'))
    return passing, moves


class TestTheGatherKeepsTransformIdentity:
    """A record's transform matrix is the scenegraph's own cached object.

    Everything downstream that remembers a per-object answer between frames --
    the shadow pass's caster geometry above all -- tells "this has not moved"
    from the matrix being the *same object* it was handed last frame.  The
    scenegraph's transform cache provides exactly that: one object while a node
    is still, a fresh one the moment it moves.  A gather that handed out rows of
    a buffer it refills each frame would give every object a new identity every
    frame, and every such memo would miss every time.
    """

    def test_a_records_matrix_is_the_paths_own(self, gather):
        passing, _moves = gather
        for record in passing.renderSet(np.eye(4, dtype='f')):
            assert record[2] is record[4].transformMatrix()

    def test_an_unmoved_path_keeps_the_same_matrix_between_frames(self, gather):
        passing, _moves = gather
        first = {id(r[4]): r[2] for r in passing.renderSet(np.eye(4, dtype='f'))}
        second = passing.renderSet(np.eye(4, dtype='f'))
        assert second
        for record in second:
            assert record[2] is first[id(record[4])]

    def test_a_moved_path_gets_a_fresh_matrix(self, gather):
        passing, moves = gather
        before = {id(r[4]): r[2] for r in passing.renderSet(np.eye(4, dtype='f'))}
        moves[1].translation = (0, 9, 0)
        moved = still = 0
        for record in passing.renderSet(np.eye(4, dtype='f')):
            if record[2] is before[id(record[4])]:
                still += 1
            else:
                moved += 1
                assert record[2][3][1] == pytest.approx(9.0)
        assert (moved, still) == (1, 2)

    def test_every_records_matrix_places_its_own_node(self, gather):
        """Identity is not enough: the values have to be each path's own."""
        passing, _moves = gather
        found = sorted(float(r[2][3][0])
                       for r in passing.renderSet(np.eye(4, dtype='f')))
        assert found == pytest.approx([0.0, 4.0, 8.0])

    def test_the_modelview_still_carries_the_camera(self, gather):
        """Slot 1 is the record's matrix through the camera, and stays so."""
        passing, _moves = gather
        camera = np.eye(4, dtype='f')
        camera[3, 2] = -10.0
        for record in passing.renderSet(camera):
            assert np.allclose(record[1], np.asarray(record[2]) @ camera)
