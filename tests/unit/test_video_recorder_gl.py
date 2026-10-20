"""Recording what a context draws, in-process against real GL and a real encoder.

The orientation check here needs no decoder: it copies a frame the way the
recorder does and compares the texture against the framebuffer it came from, so
a blit that forgets to flip fails immediately rather than at the far end of an
encoder.
"""

import sys
import numpy as np
import pytest
from OpenGL.GL import (
    GL_BACK, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_FRAMEBUFFER, GL_FRAMEBUFFER_DEFAULT,
    GL_FRONT, GL_FRONT_LEFT, GL_RGB, GL_RGBA, GL_SCISSOR_TEST, GL_TEXTURE_2D, GL_UNSIGNED_BYTE,
    GL_VIEWPORT, glBindFramebuffer, glBindTexture, glClear, glClearColor, glDisable, glEnable,
    glGetTexImage, glReadBuffer, glReadPixels, glScissor, glViewport,
)
from OpenGLContext import capture
from OpenGLContext.capture import presented_buffer
from OpenGLContext.events import systemtime
from OpenGLContext.video import recorder, recorder as recorder_module
from OpenGLContext.video.recorder import CaptureTarget, copy_frame, VideoRecorder

pytest.importorskip('pyopengl_video')

SIZE = (256, 192)
FPS = 30


@pytest.fixture
def gl_context(gl_window):
    return gl_window('recorder', size=SIZE)


@pytest.fixture
def encoder_available(gl_context):  # noqa: ARG001 an encoder is asked for with a GL context current
    encoders = pytest.importorskip('pyopengl_video').encoders
    if not encoders():
        pytest.skip('no hardware video encoder on this machine')


@pytest.fixture(autouse=True)
def restore_the_wall_clock():
    original = systemtime.timeSource()
    yield
    systemtime.setTimeSource(original)


def draw_a_distinctive_frame(index=0):
    """Fill the back buffer with something that differs top from bottom."""
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
    """The finished frame as an array, in OpenGL's bottom-up order."""

    width, height = SIZE
    glBindFramebuffer(GL_FRAMEBUFFER, 0)
    # Asked rather than assumed: an offscreen surface has no back buffer, and
    # naming one is GL_INVALID_OPERATION rather than a quiet fallback.
    glReadBuffer(presented_buffer())
    raw = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)


class TestWhichBufferAFrameIsCopiedFrom:
    """``copy_frame`` reads the default framebuffer, and which of its colour
    buffers holds the frame depends on whether it has two.  A surface nothing
    presents -- an offscreen pbuffer -- has one, and asking it for ``GL_BACK``
    fails the whole recording on its first frame.
    """

    def _asked_for(self, monkeypatch, source, has_back_buffer, **named):
        asked = []
        monkeypatch.setattr(recorder, 'glReadBuffer', asked.append)
        monkeypatch.setattr(recorder, 'glBindFramebuffer', lambda _t, _f: None)
        monkeypatch.setattr(recorder, 'glBlitFramebuffer',
                            lambda *_arguments: None)
        monkeypatch.setattr(
            recorder, 'glGetIntegerv',
            lambda enum: (0, 0, 4, 4) if enum == GL_VIEWPORT else 0)
        monkeypatch.setattr(
            capture, 'glGetFramebufferAttachmentParameteriv',
            lambda *_args: GL_FRAMEBUFFER_DEFAULT if has_back_buffer
            else capture.GL_NONE)
        recorder.copy_frame(1, (4, 4), source=source, **named)
        return asked

    def test_a_frame_comes_from_the_back_buffer_where_there_is_one(self, monkeypatch):
        assert self._asked_for(monkeypatch, 0, True) == [GL_BACK]

    def test_a_frame_comes_from_the_front_buffer_where_there_is_not(self, monkeypatch):
        assert self._asked_for(monkeypatch, 0, False) == [GL_FRONT]

    def test_another_framebuffer_is_read_at_its_colour_attachment(self, monkeypatch):
        """``GL_BACK`` means nothing on a framebuffer object, whatever the
        default framebuffer happens to have."""

        assert self._asked_for(monkeypatch, 7, False) == [GL_COLOR_ATTACHMENT0]

    def test_a_caller_naming_a_buffer_is_obeyed(self, monkeypatch):
        assert self._asked_for(
            monkeypatch, 0, True, buffer=GL_FRONT_LEFT) == [GL_FRONT_LEFT]


def read_texture(texture):
    """A GL_RGBA8 texture as an array, first row first."""
    width, height = SIZE
    glBindTexture(GL_TEXTURE_2D, texture)
    raw = glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)


@pytest.mark.usefixtures('gl_context')
def test_copy_frame_turns_the_picture_the_right_way_up():
    """The encoder reads a texture from its first row and calls that the top."""

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


@pytest.mark.usefixtures('encoder_available')
def test_a_recording_writes_a_video_file(tmp_path):
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


@pytest.mark.usefixtures('encoder_available')
def test_a_recording_of_a_set_length_stops_itself(tmp_path):
    recorder = VideoRecorder(tmp_path / 'short.mp4', fps=FPS, size=SIZE, seconds=0.2)
    try:
        taken = [recorder.capture() for _ in range(10)]
    finally:
        recorder.close()
    assert taken.count(True) == 6                # 0.2s at 30fps, then it stops
    assert taken[6:] == [False] * 4
    assert recorder.frames_written == 6


@pytest.mark.usefixtures('encoder_available')
def test_a_recording_advances_the_world_one_frame_at_a_time(tmp_path):
    """The scene must move by exactly a frame per frame recorded."""

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


