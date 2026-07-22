"""The displayed frame rate should reflect current speed, not a lifetime average.

A synchronous model load or first-frame shader compile lands in one timed frame.
The cumulative average (count/totalTime) bakes that spike in forever; the
windowed median (recentFps) shrugs it off.
"""
from OpenGLContext.framecounter import FrameCounter


def _counter():
    return FrameCounter()


def test_recent_fps_reflects_steady_state():
    fc = _counter()
    for _ in range(120):
        fc.addFrame(1 / 60.0)      # steady 60 fps
    assert abs(fc.recentFps() - 60.0) < 0.5


def test_recent_fps_ignores_a_load_spike():
    fc = _counter()
    for _ in range(60):
        fc.addFrame(1 / 60.0)
    fc.addFrame(2.0)               # a 2-second model load lands in one frame
    for _ in range(60):
        fc.addFrame(1 / 60.0)

    # Windowed median still reads ~60 fps...
    assert abs(fc.recentFps() - 60.0) < 1.0
    # ...while the cumulative average is dragged far below the real rate.
    cumulative = fc.summary()[1]
    assert cumulative < 40.0


def test_window_is_bounded():
    fc = _counter()
    for _ in range(10_000):
        fc.addFrame(1 / 120.0)
    assert len(fc._recent) <= fc._RECENT_WINDOW


def test_recent_fps_before_any_frame_is_zero():
    assert _counter().recentFps() == 0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
