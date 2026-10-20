"""Recording a context's frames to an MP4 video file, in H.264, HEVC, VP9 or AV1.

A recording is a copy and an encode per frame. The frame the renderer has just
drawn is blitted into a texture the video encoder has been told about, and the
encoder reads that texture in place -- on the GPU, where the renderer left it --
so nothing but the compressed result crosses the bus::

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

import numpy as np
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from OpenGL.GL import (
    GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_DRAW_FRAMEBUFFER,
    GL_DRAW_FRAMEBUFFER_BINDING, GL_LINEAR, GL_NEAREST,
    GL_READ_FRAMEBUFFER, GL_READ_FRAMEBUFFER_BINDING, GL_RGBA, GL_RGBA8,
    GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_UNSIGNED_BYTE, GL_VIEWPORT, glBindFramebuffer, glBindTexture,
    glBlitFramebuffer, glDeleteFramebuffers, glDeleteTextures,
    glFramebufferTexture2D, glGenFramebuffers, glGenTextures, glGetIntegerv,
    glReadBuffer, glTexImage2D, glTexParameteri,
)

from OpenGLContext.video import codecs
from OpenGLContext.video.clock import FixedStepClock

log = logging.getLogger(__name__)

__all__ = ['VideoRecorder', 'RecordingMixin', 'CaptureTarget', 'copy_frame',
           'RecordingUnavailable', 'recording_size', 'RecordingProgress']


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

    def __init__(self, width: int, height: int) -> None:
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
            glDeleteFramebuffers(1, np.array([self.framebuffer], dtype=np.uint32))
            self.framebuffer = 0
        if self.texture:
            glDeleteTextures(1, np.array([self.texture], dtype=np.uint32))
            self.texture = 0


#: The unit, in pixels, that each codec's picture size is a multiple of. 4:2:0
#: video codes pairs of lines. AV1 on the GPU's encoder (VA-API on AMD) codes
#: whole blocks of sixteen and states the real size only in a render-size field
#: that players such as ffmpeg do not apply, so a picture of another size is
#: played with padding along its bottom and right edges: 360 rows are played as
#: 362 and 1044 as 1056, while 352 and 1040 are exact.
SIZE_UNIT = {'h264': 2, 'hevc': 2, 'vp9': 2, 'av1': 16}


def recording_size(width: int, height: int, codec: str = 'h264') -> tuple[int, int]:
    """The size to record a `width` by `height` viewport at: rounded down to the codec's unit.

    Raises :class:`ValueError` for a viewport smaller than one unit.
    """
    unit = SIZE_UNIT[codecs.canonical(codec)]
    size = (width - width % unit, height - height % unit)
    if min(size) <= 0:
        raise ValueError('a %dx%d viewport is too small to record in %s: the picture is a '
                         'multiple of %d pixels each way' % (width, height, codec, unit))
    return size


def copy_frame(framebuffer: int, size: tuple[int, int],
               source: int = 0, buffer: int | None = None) -> None:
    """Copy the frame just drawn into `framebuffer`, turning it the right way up.

    - ``framebuffer`` - where to put it, usually a :class:`CaptureTarget`'s
    - ``size`` - the destination's size; a source of another size is scaled
      into it, so a recording keeps going across a window resize
    - ``source`` - the framebuffer to read, the default one by default
    - ``buffer`` - which of its buffers; by default the one the finished frame
      is in: the back buffer on a window, the front one on a surface nothing
      presents, and a framebuffer object's first colour attachment. Naming a
      buffer the framebuffer does not have is GL_INVALID_OPERATION rather than
      a quiet fallback, so it is asked rather than assumed.

    **The destination's Y coordinates run backwards on purpose.** OpenGL's
    framebuffer starts at the bottom left and a video encoder reads a texture
    from its first row and calls that the top of the picture, so the copy has to
    turn the frame over. Doing it in the blit costs nothing.
    """
    width, height = size
    previous_read = int(glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING))
    previous_draw = int(glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING))
    glBindFramebuffer(GL_READ_FRAMEBUFFER, source)
    if buffer is None:
        # Asked once `source` is the read framebuffer, since that is the one the
        # question is about.
        from OpenGLContext.capture import presented_buffer

        buffer = (presented_buffer(GL_READ_FRAMEBUFFER) if source == 0
                  else GL_COLOR_ATTACHMENT0)
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

    - ``path`` - the ``.mp4`` to write
    - ``codec`` - ``'h264'``, ``'hevc'``, ``'vp9'`` or ``'av1'``, where the
      GPU's encoder has it; ``'h265'`` and ``'avc'`` are taken too
    - ``fps`` - frames per second, as a number or an exact
      ``(numerator, denominator)`` pair
    - ``size`` - the recording's size; by default the viewport at the first
      frame. A recording keeps the size it started at, and a window resized
      later is scaled into it.
    - ``seconds``, ``frames`` - how long to record. Given neither, it records
      until closed.
    - ``start_after`` - seconds of real time to let pass before the first frame
      is kept. A world that streams its content in arrives over the first few
      seconds, and a recording that starts immediately is a recording of it
      arriving.
    - ``fixed_step`` - advance the engine's clock a frame at a time while
      recording
    - ``encoder`` - anything else is passed to the encoder: ``bitrate``,
      ``preset``, ``tuning``, ``gop``, ``bframes``; see the pyopengl-video
      documentation.

    Raises :class:`ValueError` for a codec that is not one of
    :data:`~OpenGLContext.video.codecs.CODECS`.
    """

    def __init__(self, path: str | Path, fps: float | tuple[int, int] = 60,
                 size: tuple[int, int] | None = None,
                 seconds: float | None = None, frames: int | None = None,
                 start_after: float = 0.0, fixed_step: bool = True,
                 codec: str = 'h264', **encoder: Any) -> None:
        self.path = Path(path)
        self.codec = codecs.canonical(codec)
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

    def seconds_for(self, frames: int) -> float:
        """How many seconds of video `frames` frames make at this recording's rate."""
        numerator, denominator = FixedStepClock._as_ratio(self.fps)
        return frames * denominator / numerator

    @property
    def seconds_written(self) -> float:
        """Seconds of video kept so far."""
        return self.seconds_for(self.frames_written)

    @property
    def started(self) -> bool:
        """Whether the encoder is open: the first frame has been kept.

        Until then the recording is waiting out :attr:`start_after`, and the
        world is not yet on the recording's clock.
        """
        return self._encoder is not None

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
            # A size the codec does not code whole loses rows or columns
            # somewhere; losing them here keeps the encoder's own error away
            # from a caller who only asked to record a window.
            self.size = recording_size(width, height, self.codec)
        try:
            self._encoder = pyopengl_video.open_encoder(
                *self.size, codec=self.codec, fps=self.fps, **self.encoder_options)
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
        log.info('recording %sx%s %s to %s', self.size[0], self.size[1], self.codec, self.path)

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


