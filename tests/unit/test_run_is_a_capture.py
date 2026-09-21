"""Whether a run's frames are read back, and what that settles.

``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` asks for a bounded run: a fixed number of
frames, the last of which is read back.  The adaptive renderer paths ask the
context whether this is such a run, and pin themselves where it is, so the
frame that is read back follows from the scene rather than from how quickly the
machine reached that frame.  :mod:`OpenGLContext.video.clock` asks the same
question of the same variable for the same reason.

The viewer's own ``capturing`` is the narrower question -- a settle capture is
driving the run, so the scene is loaded before the loop and nothing is
simulated -- and the two are kept apart here.
"""
import pytest

from OpenGLContext import context as context_module
from OpenGLContext.passes import ibl


def bounded_context():
    """A context that has read the environment, and has no window.

    ``setupAutoExit`` reads the environment and sets instance attributes; it
    touches no GL and opens nothing, so a context that was never initialised
    answers for it.
    """
    context = context_module.Context.__new__(context_module.Context)
    context.setupAutoExit()
    return context


class TestWhetherTheFramesAreRead:
    def test_an_interactive_run_is_not_read(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR', raising=False)
        assert bounded_context().renderingForCapture is False

    def test_a_bounded_run_is(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '5')
        assert bounded_context().renderingForCapture is True

    def test_a_frame_count_that_is_not_a_number_leaves_it_interactive(
            self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', 'soon')
        assert bounded_context().renderingForCapture is False

    def test_the_final_frame_is_still_part_of_the_capture(self, monkeypatch):
        """The frame that is saved is drawn with the auto-exit branch off.

        ``_autoExitDraw`` clears the frame count so its forced redraw renders
        instead of recursing, and that redraw is the frame the picture is of.
        A run that stopped counting itself there would pin nothing on the one
        frame anybody sees.
        """
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '5')
        context = bounded_context()
        context._autoExitFrames = None
        assert context.renderingForCapture is True


class TestWhatACapturePins:
    @pytest.mark.parametrize('requested', ['', 'auto'])
    def test_a_capture_pins_the_ibl_mode(self, monkeypatch, requested):
        """The question :mod:`OpenGLContext.passes.flateffects` asks.

        Adaptive IBL climbs back to ``full`` over tens of frames, so a capture
        left adaptive shows whichever mode the climb had reached.
        """
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '5')
        monkeypatch.delenv('OPENGLCONTEXT_IBL', raising=False)
        pinned = bounded_context().renderingForCapture
        assert ibl.ibl_is_adaptive(requested, capturing=pinned) is False

    def test_an_interactive_run_still_adapts(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_IBL', raising=False)
        pinned = bounded_context().renderingForCapture
        assert ibl.ibl_is_adaptive('auto', capturing=pinned) is True


class TestTheViewerAsksBothQuestions:
    """A settle capture pins the renderer; a bounded run does not drive the viewer."""

    @staticmethod
    def viewer():
        from OpenGLContext.viewer import capture as viewer_capture

        class Viewer(viewer_capture.SettleCaptureMixin,
                     context_module.Context):
            pass

        return Viewer.__new__(Viewer)

    def test_a_settle_capture_pins_the_renderer(self, monkeypatch, tmp_path):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        viewer = self.viewer()
        viewer.setupCapture(str(tmp_path / 'shot.png'))
        assert viewer.capturing is True
        assert viewer.renderingForCapture is True

    def test_an_interactive_viewer_is_neither(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', raising=False)
        viewer = self.viewer()
        viewer.setupCapture(None)
        assert viewer.capturing is False
        assert viewer.renderingForCapture is False

    def test_a_bounded_viewer_run_is_not_a_settle_capture(self, monkeypatch):
        """The viewer loads its scene up front and simulates nothing for a
        settle capture.  A bounded run is not that -- it is an ordinary session
        that stops after so many frames -- so only the renderer's question is
        answered yes.
        """
        monkeypatch.setenv('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '5')
        viewer = self.viewer()
        viewer.setupAutoExit()
        assert viewer.renderingForCapture is True
        assert viewer.capturing is False
