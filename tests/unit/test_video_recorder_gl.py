"""Recording what a context draws, in-process against real GL and a real encoder.

The orientation check here needs no decoder: it copies a frame the way the
recorder does and compares the texture against the framebuffer it came from, so
a blit that forgets to flip fails immediately rather than at the far end of an
encoder.
"""

import numpy as np
import pytest

pytest.importorskip('pyopengl_video')

SIZE = (256, 192)
FPS = 30


@pytest.fixture
def gl_context(gl_window):
    return gl_window('recorder', size=SIZE)


@pytest.fixture
def encoder_available(gl_context):
    from pyopengl_video import encoders
    if not encoders():
        pytest.skip('no hardware video encoder on this machine')


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    from OpenGLContext.events import systemtime
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def draw_a_distinctive_frame(index=0):
    """Fill the back buffer with something that differs top from bottom."""
    from OpenGL.GL import (
        GL_COLOR_BUFFER_BIT, GL_SCISSOR_TEST, glClear, glClearColor, glDisable,
        glEnable, glScissor, glViewport,
    )
    width, height = SIZE
    glViewport(0, 0, width, height)
    glClearColor(0.0, 0.0, 0.8, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glEnable(GL_SCISSOR_TEST)
    # GL's y=0 is the bottom, so this bright band is the *lower* quarter
    glScissor(0, 0, width, height // 4)
    glClearColor(1.0, 0.5 + 0.5 * (index % 2), 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT)
    glDisable(GL_SCISSOR_TEST)
    glScissor(0, 0, width, height)
    glDisable(GL_SCISSOR_TEST)


def read_back_buffer():
    """The back buffer as an array, in OpenGL's bottom-up order."""
    from OpenGL.GL import (
        GL_BACK, GL_FRAMEBUFFER, GL_RGB, GL_UNSIGNED_BYTE, glBindFramebuffer,
        glReadBuffer, glReadPixels,
    )
    width, height = SIZE
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    glReadBuffer(GL_BACK)
    raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)


def read_texture(texture):
    """A GL_RGBA8 texture as an array, first row first."""
    from OpenGL.GL import (
        GL_RGBA, GL_TEXTURE_2D, GL_UNSIGNED_BYTE, glBindTexture, glGetTexImage,
    )
    width, height = SIZE
    glBindTexture(GL_TEXTURE_2D, texture)
    raw = glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)


def test_copy_frame_turns_the_picture_the_right_way_up(gl_context):
    """The encoder reads a texture from its first row and calls that the top."""
    from OpenGLContext.video.recorder import CaptureTarget, copy_frame

    draw_a_distinctive_frame()
    target = CaptureTarget(*SIZE)
    try:
        copy_frame(target.framebuffer, SIZE)
        captured = read_texture(target.texture)[..., :3]
    finally:
        target.close()
    # what OpenGL drew at the bottom must be the last row of the texture
    assert np.array_equal(captured, np.flipud(read_back_buffer()))
    assert captured[0, 0, 2] > 180 and captured[0, 0, 0] < 20       # top: blue
    assert captured[-1, 0, 0] > 200 and captured[-1, 0, 2] < 20     # bottom: orange


def test_a_recording_writes_a_video_file(tmp_path, encoder_available):
    from OpenGLContext.video.recorder import VideoRecorder

    path = tmp_path / 'clip.mp4'
    recorder = VideoRecorder(path, fps=FPS, size=SIZE)
    try:
        for index in range(12):
            draw_a_distinctive_frame(index)
            assert recorder.capture() is True
    finally:
        recorder.close()

    assert recorder.frames_written == 12
    written = path.read_bytes()
    assert written[4:8] == b'ftyp'
    assert b'mdat' in written and b'moov' in written


def test_a_recording_of_a_set_length_stops_itself(tmp_path, encoder_available):
    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder(tmp_path / 'short.mp4', fps=FPS, size=SIZE, seconds=0.2)
    try:
        taken = [recorder.capture() for _ in range(10)]
    finally:
        recorder.close()
    assert taken.count(True) == 6                # 0.2s at 30fps, then it stops
    assert taken[6:] == [False] * 4
    assert recorder.frames_written == 6


def test_a_recording_advances_the_world_one_frame_at_a_time(tmp_path, encoder_available):
    """The scene must move by exactly a frame per frame recorded."""
    from OpenGLContext.events import systemtime
    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder(tmp_path / 'clock.mp4', fps=FPS, size=SIZE)
    try:
        draw_a_distinctive_frame()
        recorder.capture()                        # this is what installs the clock
        started = systemtime.systemTime()
        for _ in range(8):
            draw_a_distinctive_frame()
            recorder.capture()
        assert systemtime.systemTime() - started == pytest.approx(8 / FPS, abs=1e-5)
    finally:
        recorder.close()
    # and the clock it borrowed is given back
    assert systemtime.systemTime() > 1e9


def test_a_wall_clock_recording_leaves_the_engine_clock_alone(tmp_path, encoder_available):
    from OpenGLContext.events import systemtime
    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder(tmp_path / 'wall.mp4', fps=FPS, size=SIZE,
                             fixed_step=False)
    try:
        draw_a_distinctive_frame()
        recorder.capture()
        assert systemtime.timeSource() is systemtime.wallClock
    finally:
        recorder.close()


def test_recording_without_the_encoder_package_says_what_to_install(monkeypatch):
    """A stack with no encoder bindings must name the extra that supplies them."""
    import sys

    from OpenGLContext.video import recorder as recorder_module

    # an entry of None is what makes `import pyopengl_video` fail
    monkeypatch.setitem(sys.modules, 'pyopengl_video', None)
    with pytest.raises(recorder_module.RecordingUnavailable,
                       match=r'OpenGLContext\[video\]'):
        recorder_module.load_encoder_api()


def test_a_recording_can_wait_for_the_scene_to_arrive(tmp_path, encoder_available):
    """A world that streams in needs a moment before it is worth recording."""
    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder(tmp_path / 'waited.mp4', fps=FPS, size=SIZE,
                             start_after=10.0)
    try:
        draw_a_distinctive_frame()
        assert recorder.capture() is False        # still waiting
        assert recorder.frames_written == 0
        recorder.start_after = 0.0                # as if the wait had passed
        assert recorder.capture() is True
    finally:
        recorder.close()
    assert recorder.frames_written == 1


def test_waiting_for_the_scene_is_not_the_recording_finishing(tmp_path,
                                                              encoder_available):
    """Both look like a frame that was not kept; only one means close the file."""
    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder(tmp_path / 'waiting.mp4', fps=FPS, size=SIZE,
                             frames=2, start_after=10.0)
    try:
        assert recorder.capture() is False
        assert recorder.recording is True         # still waiting, not done
        recorder.start_after = 0.0
        draw_a_distinctive_frame()
        recorder.capture()
        draw_a_distinctive_frame()
        recorder.capture()
        assert recorder.capture() is False
        assert recorder.recording is False        # now it is done
    finally:
        recorder.close()
