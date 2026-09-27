"""Mouse-look where the toolkit has no relative-motion mode.

GLUT, Tk and wx keep a grabbed pointer in the middle of the window by warping
it back after every movement.  What is shared is the arithmetic of it: where
the warp went, which movement is its echo, and what the context is told.
"""

from OpenGLContext.windowsystem.base import WarpedPointer

VIEWPORT = (0, 0, 400, 300)


class _Context:
    def __init__(self):
        self.told = []

    def forgetPointerOrigin(self):
        self.told.append('forget')

    def recordPointerMotion(self, x, y):
        self.told.append(('moved', x, y))

    def getViewPort(self):
        return VIEWPORT[2:]


class _Toolkit(WarpedPointer):
    """A window 400 by 300, recording where the pointer was warped to."""

    def __init__(self, middle=(200, 150)):
        self.context = _Context()
        self.middle = middle
        self.warps = []

    def pointerMiddle(self):
        return self.middle

    def warpPointer(self, x, y):
        self.warps.append((x, y))


class TestGrabbing:
    def test_grabbing_warps_the_pointer_to_the_middle(self):
        toolkit = _Toolkit()
        toolkit.grabPointer(True)
        assert toolkit.pointerGrabbed
        assert toolkit.warps == [(200, 150)]

    def test_either_way_the_pointer_starts_from_nowhere(self):
        """Where the pointer is means something different on each side of a
        grab, so the next report is a position rather than one flick."""
        for capture in (True, False):
            toolkit = _Toolkit()
            toolkit.grabPointer(capture)
            assert toolkit.context.told == ['forget']

    def test_letting_go_warps_nothing(self):
        toolkit = _Toolkit()
        toolkit.grabPointer(True)
        toolkit.grabPointer(False)
        assert toolkit.warps == [(200, 150)]
        assert toolkit.pointerWarpedTo is None

    def test_a_window_that_has_gone_is_not_warped_into(self):
        toolkit = _Toolkit(middle=None)
        toolkit.grabPointer(True)
        assert toolkit.warps == []


class TestMovement:
    def _grabbed(self):
        toolkit = _Toolkit()
        toolkit.grabPointer(True)
        toolkit.context.told.clear()
        return toolkit

    def test_the_warps_echo_is_not_the_users_movement(self):
        toolkit = self._grabbed()
        assert not toolkit.pointerMoved(200, 150)
        assert toolkit.context.told == ['forget', ('moved', 200, 150)]

    def test_a_real_movement_is_the_users_and_warps_again(self):
        toolkit = self._grabbed()
        toolkit.pointerMoved(200, 150)
        assert toolkit.pointerMoved(210, 140)
        assert toolkit.warps == [(200, 150), (200, 150)]

    def test_the_movement_is_told_counting_up_from_the_bottom(self):
        toolkit = _Toolkit()
        toolkit.pointerMoved(10, 20)
        assert toolkit.context.told == [('moved', 10, 280)]

    def test_an_ungrabbed_pointer_is_never_warped(self):
        toolkit = _Toolkit()
        assert toolkit.pointerMoved(200, 150)
        assert toolkit.warps == []

    def test_the_echo_is_recognised_once(self):
        toolkit = self._grabbed()
        assert not toolkit.pointerMoved(200, 150)
        toolkit.pointerGrabbed = False
        assert toolkit.pointerMoved(200, 150)
