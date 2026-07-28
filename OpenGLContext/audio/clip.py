"""Decoded audio, and the one seam an encoded file passes through.

A :class:`Clip` is the only shape of audio the mixer knows: **one channel of
float32 samples at one rate**.  Everything is normalised to that on the way in,
because the alternative is a mixer that branches on sample format, channel count
and rate in its inner loop -- on the audio thread, sixty times a second.  Mono in
particular is not a simplification but a requirement: a stereo source has already
decided where it sits in the stereo field, and a sound that has decided cannot
then be panned to where it actually is in the world.

Decoding happens through ``miniaudio``, which is optional.  It is one MIT-licensed
package covering ``.wav``, ``.mp3``, ``.ogg`` (Vorbis) and ``.flac``, and it
resamples and re-channels while decoding, so the normalising above costs nothing
extra.  Where it is absent, :func:`decode_file` raises :class:`DecodeError` and
:class:`ClipCache` turns that into a warning and a silence -- a machine with no
audio backend is a normal machine.

Decoding never happens on the audio thread.  :class:`ClipCache` is what makes
that practical: a sound fired sixty times a second is decoded once.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional, Set

import numpy as np

log = logging.getLogger(__name__)

#: What the engine mixes at, in frames per second.  44.1 kHz is what most
#: content is authored at, so resampling on load is usually a no-op.
DEFAULT_SAMPLE_RATE = 44100

#: The backend module, imported once, on demand.  Import-time would freeze the
#: answer before a test could arrange for it to fail.
_miniaudio: Any = None
_import_attempted = False


class DecodeError(Exception):
    """A file could not be turned into samples: absent, unreadable, or unknown."""


def _backend() -> Any:
    """The ``miniaudio`` module, or None where it is not installed."""
    global _miniaudio, _import_attempted
    if not _import_attempted:
        _import_attempted = True
        try:
            import miniaudio
        except ImportError as error:
            log.info('audio decoding unavailable: %s', error)
        else:
            _miniaudio = miniaudio
    return _miniaudio


def decoder_available() -> bool:
    """Whether encoded files can be decoded at all in this installation."""
    return _backend() is not None


class Clip:
    """Mono float32 samples and the rate they were taken at.

    Immutable by convention: the mixer reads a clip from the audio thread while
    the application may still be holding it, so nothing rewrites one in place.
    """

    __slots__ = ('samples', 'sample_rate', 'name')

    def __init__(self, samples: Any, sample_rate: int = DEFAULT_SAMPLE_RATE,
                 name: str = '') -> None:
        if sample_rate <= 0:
            raise ValueError('sample_rate must be positive, not %r' % (sample_rate,))
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim > 1:
            # Interleaved (frames, channels): average, so a centre-panned stereo
            # file keeps its level rather than doubling it.
            data = data.mean(axis=-1, dtype=np.float32)
        self.samples = np.ascontiguousarray(data.reshape(-1), dtype=np.float32)
        self.sample_rate = int(sample_rate)
        self.name = name

    def __repr__(self) -> str:
        return '<%s %r %.3fs @%dHz>' % (
            type(self).__name__, self.name, self.duration, self.sample_rate)

    @property
    def frames(self) -> int:
        """How many samples the clip holds."""
        return int(self.samples.shape[0])

    @property
    def duration(self) -> float:
        """How long the clip lasts, in seconds, at its own rate."""
        return self.frames / float(self.sample_rate)

    @property
    def peak(self) -> float:
        """The largest absolute sample value; 0.0 for silence."""
        return float(np.abs(self.samples).max()) if self.frames else 0.0

    def normalised(self) -> 'Clip':
        """A copy scaled so its peak is 1.0; silence is returned unchanged."""
        peak = self.peak
        if peak == 0.0:
            return self
        return Clip(self.samples / peak, self.sample_rate, self.name)

    def resampled(self, sample_rate: int) -> 'Clip':
        """A copy at ``sample_rate``, linearly interpolated.

        Used where a clip arrives at a rate the engine does not mix at -- a
        synthesised clip, or one decoded before the engine's rate was known.
        Files go through :func:`decode_file`, which resamples during decoding
        and does it better.
        """
        if sample_rate == self.sample_rate or not self.frames:
            return self
        count = int(round(self.frames * sample_rate / self.sample_rate))
        position = np.arange(count, dtype=np.float64) * (self.sample_rate / sample_rate)
        return Clip(np.interp(position, np.arange(self.frames), self.samples),
                    sample_rate, self.name)


def decode_file(path: str, sample_rate: int = DEFAULT_SAMPLE_RATE) -> Clip:
    """Decode ``path`` to a mono :class:`Clip` at ``sample_rate``.

    The backend resamples and mixes to one channel as part of decoding, so this
    is one pass over the file rather than a decode followed by two conversions.

    Raises:
        DecodeError: where the backend is absent, the file is missing, or its
            contents are not audio this build can read.
    """
    backend = _backend()
    if backend is None:
        raise DecodeError(
            'cannot decode %r: miniaudio is not installed '
            '(install OpenGLContext[audio])' % (path,))
    try:
        decoded = backend.decode_file(
            path, output_format=backend.SampleFormat.FLOAT32,
            nchannels=1, sample_rate=sample_rate)
    except Exception as error:
        raise DecodeError('cannot decode %r: %s' % (path, error)) from error
    return Clip(np.frombuffer(memoryview(decoded.samples), dtype=np.float32),
                sample_rate, name=path)


#: What a cache calls to turn a name into samples.  Swappable so a test, or an
#: application with its own resolver, can supply clips without touching a disk.
Decoder = Callable[[str, int], Clip]


class ClipCache:
    """Decoded clips, keyed by resolved path, decoded at most once.

    A weapon fired sixty times a second names the same file sixty times; this is
    what keeps that one decode.  A name that fails to decode is remembered as a
    failure, so a missing file warns once rather than once per shot.

    Not thread-safe by design: it is used from the control thread only, which is
    the same rule that keeps decoding off the audio thread.
    """

    def __init__(self, sample_rate: int = DEFAULT_SAMPLE_RATE,
                 decode: Optional[Decoder] = None) -> None:
        self.sample_rate = int(sample_rate)
        self.decode = decode if decode is not None else decode_file
        self._clips: Dict[str, Clip] = {}
        self._failed: Set[str] = set()

    def __len__(self) -> int:
        return len(self._clips)

    @property
    def frames_held(self) -> int:
        """Total samples held, for anyone budgeting memory."""
        return sum(clip.frames for clip in self._clips.values())

    def key(self, name: str) -> str:
        """The cache key for ``name``: its resolved path where it names a file.

        Two spellings of one file are one entry.  A name that is not a path --
        a synthesised sound registered with :meth:`put` -- is its own key.
        """
        if name in self._clips or name in self._failed:
            return name
        try:
            resolved = os.path.normpath(os.path.abspath(name))
        except (OSError, ValueError):
            return name
        return resolved if os.path.exists(resolved) else name

    def put(self, name: str, clip: Clip) -> Clip:
        """Register ``clip`` under ``name``, resampling it if it needs it."""
        if clip.sample_rate != self.sample_rate:
            clip = clip.resampled(self.sample_rate)
        self._clips[name] = clip
        self._failed.discard(name)
        return clip

    def get(self, name: str) -> Optional[Clip]:
        """The clip for ``name``, decoding it if this is the first ask.

        Returns None where the name cannot be decoded.  A sound that will not
        load is a silence and a warning, never an exception: content is often
        incomplete, and a missing footstep must not stop a scene from running.
        """
        key = self.key(name)
        clip = self._clips.get(key)
        if clip is not None:
            return clip
        if key in self._failed:
            return None
        try:
            clip = self.decode(key, self.sample_rate)
        except DecodeError as error:
            self._failed.add(key)
            log.warning('no sound for %s', error)
            return None
        return self.put(key, clip)

    def clear(self) -> None:
        """Drop every decoded clip and every remembered failure."""
        self._clips.clear()
        self._failed.clear()
