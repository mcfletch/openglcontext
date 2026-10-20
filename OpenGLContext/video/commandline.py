"""The command-line options a program offers to record itself to a video file.

A program with a ``--record`` mode adds the same options as every other one,
and turns what was parsed into the arguments of
:meth:`~OpenGLContext.video.recorder.RecordingMixin.setupRecording`::

    parser = argparse.ArgumentParser()
    add_recording_arguments(parser, seconds=30, fps=30)
    arguments = parser.parse_args()
    request = require_recording(parser, RecordingRequest.from_namespace(arguments))
    ...
    # in the context's OnInit
    if request:
        self.setupRecording(request.path, **request.options())

======================  ==============================================
``--record PATH``       the ``.mp4`` to write; without it nothing is recorded
``--record-codec``      ``h264``, ``hevc``, ``vp9`` or ``av1``
``--record-seconds``    how long the video is
``--record-fps``        frames a second
``--record-delay``      seconds of real time to let the world arrive first
``--record-bitrate``    bits a second; 0 lets the encoder choose
======================  ==============================================

Nothing here touches GL or imports the encoder package until a recording is
requested.
"""
from __future__ import annotations

import argparse
import dataclasses
from typing import Any

from OpenGLContext.video import codecs

__all__ = ['RecordingRequest', 'add_recording_arguments', 'require_recording']


def _codec(text: str) -> str:
    try:
        return codecs.canonical(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _number(kind: type, low: float, inclusive: bool, what: str) -> Any:
    """An argparse type for a ``kind`` above (or, if `inclusive`, from) `low`."""
    def parse(text: str) -> Any:
        try:
            value = kind(text)
        except ValueError:
            raise argparse.ArgumentTypeError('%r is not %s' % (text, what)) from None
        if value < low or (value == low and not inclusive):
            raise argparse.ArgumentTypeError('%r is not %s' % (text, what))
        return value
    return parse


def add_recording_arguments(parser: argparse.ArgumentParser, *, seconds: float = 20.0,
                            fps: int = 60, delay: float = 0.0,
                            codec: str = 'h264') -> None:
    """Add the ``--record`` options to `parser`, with these defaults."""
    parser.add_argument(
        '--record', metavar='PATH',
        help='record to PATH (an .mp4) and exit when the recording is done. The '
             'world advances by exactly one frame of time per frame recorded')
    parser.add_argument(
        '--record-codec', type=_codec, default=codec, metavar='CODEC',
        help='the video codec: %s; the GPU has to encode it (default: %%(default)s)'
             % ', '.join(codecs.CODECS))
    parser.add_argument(
        '--record-seconds', type=_number(float, 0, False, 'a number of seconds above zero'),
        default=float(seconds), metavar='SECONDS',
        help='how long the video is (default: %(default)s)')
    parser.add_argument(
        '--record-fps', type=_number(int, 0, False, 'a frame rate above zero'),
        default=fps, metavar='FPS', help='frames a second (default: %(default)s)')
    parser.add_argument(
        '--record-delay', type=_number(float, 0, True, 'a number of seconds, zero or more'),
        default=float(delay), metavar='SECONDS',
        help='let the world arrive for this long before the recording starts '
             '(default: %(default)s)')
    parser.add_argument(
        '--record-bitrate', type=_number(int, 0, True, 'a number of bits, zero or more'),
        default=0, metavar='BITS',
        help='bits a second; 0 lets the encoder choose from the frame size and rate')


@dataclasses.dataclass(frozen=True)
class RecordingRequest:
    """What the ``--record`` options asked for."""

    path: str
    codec: str = 'h264'
    seconds: float = 20.0
    fps: int = 60
    delay: float = 0.0
    bitrate: int = 0

    @classmethod
    def from_namespace(cls, arguments: argparse.Namespace) -> RecordingRequest | None:
        """The request in parsed `arguments`, or None when no ``--record`` was given."""
        if not arguments.record:
            return None
        return cls(path=arguments.record, codec=arguments.record_codec,
                   seconds=arguments.record_seconds, fps=arguments.record_fps,
                   delay=arguments.record_delay, bitrate=arguments.record_bitrate)

    def options(self) -> dict[str, Any]:
        """The keyword arguments of ``setupRecording`` after the path.

        A bitrate of 0 is left out, which leaves the choice to the encoder.
        """
        found: dict[str, Any] = dict(codec=self.codec, fps=self.fps, seconds=self.seconds,
                                     start_after=self.delay)
        if self.bitrate:
            found['bitrate'] = self.bitrate
        return found


def require_recording(parser: argparse.ArgumentParser,
                      request: RecordingRequest | None) -> RecordingRequest | None:
    """`request`, after ending the program with a usage error if it cannot be met.

    A machine without the encoder package reports that here, before a window is
    opened or a world built, rather than at the first frame. Whether the GPU
    encodes the codec is known only once a GL context is current, so that is
    reported by the first frame: :class:`~OpenGLContext.video.recorder.RecordingUnavailable`.
    """
    if request is None:
        return None
    from OpenGLContext.video.recorder import RecordingUnavailable, load_encoder_api
    try:
        load_encoder_api()
    except RecordingUnavailable as error:
        parser.error(str(error))
    return request
