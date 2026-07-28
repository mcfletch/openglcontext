"""The one object an application holds, and the only one it needs.

An :class:`AudioEngine` owns the four pieces below it -- a device, a mixer, a
clip cache and a listener -- and gives them a single job to do together: *play
this sound, at this place in the world, heard from here*.

The division of labour is the point:

======================  ========================================================
Control thread          Resolves a name to a clip, decodes it, works out the
                        distance, cone and pan gains, and starts a voice.  All of
                        it here, in :class:`AudioEngine`.
Audio thread            Multiplies samples by gains and adds them up.  All of it
                        in :class:`~OpenGLContext.audio.mixer.Mixer`, which never
                        sees a path, a matrix or a listener.
======================  ========================================================

A moving sound is *re-aimed*, not restarted: :meth:`AudioEngine.aim` writes two
floats onto a playing voice, and the mixer ramps to them across the next block.
That is why a scene can update every sound it has every frame without the audio
thread noticing.

Nothing here can fail loudly.  A clip that will not decode, a device that will
not open, a pool with no free voice: each is a silence, and each is reported
once.  Sound is a thing a scene has, not a thing it depends on.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext.audio import model
from OpenGLContext.audio.clip import Clip, ClipCache
from OpenGLContext.audio.device import AudioDevice, open_device
from OpenGLContext.audio.mixer import DEFAULT_VOICES, Mixer, VoiceHandle
from OpenGLContext.audio.spatial import Listener, equal_power_pan

log = logging.getLogger(__name__)

#: A clip, or the name of one to resolve through the cache.
Source = Union[Clip, str]

#: A glTF emitter faces its own ``-Z``, as ``KHR_lights_punctual`` and glTF
#: cameras do.  An emitter with no transform of its own therefore points here.
DEFAULT_FORWARD = (0.0, 0.0, -1.0)


class AudioEngine:
    """Sound for one scene: a device, a mixer, a cache and a listener."""

    def __init__(self, device: Optional[AudioDevice] = None,
                 voices: int = DEFAULT_VOICES,
                 master_gain: float = 1.0,
                 clips: Optional[ClipCache] = None) -> None:
        self.device = device if device is not None else open_device()
        self.mixer = Mixer(sample_rate=self.device.sample_rate, voices=voices,
                           master_gain=master_gain)
        self._master_gain = float(master_gain)
        self._volume = 1.0
        self.clips = clips if clips is not None else ClipCache(
            sample_rate=self.device.sample_rate)
        #: Where the ears are.  Replace it each frame; see :meth:`listen`.
        self.listener = Listener()
        self._closed = False
        self.device.start(self.mixer.blocks())
        log.info('audio engine started (%s)',
                 'silent' if self.silent else 'device %d Hz' % (self.device.sample_rate,))

    # ------------------------------------------------------------------
    # Whole-engine controls
    # ------------------------------------------------------------------

    @property
    def silent(self) -> bool:
        """Whether anything played will actually be heard."""
        return self.device.silent

    @property
    def sample_rate(self) -> int:
        """Frames per second the whole chain runs at."""
        return self.mixer.sample_rate

    @property
    def active_voices(self) -> int:
        """How many sounds are playing right now."""
        return self.mixer.active_voices

    @property
    def master_gain(self) -> float:
        """The **application's** mix level: how loud this scene is authored to be.

        An application sets it once; the player never sees it.  It multiplies
        with :attr:`volume` rather than competing with it, which is what keeps a
        per-frame refresh of the player's setting from silently undoing it.
        """
        return self._master_gain

    @master_gain.setter
    def master_gain(self, value: float) -> None:
        self._master_gain = max(0.0, float(value))
        self._applyGain()

    @property
    def volume(self) -> float:
        """The **player's** volume, from the settings screen: 0 to 1."""
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, float(value)))
        self._applyGain()

    def _applyGain(self) -> None:
        """The mixer sees one number; the two above are what make it."""
        self.mixer.master_gain = self._master_gain * self._volume

    @property
    def muffle(self) -> float:
        """How low-passed the whole mix is: 0 clear, 1 underwater."""
        return self.mixer.muffle

    @muffle.setter
    def muffle(self, value: float) -> None:
        self.mixer.muffle = value

    def listen(self, platform: Any) -> Listener:
        """Move the listener to a view platform's pose, and return it.

        Called once a frame from the render loop.  The camera *is* the listener:
        keeping them separate buys nothing and gives two things to forget.
        """
        self.listener = Listener.from_view_platform(platform)
        return self.listener

    def stop_all(self) -> None:
        """Silence every sound at once."""
        self.mixer.stop_all()

    def close(self) -> None:
        """Stop everything and release the device.  Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self.mixer.stop_all()
        self.device.close()

    # ------------------------------------------------------------------
    # Clips
    # ------------------------------------------------------------------

    def clip(self, source: Source) -> Optional[Clip]:
        """``source`` as a decoded clip, or None where it will not resolve."""
        if isinstance(source, Clip):
            return source
        return self.clips.get(source)

    # ------------------------------------------------------------------
    # Spatialisation
    # ------------------------------------------------------------------

    def gains_for(self, emitter: model.AudioEmitter,
                  position: Optional[Sequence[float]] = None,
                  forward: Sequence[float] = DEFAULT_FORWARD,
                  gain: float = 1.0) -> Tuple[float, float]:
        """The per-ear gains for ``emitter`` heard from the current listener.

        ``position`` and ``forward`` are the emitter's **world** pose, which for
        a scenegraph node is its accumulated transform.  A ``global`` emitter --
        or one with no position -- ignores both and is heard the same wherever
        the listener stands, which is what makes it the right shape for music.

        The result is the product of four independent things: the emitter's own
        ``gain``, the distance curve, the cone, and the equal-power pan.  Each is
        a separate function in :mod:`~OpenGLContext.audio.spatial`, which is what
        makes each of them testable and each of them replaceable.
        """
        level = gain * emitter.gain
        if position is None or not emitter.positional_audio or emitter.positional is None:
            return level * np.sqrt(0.5), level * np.sqrt(0.5)
        listener = self.listener
        distance = listener.distance_to(position)
        level *= emitter.positional.gain(distance, _cone_angle(position, forward, listener))
        if level <= 0.0:
            return 0.0, 0.0
        azimuth, _ = listener.azimuth_elevation(position)
        left, right = equal_power_pan(azimuth)
        return level * left, level * right

    # ------------------------------------------------------------------
    # Playing
    # ------------------------------------------------------------------

    def play(self, source: Source,
             emitter: Optional[model.AudioEmitter] = None,
             position: Optional[Sequence[float]] = None,
             forward: Sequence[float] = DEFAULT_FORWARD,
             gain: float = 1.0, priority: float = 0.0,
             loop: bool = False, rate: float = 1.0) -> Optional[VoiceHandle]:
        """Start ``source``, spatialised by ``emitter`` if one is given.

        Returns a handle to steer the sound with, or None where the clip will
        not resolve or the voice pool refuses it.  Both are ordinary outcomes,
        so a caller may use the result without checking it -- :meth:`aim`
        accepts None.
        """
        clip = self.clip(source)
        if clip is None:
            return None
        if emitter is None:
            left = right = gain * float(np.sqrt(0.5))
        else:
            left, right = self.gains_for(emitter, position, forward, gain)
        return self.mixer.play_gains(clip, left, right, priority=priority,
                                     loop=loop, rate=rate)

    def play_source(self, source: model.AudioSource,
                    document: model.AudioDocument,
                    emitter: Optional[model.AudioEmitter] = None,
                    position: Optional[Sequence[float]] = None,
                    forward: Sequence[float] = DEFAULT_FORWARD,
                    priority: float = 0.0) -> Optional[VoiceHandle]:
        """Play one ``KHR_audio_emitter`` source with its own settings.

        The source's ``gain``, ``loop`` and ``playbackRate`` come from the
        document rather than from the caller: they are what the author of the
        scene asked for, and honouring them is the whole point of reading the
        extension rather than inventing a format.
        """
        audio = document.audio_for(source)
        if audio is None:
            return None
        name = audio.uri or audio.name
        if not name:
            return None
        return self.play(name, emitter=emitter, position=position, forward=forward,
                         gain=source.gain, priority=priority, loop=source.loop,
                         rate=source.playbackRate)

    def aim(self, handle: Optional[VoiceHandle], emitter: model.AudioEmitter,
            position: Optional[Sequence[float]] = None,
            forward: Sequence[float] = DEFAULT_FORWARD,
            gain: float = 1.0) -> None:
        """Re-point a playing sound at where its emitter has moved to.

        Called every frame for every sounding emitter.  It writes two floats, so
        the cost of following a hundred moving sounds is a hundred pairs of
        floats -- and a handle whose sound has finished or been stolen quietly
        does nothing, so no caller has to test first.
        """
        if handle is None or not handle.playing:
            return
        left, right = self.gains_for(emitter, position, forward, gain)
        handle.set_gain(left, right)


def _cone_angle(position: Sequence[float], forward: Sequence[float],
                listener: Listener) -> float:
    """How far off its own forward axis the emitter has to look to see the listener.

    Zero means the listener is straight in front of the emitter, which is where
    a cone is at full volume.
    """
    axis = np.asarray(forward, dtype='d')[:3]
    length = float(np.linalg.norm(axis))
    if length == 0.0:
        return 0.0
    to_listener = listener.position - np.asarray(position, dtype='d')[:3]
    reach = float(np.linalg.norm(to_listener))
    if reach == 0.0:
        return 0.0
    cosine = float(np.dot(axis / length, to_listener / reach))
    return float(np.arccos(max(-1.0, min(1.0, cosine))))