@pytest.mark.usefixtures('encoder_available')
def test_a_wall_clock_recording_leaves_the_engine_clock_alone(tmp_path):
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

    # an entry of None is what makes `import pyopengl_video` fail
    monkeypatch.setitem(sys.modules, 'pyopengl_video', None)
    with pytest.raises(recorder_module.RecordingUnavailable,
                       match=r'OpenGLContext\[video\]'):
        recorder_module.load_encoder_api()


@pytest.mark.usefixtures('encoder_available')
def test_a_recording_can_wait_for_the_scene_to_arrive(tmp_path):
    """A world that streams in needs a moment before it is worth recording."""

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


@pytest.mark.usefixtures('encoder_available')
def test_waiting_for_the_scene_is_not_the_recording_finishing(tmp_path):
    """Both look like a frame that was not kept; only one means close the file."""

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


def encoded_codecs():
    """The codecs the hardware here encodes; asked with a GL context current."""
    return {codec for backend in pytest.importorskip('pyopengl_video').encoders()
            for codec in backend.codecs}


@pytest.mark.parametrize('codec', ['h264', 'hevc', 'vp9', 'av1'])
@pytest.mark.usefixtures('encoder_available')
def test_a_recording_is_written_in_the_codec_asked_for(tmp_path, codec):
    if codec not in encoded_codecs():
        pytest.skip('this GPU does not encode %s' % codec)
    from pyopengl_video import codecs as encoder_codecs
    from pyopengl_video.mp4 import MP4Reader

    path = tmp_path / ('%s.mp4' % codec)
    with VideoRecorder(path, fps=FPS, size=SIZE, codec=codec, frames=8) as recording:
        for index in range(8):
            draw_a_distinctive_frame(index)
            recording.capture()

    with MP4Reader(path) as movie:
        assert encoder_codecs.canonical(movie.video.codec) == codec
        assert movie.video.size == SIZE


def test_a_recording_in_an_unknown_codec_is_refused_before_anything_opens(tmp_path):
    with pytest.raises(ValueError, match='theora'):
        VideoRecorder(tmp_path / 'x.mp4', codec='theora')


def test_a_codec_is_taken_by_any_of_its_spellings(tmp_path):
    assert VideoRecorder(tmp_path / 'x.mp4', codec='H265').codec == 'hevc'


def test_a_recording_that_has_not_kept_a_frame_has_not_started(tmp_path):
    recording = VideoRecorder(tmp_path / 'x.mp4')
    assert recording.started is False


@pytest.mark.usefixtures('encoder_available')
def test_a_recording_has_started_once_it_has_its_first_frame(tmp_path):
    with VideoRecorder(tmp_path / 'x.mp4', fps=FPS, size=SIZE) as recording:
        draw_a_distinctive_frame()
        recording.capture()
        assert recording.started is True


def test_a_context_is_waiting_for_its_recording_until_the_first_frame_is_kept(tmp_path):
    class Window(recorder.RecordingMixin):
        pass

    window = Window()
    assert window.awaiting_recording is False
    window.setupRecording(tmp_path / 'x.mp4', start_after=5)
    assert window.awaiting_recording is True


@pytest.mark.parametrize('codec, width, height, expected', [
    ('h264', 1856, 1044, (1856, 1044)),
    ('hevc', 1857, 1045, (1856, 1044)),
    ('vp9', 1001, 777, (1000, 776)),
    ('av1', 1856, 1044, (1856, 1040)),
    ('av1', 1279, 719, (1272, 712)),
])
def test_a_recording_is_sized_to_what_its_codec_codes_whole(codec, width, height, expected):
    """4:2:0 codes pairs of lines; AV1 on the GPU codes blocks of eight, and players show the padding."""
    assert recorder.recording_size(width, height, codec) == expected


def test_a_viewport_smaller_than_the_codec_unit_is_refused():
    with pytest.raises(ValueError, match='too small'):
        recorder.recording_size(7, 300, 'av1')


class FakeClock:
    """A clock the test moves, for a recording's progress."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_progress_is_silent_until_a_frame_has_been_kept(tmp_path):
    progress = recorder.RecordingProgress(interval=5, clock=FakeClock())
    assert progress.report(VideoRecorder(tmp_path / 'x.mp4', seconds=120)) is None


def test_progress_says_how_far_the_recording_is_and_how_long_is_left(tmp_path):
    clock = FakeClock()
    progress = recorder.RecordingProgress(interval=5, clock=clock)
    recording = VideoRecorder(tmp_path / 'x.mp4', fps=60, seconds=120)
    recording.frames_written = 1
    assert progress.report(recording) is None              # the first kept frame starts the timing
    clock.now += 10
    recording.frames_written = 301                         # 300 frames in 10 s: 30 a second
    assert progress.report(recording) == (
        'recording: 5 of 120 s, 30 frames a second, about 230 s to go')


def test_progress_is_reported_once_an_interval_not_every_frame(tmp_path):
    clock = FakeClock()
    progress = recorder.RecordingProgress(interval=5, clock=clock)
    recording = VideoRecorder(tmp_path / 'x.mp4', fps=60, seconds=120)
    recording.frames_written = 1
    progress.report(recording)
    clock.now += 5
    recording.frames_written = 151
    assert progress.report(recording) is not None
    clock.now += 1
    recording.frames_written = 181
    assert progress.report(recording) is None
    clock.now += 4
    recording.frames_written = 301
    assert progress.report(recording) is not None


def test_a_recording_with_no_length_reports_what_it_has(tmp_path):
    clock = FakeClock()
    progress = recorder.RecordingProgress(interval=5, clock=clock)
    recording = VideoRecorder(tmp_path / 'x.mp4', fps=30)
    recording.frames_written = 1
    progress.report(recording)
    clock.now += 10
    recording.frames_written = 301
    assert progress.report(recording) == 'recording: 10 s, 30 frames a second'
