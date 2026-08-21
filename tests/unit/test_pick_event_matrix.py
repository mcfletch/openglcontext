"""A pick event unprojects against the camera, not the last thing drawn
(:mod:`OpenGLContext.passes.selection`, :mod:`OpenGLContext.passes.asyncpick`).

``event.unproject()`` turns the pick point and its depth back into a world
coordinate, and needs the model-view the frame was drawn with.  The pass keeps
two matrices: ``modelView``, set once from the view platform, and ``matrix``,
which the traversal rewrites for every node it visits.  By the time the picks
are dispatched the traversal has finished, so ``matrix`` holds whatever node
happened to be drawn last.

Handing that one to the event puts every picked point in that node's local
space -- offset by its transform, and by a different amount whenever the draw
order changes.  Anything asking where the pointer is in the world is wrong by
that offset: :mod:`OpenGLContext.edit.surface`'s ``pointer_from`` and
``ray_from``, and so every editor tool built on them.
"""
import numpy as np

from OpenGLContext.passes import selection


CAMERA = np.identity(4, 'f')
CAMERA[3, :3] = (0.0, 0.0, -70.0)          # the camera, 70 back

LAST_NODE = np.identity(4, 'f')
LAST_NODE[3, :3] = (-8.0, -34.0, -66.0)    # camera composed with a block's transform


class _Event:
    def __init__(self):
        self.modelViewMatrix = None
        self.projectionMatrix = None
        self.viewport = None
        self.viewCoordinate = None
        self.paths = None

    def getPickPoint(self):
        return (100, 120)

    def setObjectPaths(self, paths):
        self.paths = paths


class _Buffer:
    _initialized = True
    id_map: dict = {}

    def read_pixel(self, x, y):
        return 0, 0.5


class _Context:
    def ProcessEvent(self, event):
        pass


class _Mode:
    context = _Context()


class _Pass(selection.SelectionMixin):
    """Just enough of a pass to run the dispatch."""

    projection = np.identity(4, 'f')
    viewport = (0, 0, 300, 300)

    def __init__(self):
        self.modelView = CAMERA
        self.matrix = LAST_NODE          # as the traversal leaves it

    def _getSelectionBuffer(self):
        return _Buffer()


class TestTheEventCarriesTheCameraMatrix:
    def _dispatched(self):
        held = _Pass()
        event = _Event()
        held.processPickEventsFromBuffer(_Mode(), {'k': event})
        return event

    def test_it_is_not_the_last_drawn_node(self):
        found = self._dispatched().modelViewMatrix
        assert found is not None, 'no matrix reached the event'
        assert not np.allclose(np.asarray(found), LAST_NODE), (
            'the event carries the last drawn node transform, so every picked '
            'point is offset by it')

    def test_it_is_the_camera(self):
        found = np.asarray(self._dispatched().modelViewMatrix)
        assert np.allclose(found, CAMERA)
