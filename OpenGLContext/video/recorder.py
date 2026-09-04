"""Recording a context's frames to an H.264 video file.

A recording is a copy and an encode per frame. The frame the renderer has just
drawn is blitted into a texture the video encoder has been told about, and the
encoder reads that texture in place -- on the GPU, where the renderer left it --
so nothing but the compressed result crosses the bus.

    from OpenGLContext.video.recorder import VideoRecorder

    recorder = VideoRecorder('run.mp4', fps=60, seconds=20)
    ...
    def presentFrame(self):
        recorder.capture()          # before the swap: the back buffer is the frame
        return super().presentFrame()
    ...
    recorder.close()

:class:`RecordingMixin` wires that into a context, including stopping when the
recording is done.

Recording needs the ``video`` extra (``pip install OpenGLContext[video]``),
which brings in `pyopengl-video`. Without it, building a recorder is fine and
the first frame reports what is missing.

**Time.** By default a recorder installs a
:class:`~OpenGLContext.video.clock.FixedStepClock` and advances it one frame per
frame recorded, so the world moves by exactly a frame's worth however long the
frame took to draw and the recording is smooth and repeatable. Pass
``fixed_step=False`` to record against the wall clock instead, which is what a
recording of an interactive session -- stalls and all -- wants.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from OpenGL.GL import (
    GL_BACK, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_DRAW_FRAMEBUFFER,
    GL_DRAW_FRAMEBUFFER_BINDING, GL_LINEAR, GL_NEAREST,
    GL_READ_FRAMEBUFFER, GL_READ_FRAMEBUFFER_BINDING, GL_RGBA, GL_RGBA8,
    GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_UNSIGNED_BYTE, GL_VIEWPORT, glBindFramebuffer, glBindTexture,
    glBlitFramebuffer, glDeleteFramebuffers, glDeleteTextures,
    glFramebufferTexture2D, glGenFramebuffers, glGenTextures, glGetIntegerv,
    glReadBuffer, glTexImage2D, glTexParameteri,
)

from OpenGLContext.video.clock import FixedStepClock

log = logging.getLogger(__name__)

__all__ = ['VideoRecorder', 'RecordingMixin', 'CaptureTarget', 'copy_frame',
           'RecordingUnavailable']


class RecordingUnavailable(RuntimeError):
    """Nothing on this machine can record: no encoder, or no encoder package."""


def load_encoder_api() -> Any:
    """The encoder package, or raise :class:`RecordingUnavailable` saying so."""
    try:
        import pyopengl_video
        from pyopengl_video import mp4
    except ImportError as error:
        raise RecordingUnavailable(
            'recording needs the pyopengl-video package: install '
            'OpenGLContext[video]') from error
    return pyopengl_video, mp4


class CaptureTarget:
    """A texture to copy a finished frame into, and the framebuffer that fills it.

    :class:`VideoRecorder` gets its own targets from the encoder, which on some
    platforms is the only side that can allocate one. This is here for code
    doing its own capture -- a screenshot path, a test, a frame handed to
    something other than an encoder -- that just wants somewhere to blit to.
    """

    def __init__(self, width: int, height: int):
        self.size = (int(width), int(height))
        self.texture = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.texture)
        # The encoder wants RGBA with eight bits a channel, at the frame size.
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, None)
        for parameter in (GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER):
            glTexParameteri(GL_TEXTURE_2D, parameter, GL_LINEAR)
        previous = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
        self.framebuffer = int(glGenFramebuffers(1))
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, self.framebuffer)
        glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, self.texture, 0)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previous)

    def close(self) -> None:
        """Give the texture and framebuffer back to the driver."""
        if self.framebuffer:
            glDeleteFramebuffers(1, [self.framebuffer])
            self.framebuffer = 0
        if self.texture:
            glDeleteTextures([self.texture])
            self.texture = 0


def copy_frame(framebuffer: int, size: tuple[int, int],
               source: int = 0, buffer: int = GL_BACK) -> None:
    """Copy the frame just drawn into `framebuffer`, turning it the right way up.

    framebuffer -- where to put it, usually a :class:`CaptureTarget`'s
    size -- the destination's size; a source of another size is scaled into it,
        which is what keeps a recording going across a window resize
    source -- the framebuffer to read, the default one by default
    buffer -- which of its buffers, the back one by default, which is where the
        frame lives until it is swapped away

    **The destination's Y coordinates run backwards on purpose.** OpenGL's
    framebuffer starts at the bottom left and a video encoder reads a texture
    from its first row and calls that the top of the picture, so the copy has to
    turn the frame over. Doing it in the blit costs nothing.
    """
    width, height = size
    previous_read = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
    previous_draw = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
    glBindFramebuffer(GL_READ_FRAMEBUFFER, source)
    glReadBuffer(buffer)
    source_x, source_y, source_width, source_height = (
        int(value) for value in glGetIntegerv(GL_VIEWPORT))
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, framebuffer)
    scaling = (source_width, source_height) != (width, height)
    glBlitFramebuffer(
        source_x, source_y, source_x + source_width, source_y + source_height,
        0, height, width, 0,                     # top and bottom swapped: the flip
        GL_COLOR_BUFFER_BIT, GL_LINEAR if scaling else GL_NEAREST)
    glBindFramebuffer(GL_READ_FRAMEBUFFER, previous_read)
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, previous_draw)


class VideoRecorder:
    """Writes the frames a context draws to a video file.

    path -- the ``.mp4`` to write
    fps -- frames per second, as a number or an exact ``(numerator,
        denominator)`` pair
    size -- the recording's size; by default the viewport at the first frame.
        A recording keeps the size it started at, and a window resized later is
        scaled into it.
    seconds/frames -- how long to record. Given neither, it records until closed.
    start_after -- seconds of real time to let pass before the first frame is
        kept. A world that streams its content in arrives over the first few
        seconds, and a recording that starts immediately is a recording of it
        arriving.
    fixed_step -- advance the engine's clock a frame at a time while recording
    encoder -- anything else is passed to the encoder: ``bitrate``, ``preset``,
        ``tuning``, ``gop``, ``bframes``; see the pyopengl-video documentation.
    """

    def __init__(self, path: str | Path, fps: float | tuple[int, int] = 60,
                 size: tuple[int, int] | None = None,
                 seconds: float | None = None, frames: int | None = None,
                 start_after: float = 0.0, fixed_step: bool = True,
                 **encoder: Any):
        self.path = Path(path)
        self.fps = fps
        self.size = size
        self.encoder_options = encoder
        self.frames_written = 0
        self.start_after = float(start_after)
        self._waiting_since: float | None = None
        self.clock = FixedStepClock(fps) if fixed_step else None
        self.limit = self._frame_limit(seconds, frames)
        self._encoder: Any = None
        self._movie: Any = None
        self._handles: list[Any] = []
        self._closed = False

    def _frame_limit(self, seconds: float | None, frames: int | None) -> int | None:
        """How many frames this recording is, or None for as many as it is given."""
        if frames is not None:
            return int(frames)
        if seconds is None:
            return None
        numerator, denominator = FixedStepClock._as_ratio(self.fps)
        return int(round(seconds * numerator / denominator))

    @property
    def recording(self) -> bool:
        """Whether more frames are still wanted."""
        return not self._closed and (self.limit is None
                                     or self.frames_written < self.limit)

    def capture(self) -> bool:
        """Record the frame in the back buffer. Returns whether it took it.

        Call from ``presentFrame`` **before** the swap: the back buffer holds
        the frame just drawn only until it is swapped away.

        A False answer means this frame was not kept, which happens both while
        the recording is waiting for :attr:`start_after` to pass and once it has
        run its length. :attr:`recording` is what tells those apart, and it is
        what a caller watches to know when to close the file.
        """
        if not self.recording or not self._warmed_up():
            return False
        if self._encoder is None:
            self._start()
        size = self.size
        if size is None:            # pragma: no cover - _start() has settled it
            raise RecordingUnavailable('the recording never settled on a size')
        handle = self._handles[self.frames_written % len(self._handles)]
        # The scope is where a surface shared with another graphics API changes
        # hands; on a backend that shares nothing it does nothing.
        with handle.for_drawing():
            copy_frame(handle.framebuffer, size)
        packets = self._encoder.encode(handle, timestamp=self._timestamp())
        self._movie.write(packets)
        self.frames_written += 1
        if self.clock is not None:
            self.clock.advance()
        return True

    def _warmed_up(self) -> bool:
        """Has the scene been given its :attr:`start_after` seconds to arrive?

        Timed against real time rather than against the engine clock, because
        what it is waiting for -- tiles loading, textures uploading, a renderer
        settling -- happens in real time whatever the clock says.
        """
        if not self.start_after:
            return True
        from time import perf_counter
        if self._waiting_since is None:
            self._waiting_since = perf_counter()
        return perf_counter() - self._waiting_since >= self.start_after

    def _timestamp(self) -> int:
        """When this frame is shown, in the encoder's timescale."""
        numerator, denominator = FixedStepClock._as_ratio(self.fps)
        return int(self.frames_written * self._encoder.timescale
                   * denominator // numerator)

    def _start(self) -> None:
        """Open the encoder and the file, sizing the recording to the viewport."""
        pyopengl_video, mp4 = load_encoder_api()
        if self.size is None:
            _x, _y, width, height = (int(value) for value in glGetIntegerv(GL_VIEWPORT))
            # H.264 codes in pairs of lines, so an odd size has to lose a row or
            # a column somewhere; losing it here keeps the encoder's own error
            # away from a caller who only asked to record a window.
            self.size = (width - width % 2, height - height % 2)
        try:
            self._encoder = pyopengl_video.open_encoder(
                *self.size, fps=self.fps, **self.encoder_options)
        except pyopengl_video.EncoderUnavailable as error:
            raise RecordingUnavailable(str(error)) from error
        # One input per frame the encoder may be holding: it reads a texture for
        # as long as it holds the frame, and the renderer needs a different one
        # to draw into meanwhile. The encoder allocates them because on some
        # platforms its input is a resource only the driver can make.
        self._handles = [self._encoder.new_input()
                         for _ in range(self._encoder.input_slots)]
        self._movie = mp4.MP4Writer(self.path, self._encoder)
        if self.clock is not None:
            self.clock.install()
        log.info('recording %sx%s to %s', self.size[0], self.size[1], self.path)

    def close(self) -> None:
        """Finish the file and give everything back. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        if self.clock is not None:
            self.clock.restore()
        try:
            if self._encoder is not None:
                self._movie.write(self._encoder.flush())
                self._movie.close()
                self._encoder.close()
        finally:
            # Closing the encoder releases the inputs it made, so there is
            # nothing to give back here beyond letting go of the references.
            self._handles = []
        if self.frames_written:
            log.info('recorded %d frames to %s', self.frames_written, self.path)

    def __enter__(self) -> "VideoRecorder":
        return self

    def __exit__(self, *exception: Any) -> None:
        self.close()


class RecordingMixin(object):
    """Gives a context a record-to-video mode.

    Mirrors :class:`~OpenGLContext.viewer.capture.SettleCaptureMixin`: set the
    recording up once, tick it from ``presentFrame``, and the mixin closes the
    file when the recording has run its length.
    """

    #: The recording in progress, or None for an ordinary run.
    recorder: VideoRecorder | None = None
    #: Quit once the recording is done, which is what a headless run of a fixed
    #: length wants.
    quitWhenRecorded: bool = True

    def setupRecording(self, path: str | Path | None, **options: Any) -> None:
        """Arrange to record to `path`; a path of None records nothing."""
        self.recorder = VideoRecorder(path, **options) if path else None

    @property
    def recording(self) -> bool:
        """Whether this run is being recorded."""
        return self.recorder is not None

    def tickRecording(self) -> bool:
        """Offer the finished frame to the recording; True while it wants more.

        Call from ``presentFrame`` before the swap.
        """
        if self.recorder is None:
            return False
        self.recorder.capture()
        if self.recorder.recording:
            return True
        # Finished, rather than merely waiting for the scene to arrive: those
        # both look like a frame that was not kept.
        self.finishRecording()
        return False

    def finishRecording(self) -> None:
        """Close the file, and quit if that is what the run was for."""
        if self.recorder is None:
            return
        recorder, self.recorder = self.recorder, None
        recorder.close()
        print('recorded %d frames to %s' % (recorder.frames_written, recorder.path))
        quit = getattr(self, 'OnQuit', None)
        if self.quitWhenRecorded and quit is not None:
            quit()
