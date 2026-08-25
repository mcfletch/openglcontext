"""The screenshot key, and the moment the picture is actually taken.

A key handler runs *between* frames.  By the time it does, the back buffer no
longer holds the frame the player was looking at -- the driver has recycled it
-- so reading pixels from inside the handler gets whatever happens to be there.

So the key only asks.  The flag it sets is read by the render pass at the one
moment the frame is finished and still in the back buffer: immediately before
the swap.  These tests pin both halves, and the order between them.
"""

import pytest

from OpenGLContext.context import Context
from OpenGLContext.screenshot import ScreenshotMixin


class Asker(ScreenshotMixin):
    """A context reduced to what the mixin needs of one."""

    def __init__(self):
        self.bound = []
        self.redraws = 0
        self.saved = 0

    def addEventHandler(self, kind, **named):
        self.bound.append((kind, named))

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def OnSaveImage(self, event=None):
        self.saved += 1
        return (640, 480)


@pytest.fixture
def asker():
    host = Asker()
    host.setupScreenshotKey()
    return host


class TestAskingForOne:
    def test_the_key_is_bound(self, asker):
        assert asker.bound, 'nothing takes a screenshot'

    def test_it_is_f2(self, asker):
        assert asker.bound[0][1]['name'] == '<F2>'

    def test_it_is_a_key_down_and_not_a_character(self, asker):
        """A function key produces no character, so a keypress never arrives."""
        kind, named = asker.bound[0]
        assert kind == 'keyboard'
        assert named['state'] == 1

    def test_a_context_may_decline_the_key(self):
        """An application that wants F2 for itself sets screenshotKey to ''."""
        host = Asker()
        host.screenshotKey = ''
        host.setupScreenshotKey()
        assert not host.bound

    def test_pressing_it_saves_nothing_yet(self, asker):
        asker.requestScreenshot()
        assert asker.saved == 0

    def test_pressing_it_asks_for_a_frame(self, asker):
        """Without a redraw an idle scene would never reach the swap."""
        asker.requestScreenshot()
        assert asker.redraws == 1


class TestTakingIt:
    def test_nothing_is_saved_when_none_was_asked_for(self, asker):
        assert asker.takePendingScreenshot() is False
        assert asker.saved == 0

    def test_the_frame_is_saved_once_it_has_been_asked_for(self, asker):
        asker.requestScreenshot()
        assert asker.takePendingScreenshot() is True
        assert asker.saved == 1

    def test_one_press_is_one_picture(self, asker):
        """The flag clears as it is read, so the next frame is not saved too."""
        asker.requestScreenshot()
        asker.takePendingScreenshot()
        assert asker.takePendingScreenshot() is False
        assert asker.saved == 1


class Presenter:
    """A context that records the order of what the pass does to it."""

    def __init__(self):
        self.calls = []

    def takePendingScreenshot(self):
        self.calls.append('screenshot')
        return True

    def SwapBuffers(self):
        self.calls.append('swap')


class TestWhenThePassTakesIt:
    """The read must happen before the swap, or it reads the previous frame."""

    @pytest.fixture
    def pass_(self):
        from OpenGLContext.passes import _flat
        return _flat.FlatPass.__new__(_flat.FlatPass)

    def test_the_pass_presents_the_frame(self, pass_):
        context = Presenter()
        pass_.presentFrame(context)
        assert context.calls == ['screenshot', 'swap']

    def test_the_compatibility_pass_presents_it_the_same_way(self):
        """Both flat passes end a frame; neither may skip the screenshot."""
        from OpenGLContext.passes import _flat, flatcompat
        assert flatcompat.FlatPass.presentFrame is _flat.FlatPass.presentFrame


class TestEveryContextHasIt:
    def test_the_base_context_carries_the_mixin(self):
        assert issubclass(Context, ScreenshotMixin)

    def test_a_context_that_never_asked_takes_no_screenshot(self):
        """The flag is a class attribute, so an untouched context reads False."""
        assert Context._screenshotPending is False
