"""A key that saves the frame to a picture
(:mod:`OpenGLContext.viewer.overlay`).

Driven on a host that is not a viewer and has no GL: what these check is the
*arrangement* -- when a grab happens and when it does not, and that a screenshot
is taken from the frame just drawn rather than the one after it.  The
pixel-pushing itself needs a live context and is covered by the visual suite.

The caption that used to live beside this is now a HUD layer; see
``tests/unit/test_viewer_caption.py``.
"""
from OpenGLContext.viewer.overlay import ScreenshotMixin


class _Snapper(ScreenshotMixin):
    def __init__(self):
        self.handlers = []
        self.redraws = 0
        self.saved = 0

    def addEventHandler(self, kind, name=None, function=None, **named):
        self.handlers.append((kind, name, function))

    def triggerRedraw(self, count=1):
        self.redraws += count

    def saveScreenshot(self):
        self.saved += 1


class TestScreenshots:
    def test_the_key_is_bound(self):
        host = _Snapper()
        host.setupScreenshots()
        assert ('keyboard', '<F2>', host.requestScreenshot) in host.handlers

    def test_a_host_may_decline_to_bind_a_key(self):
        class _NoKey(_Snapper):
            screenshotKey = ''

        host = _NoKey()
        host.setupScreenshots()
        assert host.handlers == []

    def test_asking_does_not_save_immediately(self):
        """The grab waits for a frame, since there is not one to read yet."""
        host = _Snapper()
        host.requestScreenshot()
        assert host.saved == 0
        assert host._screenshotPending is True
        assert host.redraws >= 1

    def test_the_next_frame_is_saved(self):
        host = _Snapper()
        host.requestScreenshot()
        assert host.takePendingScreenshot() is True
        assert host.saved == 1

    def test_only_one_frame_is_saved_per_request(self):
        host = _Snapper()
        host.requestScreenshot()
        host.takePendingScreenshot()
        assert host.takePendingScreenshot() is False
        assert host.saved == 1

    def test_an_unasked_for_frame_is_not_saved(self):
        host = _Snapper()
        assert host.takePendingScreenshot() is False
        assert host.saved == 0

    def test_the_name_is_dated_so_two_grabs_do_not_collide(self):
        from datetime import datetime
        name = datetime.now().strftime(ScreenshotMixin.screenshotName)
        assert name.endswith('.png')
        assert name != ScreenshotMixin.screenshotName, 'the pattern was not expanded'