class RecordingProgress:
    """Says how far a recording has got, once an `interval` of real time.

    A recording is paced by frames, so a minute of video takes as long to
    record as its frames take to draw, which is more than a minute for a heavy
    scene. The line says how much video is written and how long the rest is
    expected to take at the rate so far.

    - ``interval`` - seconds of real time between lines
    - ``clock`` - the real-time clock, which a test replaces
    """

    def __init__(self, interval: float = 5.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.interval = interval
        self.clock = clock
        self._began: float | None = None
        self._first = 0
        self._next = 0.0

    def report(self, recording: VideoRecorder) -> str | None:
        """The line to print now, or None when it is not time or nothing is kept yet."""
        if not recording.frames_written:
            return None
        now = self.clock()
        if self._began is None:
            self._began = now
            self._first = recording.frames_written
            self._next = now + self.interval
            return None
        if now < self._next:
            return None
        self._next = now + self.interval
        rate = (recording.frames_written - self._first) / max(now - self._began, 1e-9)
        done = recording.seconds_written
        line = 'recording: %.0f' % done
        if recording.limit is not None:
            line += ' of %.0f s' % recording.seconds_for(recording.limit)
        else:
            line += ' s'
        line += ', %.0f frames a second' % rate
        if recording.limit is not None and rate > 0:
            line += ', about %.0f s to go' % ((recording.limit - recording.frames_written) / rate)
        return line


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
    #: Prints how far the recording has got every few seconds; None prints nothing.
    recordingProgress: RecordingProgress | None = None

    def setupRecording(self, path: str | Path | None, **options: Any) -> None:
        """Arrange to record to `path`; a path of None records nothing."""
        self.recorder = VideoRecorder(path, **options) if path else None
        self.recordingProgress = RecordingProgress() if path else None

    @property
    def recording(self) -> bool:
        """Whether this run is being recorded."""
        return self.recorder is not None

    @property
    def awaiting_recording(self) -> bool:
        """Whether a recording is set up and has yet to keep its first frame.

        True while the recording waits out its ``start_after``. A program with
        something that runs in real time, a game or an animation, holds it
        while this is true, so the video opens on the start of the run.
        """
        return self.recorder is not None and not self.recorder.started

    def wantsMoreFrames(self) -> bool:
        """A recording still running needs frames to record.

        What keeps an offscreen main loop going, which otherwise draws
        ``frameCount`` frames and returns. A recording bounded by ``seconds``
        or ``frames`` closes itself and the loop ends with it; one bounded by
        neither records until something closes it, here as on a window.
        """
        if self.recording:
            return True
        # Passed on rather than answered for: a viewer may be recording and
        # capturing at once, and the frames either still wants are frames the
        # loop must draw. The tail is the context's own, which answers False;
        # a mixin used on its own has no context to ask.
        following = getattr(super(), 'wantsMoreFrames', None)
        return bool(following()) if following is not None else False

    def tickRecording(self) -> bool:
        """Offer the finished frame to the recording; True while it wants more.

        Call from ``presentFrame`` before the swap.
        """
        if self.recorder is None:
            return False
        self.recorder.capture()
        if self.recorder.recording:
            line = (self.recordingProgress.report(self.recorder)
                    if self.recordingProgress is not None else None)
            if line:
                print(line, flush=True)
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
