"""Rendering one settled frame to a file, then quitting
(:mod:`OpenGLContext.viewer.capture`).

A capture has to be *reproducible*: taken from the frame just drawn, after the
renderer has had time to converge, and followed by the machine-readable line the
regression harness records per model.  These drive that arrangement on a host
with no GL.
"""
import pytest

from OpenGLContext.viewer.capture import SettleCaptureMixin


class _Grab:
    """Stands in for a SettleCapture: says yes on the nth tick."""

    def __init__(self, ready_on=1):
        self.ticks = 0
        self.ready_on = ready_on

    def tick(self):
        self.ticks += 1
        return self.ticks >= self.ready_on


class _Host(SettleCaptureMixin):
    def __init__(self, fps=None):
        self.quits = 0
        self.frameCounter = fps

    def OnQuit(self):
        self.quits += 1


class TestArrangingACapture:
    def test_a_path_arranges_a_settled_grab(self, tmp_path):
        host = _Host()
        host.setupCapture(str(tmp_path / 'shot.png'), delay=0.25, frames=4)
        assert host.capturing is True
        assert host.settleCapture is not None
        assert host.settleCapture.delay == pytest.approx(0.25)
        assert host.settleCapture.min_frames == 4

    def test_no_path_leaves_the_run_interactive(self):
        host = _Host()
        host.setupCapture(None)
        assert host.capturing is False
        assert host.settleCapture is None

    def test_an_empty_path_is_not_a_capture(self):
        """An unset option must not produce a file called ''."""
        host = _Host()
        host.setupCapture('')
        assert host.capturing is False

    def test_setting_up_twice_replaces_the_first(self, tmp_path):
        host = _Host()
        host.setupCapture(str(tmp_path / 'a.png'))
        first = host.settleCapture
        host.setupCapture(str(tmp_path / 'b.png'))
        assert host.settleCapture is not first


class TestTicking:
    def test_an_interactive_run_never_grabs(self):
        host = _Host()
        host.setupCapture(None)
        assert host.tickCapture() is False

    def test_the_grab_waits_for_the_scene_to_settle(self):
        host = _Host()
        host.settleCapture = _Grab(ready_on=3)
        assert host.tickCapture() is False
        assert host.tickCapture() is False
        assert host.tickCapture() is True

    def test_every_frame_is_offered_to_the_grab(self):
        host = _Host()
        grab = _Grab(ready_on=99)
        host.settleCapture = grab
        for _ in range(5):
            host.tickCapture()
        assert grab.ticks == 5


class TestFinishing:
    def test_it_reports_what_the_capture_cost_and_quits(self, capsys):
        """The harness records the numbers per model, so a load that doubles or a
        frame rate that halves is visible even when the picture is unchanged."""
        host = _Host(fps=type('C', (), {'recentFps': lambda self: 61.5})())
        host.loadSeconds = 1.25
        host.finishCapture()
        out = capsys.readouterr().out
        assert 'CAPTURE_STATS' in out
        assert 'load_seconds=1.25' in out
        assert 'fps=61.5' in out
        assert host.quits == 1

    def test_a_context_with_no_frame_counter_still_reports(self):
        host = _Host(fps=None)
        host.finishCapture()
        assert host.quits == 1

    def test_a_frame_counter_that_raises_does_not_lose_the_capture(self, capsys):
        """The picture is the deliverable; the statistics are not worth failing for."""
        class _Broken:
            def recentFps(self):
                raise RuntimeError('no frames yet')

        host = _Host(fps=_Broken())
        host.finishCapture()
        assert 'CAPTURE_STATS' in capsys.readouterr().out
        assert host.quits == 1

    def test_an_unmeasured_load_reports_empty_rather_than_guessing(self, capsys):
        host = _Host()
        host.finishCapture()
        assert 'load_seconds=' in capsys.readouterr().out
