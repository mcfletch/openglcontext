"""What a mousein/mouseout traversal is handed
(:mod:`OpenGLContext.events.mouseevents`).

The pointer moving between two shapes is reported as the *delta* between the
path it was on and the path it is on now: the managers take the common prefix
and slice it off. What comes back is handed on as ``event.currentPath``, and a
handler asks it for ``transformMatrix()`` -- so the slice has to stay a
``NodePath`` rather than decaying to a list.

pyvrml97 keeps the type across a slice, and this holds the engine to that: it
is the one property of the dependency the event system reads without checking.
"""
import pytest

from OpenGLContext.events import mouseevents
from OpenGLContext.scenegraph import basenodes

vrml_nodepath = pytest.importorskip('vrml.vrml97.nodepath')
NodePath = vrml_nodepath.NodePath


@pytest.fixture
def scene():
    """A transform holding two shapes, with a path to each."""
    left, right = basenodes.Shape(), basenodes.Shape()
    root = basenodes.Transform(translation=(1, 2, 3), children=[left, right])
    return root, NodePath([root, left]), NodePath([root, right])


class _Event:
    def __init__(self, lastPath, newPath):
        self.lastPath = lastPath
        self.newPath = newPath


@pytest.mark.parametrize('manager,attribute', [
    (mouseevents.MouseInEventManager, 'newPath'),
    (mouseevents.MouseOutEventManager, 'lastPath'),
], ids=['mousein', 'mouseout'])
class TestTheDeltaIsAPath:
    def _traversed(self, manager, scene):
        _root, onto, off = scene
        instance = manager.__new__(manager)
        return instance._traversalPaths(_Event(lastPath=off, newPath=onto))

    def test_it_gives_one_path(self, manager, attribute, scene):
        assert len(self._traversed(manager, scene)) == 1

    def test_the_delta_is_still_a_node_path(self, manager, attribute, scene):
        found = self._traversed(manager, scene)[0]
        assert isinstance(found, NodePath), type(found)

    def test_it_can_still_give_its_matrix(self, manager, attribute, scene):
        """``transformMatrix`` is what a handler asks the path for."""
        found = self._traversed(manager, scene)[0]
        assert found.transformMatrix().shape == (4, 4)

    def test_the_shared_prefix_is_dropped(self, manager, attribute, scene):
        """Both paths start at the same Transform, so only the leaf differs."""
        _root, onto, off = scene
        found = self._traversed(manager, scene)[0]
        expected = {'newPath': onto, 'lastPath': off}[attribute]
        assert list(found) == [expected[-1]]
