"""Where mixed blocks go, and what happens when there is nowhere for them.

The seam is deliberately thin.  It exists to make **silence a first-class
backend** -- not to abstract over a second audio library nobody is going to
write -- and to keep the mixer testable with no hardware anywhere in sight.

Sound can be unavailable two ways: the ``miniaudio`` package may not be
installed, and a device may fail to open even where it is.  A container with no
ALSA or PulseAudio, a machine with no sound card, a device something else holds
exclusively, and a deliberately minimal install all land here.  **Every one of
them ends in the same place**: :func:`open_device` logs one warning and returns
a :class:`NullDevice`, so there is a single silent path rather than a scattering
of special cases.  A machine with no sound is a normal machine, continuous
integration is one, and audio must never be why an application will not start.

That makes the fallback real code that has to keep working, so it is tested
directly rather than assumed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

#: Frames per second an output device is opened at.
DEFAULT_SAMPLE_RATE = 44100

#: How much audio the device buffers ahead, in milliseconds.  Small enough that
#: a sound fired this frame is heard this frame; large enough that an ordinary
#: scheduling hiccup does not empty the buffer.
DEFAULT_BUFFER_MSEC = 40

#: The name ``miniaudio`` gives its do-nothing output.  Getting it back means
#: the machine has no audio hardware the library can reach, which is the
#: no-device case rather than a device.
NULL_BACKEND = 'null'

_miniaudio: Any = None
_import_attempted = False


class DeviceError(Exception):
    """No output device could be opened."""


def _backend() -> Any:
    """The ``miniaudio`` module, or None where it is not installed.

    Imported on demand rather than at module import, so a test can arrange for
    the absent-package path without having got in before the module loaded.
    """
    global _miniaudio, _import_attempted
    if not _import_attempted:
        _import_attempted = True
        try:
            import miniaudio
        except ImportError as error:
            log.info('audio playback unavailable: %s', error)
        else:
            _miniaudio = miniaudio
    return _miniaudio


def miniaudio_available() -> bool:
    """Whether the optional playback backend is installed."""
    return _backend() is not None


class AudioDevice:
    """An output for mixed blocks.

    Subclasses provide :meth:`start`, :meth:`stop` and :meth:`close`.  The
    contract is small on purpose: a device is handed a *generator* -- the one
    :meth:`OpenGLContext.audio.mixer.Mixer.blocks` returns -- and pulls blocks
    from it on its own thread.  Nothing pushes; nothing waits.
    """

    #: Frames per second the device runs at.  The mixer must match it.
    sample_rate = DEFAULT_SAMPLE_RATE
    #: Output channels.  Everything here is written for stereo.
    channels = 2
    #: Whether this device produces no sound, whatever it is given.
    silent = False

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE,
                 channels: int = 2) -> None:
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self._source: Any = None

    @property
    def running(self) -> bool:
        """Whether a source is attached and being pulled from."""
        return self._source is not None

    def start(self, source: Any) -> None:
        """Begin pulling blocks from ``source``."""
        self._source = source

    def stop(self) -> None:
        """Stop pulling, leaving the device open."""
        self._source = None

    def close(self) -> None:
        """Stop and release the device.  Safe to call more than once."""
        self.stop()


class NullDevice(AudioDevice):
    """An output that goes nowhere.

    It holds the source without ever pulling from it, so a scene with sounds in
    it builds, runs and stays silent at no cost -- no thread, no callback, no
    mixing.  This is what an application gets on a machine with no audio, and it
    is the reason no other code needs a "do we have sound?" branch.
    """

    silent = True


class MiniaudioDevice(AudioDevice):
    """Playback through ``miniaudio``'s ``PlaybackDevice``.

    The device drives the mixer's generator from its own audio thread, which is
    the seam the whole design is built around: the render loop only ever posts
    voice starts, and neither thread waits on the other.

    Raises:
        DeviceError: where the package is absent, the device will not open, or
            the library falls back to its own null output -- which means the
            machine has no audio hardware and is the no-device case.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 2,
                 buffer_msec: int = DEFAULT_BUFFER_MSEC) -> None:
        super().__init__(sample_rate=sample_rate, channels=channels)
        backend = _backend()
        if backend is None:
            raise DeviceError('miniaudio is not installed')
        try:
            self.device = backend.PlaybackDevice(
                output_format=backend.SampleFormat.FLOAT32,
                nchannels=self.channels,
                sample_rate=self.sample_rate,
                buffersize_msec=int(buffer_msec),
            )
        except Exception as error:
            raise DeviceError('cannot open an audio device: %s' % (error,)) from error
        if str(getattr(self.device, 'backend', '')).lower() == NULL_BACKEND:
            self.device.close()
            raise DeviceError('no audio hardware is available')
        self.backend_name = str(self.device.backend)

    def start(self, source: Any) -> None:
        """Prime ``source`` and hand it to the device.

        The generator must already have been advanced to its first yield: the
        device *sends* the frame count in, and a generator that has not started
        cannot be sent anything.
        """
        next(source)
        super().start(source)
        self.device.start(source)

    def stop(self) -> None:
        if self._source is not None:
            self.device.stop()
        super().stop()

    def close(self) -> None:
        super().close()
        device = getattr(self, 'device', None)
        if device is not None:
            self.device = None
            device.close()


def open_device(sample_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 2,
                buffer_msec: int = DEFAULT_BUFFER_MSEC) -> AudioDevice:
    """The best available output, or silence.  Never raises.

    A :class:`NullDevice` at the requested rate is returned where no real device
    can be had, so the mixer above it is built the same way either way and an
    application never asks whether it has sound.
    """
    try:
        return MiniaudioDevice(sample_rate=sample_rate, channels=channels,
                               buffer_msec=buffer_msec)
    except DeviceError as error:
        log.warning('%s; running silently. Install OpenGLContext[audio] for sound.',
                    error)
    except Exception as error:
        # A backend that fails in a way it never documented is still just a
        # machine without sound; it must not be a machine that will not start.
        log.warning('audio backend failed (%s); running silently.', error)
    return NullDevice(sample_rate=sample_rate, channels=channels)


def describe(device: Optional[AudioDevice]) -> str:
    """One line naming the output, for a debug overlay or a start-up log."""
    if device is None:
        return 'audio: none'
    if device.silent:
        return 'audio: silent'
    return 'audio: %s %d Hz x%d' % (
        getattr(device, 'backend_name', 'device'), device.sample_rate, device.channels)
