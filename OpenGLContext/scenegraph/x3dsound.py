"""X3D's Sound component as nodes of omi_audio's processing graph

Each node here is the X3D declaration with what the engine needs to play it:
:meth:`SoundNode.makeAudio` makes the :mod:`omi_audio.graph` node it is,
:meth:`SoundNode.applyAudio` writes its fields onto that node once a frame,
and :meth:`SoundNode.audioInputs` names the X3D nodes it reads. The timing of
the sources and processing nodes is pyvrml97's (:mod:`vrml.x3d.sound`).
:class:`~OpenGLContext.audio.x3dgraph.SoundGraph` walks a scene's sound nodes
each frame, wires their graph nodes together and decides what is heard.

=========================  ====================================================
X3D node                   omi_audio graph node
=========================  ====================================================
AudioDestination,          :class:`~omi_audio.graph.Gain`, heard
StreamAudioDestination
Sound, SpatialSound        :class:`~omi_audio.graph.Panner` placed each frame
                           (a :class:`~omi_audio.graph.Gain` with
                           ``spatialize`` FALSE)
AudioClip,                 :class:`~omi_audio.graph.BufferSource`
BufferAudioSource
OscillatorSource,          :class:`~omi_audio.graph.Oscillator` playing a
PeriodicWave               :class:`~omi_audio.graph.PeriodicWave`
MicrophoneSource,          :class:`~omi_audio.graph.CaptureSource`, an input
StreamAudioSource          opened only where the application allows capture
ListenerPointSource        silence; it moves where the spatial sounds are heard
Gain, Delay, BiquadFilter, the graph node of the same name
Convolver, WaveShaper,
DynamicsCompressor,
Analyser, ChannelSplitter,
ChannelMerger,
ChannelSelector
=========================  ====================================================

Reference:
    https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html
"""
from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

import numpy as np
from numpy.typing import NDArray
from omi_audio import graph, model, spatial
from omi_audio.graph.panner import SPEED_OF_SOUND
from vrml import cache, node
from vrml.x3d import nodes as x3d
from vrml.x3d import sound as timing

from OpenGLContext.scenegraph.audio import clip_from_urls, direction_to_world, point_to_world

if TYPE_CHECKING:
    from OpenGLContext.audio.x3dgraph import SoundGraph

log = logging.getLogger(__name__)

__all__ = [
    'Analyser', 'AudioClip', 'AudioDestination', 'BiquadFilter', 'BufferAudioSource',
    'ChannelMerger', 'ChannelSelector', 'ChannelSplitter', 'Convolver', 'Delay',
    'DynamicsCompressor', 'Gain', 'ListenerPointSource', 'MicrophoneSource',
    'Hearing', 'OscillatorSource', 'PeriodicWave', 'Placement', 'SILENT', 'Sound', 'SoundNode',
    'scaled',
    'SpatialSound', 'StreamAudioDestination', 'StreamAudioSource', 'WaveShaper',
]

#: X3D's channel count modes as omi_audio names them.
CHANNEL_COUNT_MODES = {'MAX': 'max', 'CLAMPED_MAX': 'clamped-max', 'EXPLICIT': 'explicit'}

#: X3D's channel interpretations as omi_audio names them.
INTERPRETATIONS = {'SPEAKERS': 'speakers', 'DISCRETE': 'discrete'}

#: The longest propagation delay a SpatialSound's Doppler effect reaches, in
#: seconds: 343 m of air.
MAX_PROPAGATION_DELAY = 1.0

#: The smallest `referenceDistance` the distance models divide by, in metres.
MIN_REFERENCE_DISTANCE = 1e-6

#: The cache key under which a node keeps the samples its fields describe.
SAMPLES_KEY = 'x3dsound-samples'

_EMPTY = np.zeros(0, dtype=np.float32)


def assign(target: Any, name: str, value: Any) -> None:
    """Set ``target.name`` to ``value`` where it differs

    A graph node's setter may redesign a filter or reselect a table, so a
    value that has not changed is not written again.
    """
    if getattr(target, name) != value:
        setattr(target, name, value)


class Placement(NamedTuple):
    """Where a Sound or SpatialSound is heard: its ear gains, its level, its delay"""

    left: float
    right: float
    #: The level before panning, which ranks it against the others.
    level: float
    #: Seconds the sound takes to reach the listener; 0 without Doppler.
    delay: float = 0.0


#: A sound not heard.
SILENT = Placement(0.0, 0.0, 0.0)


def scaled(placement: Placement, share: float) -> Placement:
    """`placement` heard at `share` of its level"""
    if share >= 1.0:
        return placement
    return placement._replace(left=placement.left * share, right=placement.right * share,
                              level=placement.level * share)


class SoundNode:
    """An X3D sound node played as a node of omi_audio's graph"""

    children: Any
    enabled: Any
    channelInterpretation: Any

    def audioInputs(self) -> list[Any]:
        """The sound nodes this node reads: its `children`"""
        return [child for child in getattr(self, 'children', ()) or ()
                if isinstance(child, SoundNode)]

    def audioOutputs(self) -> Sequence[Any]:
        """The nodes that each read one of this node's channels; none"""
        return ()

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        """The graph node this X3D node plays as, in ``made``'s engine"""
        raise NotImplementedError('%s makes no graph node' % type(self).__name__)

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        """Write this node's fields onto ``audio``: its gain and channel handling"""
        if hasattr(self, 'gain'):
            assign(audio, 'gain', float(self.gain))
        mode = getattr(self, 'channelCountMode', None)
        if mode is not None:
            assign(audio, 'channel_count_mode', CHANNEL_COUNT_MODES.get(str(mode), 'max'))
            assign(audio, 'channel_interpretation',
                   INTERPRETATIONS.get(str(self.channelInterpretation), 'speakers'))

    def runAudio(self, audio: Any, rejoined: bool) -> None:
        """Start, pause or silence ``audio`` as this node's time says

        ``rejoined`` is true on the frame the node is first heard, or heard
        again after a time out of the graph.
        """

    def reportAudio(self, audio: Any, made: SoundGraph) -> None:
        """Send what the graph node reports: `channelCount` where the node has one"""
        if getattr(type(self), 'channelCount', None) is not None and \
                made.changed(self, 'channelCount', audio.channels):
            self.channelCount = int(audio.channels)


class Timed(SoundNode):
    """A sound node that runs from `startTime` to `stopTime` (pyvrml97's timing)"""

    running: Any
    paused: Any

    def runAudio(self, audio: Any, rejoined: bool) -> None:
        running = bool(self.running())
        if running and (rejoined or not audio.playing):
            self.startAudio(audio)
        audio.playing = running
        audio.paused = bool(self.paused())

    def startAudio(self, audio: Any) -> None:
        """Begin ``audio`` where this node's time has reached; nothing to do by default"""


class Processing(Timed):
    """A processing node: its input passes through unchanged while not `enabled`

    The node's time runs whether it is enabled or not; it is silent before
    `startTime`, after `stopTime` and while paused.
    """

    def clockEnabled(self) -> bool:
        return True

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'enabled', bool(self.enabled))


# ----------------------------------------------------------------------
# Destinations
# ----------------------------------------------------------------------

class Destination(SoundNode):
    """What is heard: everything connected to it, mixed and sent to the output

    The engine has one output, the audio device, so `mediaDeviceID` chooses
    nothing. `maxChannelCount` is the channel count it mixes to with
    `channelCountMode` EXPLICIT or CLAMPED_MAX.
    """

    maxChannelCount: Any
    isActive: Any

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Gain()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'channel_count', max(1, int(getattr(self, 'maxChannelCount', 2))))


class AudioDestination(Destination, x3d.AudioDestination):
    """The audio device: its children are heard"""


class StreamAudioDestination(Destination, x3d.StreamAudioDestination):
    """Heard, as an AudioDestination is: a desktop engine's output stream is its device

    `streamIdentifier` names a W3C media stream, which a desktop engine does
    not have; the node's input is sent to the engine's output.
    """


# ----------------------------------------------------------------------
# Placed sounds
# ----------------------------------------------------------------------

Vec3 = tuple[float, float, float]

#: Three numbers as a field holds them, or as a sequence.
Triple = Sequence[float] | NDArray[Any]


def _point(rows: Sequence[Sequence[float]], point: Triple) -> Vec3:
    """``point`` carried by the row-vector matrix ``rows``"""
    x, y, z = float(point[0]), float(point[1]), float(point[2])
    return (x * rows[0][0] + y * rows[1][0] + z * rows[2][0] + rows[3][0],
            x * rows[0][1] + y * rows[1][1] + z * rows[2][1] + rows[3][1],
            x * rows[0][2] + y * rows[1][2] + z * rows[2][2] + rows[3][2])


def _direction(rows: Sequence[Sequence[float]], direction: Triple) -> Vec3:
    """``direction`` turned by the row-vector matrix ``rows``, its translation ignored"""
    x, y, z = float(direction[0]), float(direction[1]), float(direction[2])
    return (x * rows[0][0] + y * rows[1][0] + z * rows[2][0],
            x * rows[0][1] + y * rows[1][1] + z * rows[2][1],
            x * rows[0][2] + y * rows[1][2] + z * rows[2][2])


def _dot(first: Vec3, second: Vec3) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


class Hearing:
    """A listener's position and axes as numbers, for placing many sounds a frame

    The bearings are :class:`omi_audio.spatial.Listener`'s: azimuth in the
    listener's horizontal plane, positive to the right.
    """

    def __init__(self, listener: spatial.Listener) -> None:
        self.listener = listener
        self.position: Vec3 = tuple(float(value) for value in listener.position[:3])  # type: ignore[assignment]  # three components
        self.forward: Vec3 = tuple(float(value) for value in listener.forward[:3])  # type: ignore[assignment]  # three components
        self.up: Vec3 = tuple(float(value) for value in listener.up[:3])  # type: ignore[assignment]  # three components
        self.right: Vec3 = tuple(float(value) for value in listener.right[:3])  # type: ignore[assignment]  # three components

    def offset(self, point: Vec3) -> tuple[Vec3, float]:
        """The way from ``point`` to the listener, and its length"""
        way = (self.position[0] - point[0], self.position[1] - point[1],
               self.position[2] - point[2])
        return way, math.sqrt(_dot(way, way))

    def azimuth(self, point: Vec3) -> float:
        """The bearing of ``point`` from the listener; 0 ahead, positive to the right"""
        way, length = self.offset(point)
        if length == 0.0:
            return 0.0
        toward = (-way[0] / length, -way[1] / length, -way[2] / length)
        vertical = _dot(toward, self.up)
        across = (toward[0] - vertical * self.up[0], toward[1] - vertical * self.up[1],
                  toward[2] - vertical * self.up[2])
        if across == (0.0, 0.0, 0.0):
            return 0.0
        return math.atan2(_dot(across, self.right), _dot(across, self.forward))

    def ears(self, point: Vec3, level: float, spatialize: bool = True) -> tuple[float, float]:
        """``level`` split between the ears for a sound at ``point``

        Equal-power panning on the bearing
        (:func:`omi_audio.spatial.equal_power_pan`); a sound not spatialised
        is centred.
        """
        if level <= 0.0 or not math.isfinite(level):
            return 0.0, 0.0
        if not spatialize:
            centre = level * math.sqrt(0.5)
            return centre, centre
        left, right = spatial.equal_power_pan(self.azimuth(point))
        return level * left, level * right


class Placed(SoundNode):
    """A sound heard from a place: a Panner, or a Gain where it is not spatialised"""

    spatialize: Any
    priority: Any

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        if self.spatialize:
            return graph.Panner(max_propagation_delay=MAX_PROPAGATION_DELAY)
        return graph.Gain()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        """The gains are the placement's (:meth:`placeAudio`)"""

    location: Any

    def origin(self, matrix: Any) -> Vec3:
        """Where the sound comes from in the world, with this node at ``matrix``"""
        return _point(matrix.tolist(), self.location)

    def placement(self, matrix: Any, hearing: Hearing) -> Placement:
        """Where the sound is heard from ``hearing``, with this node at ``matrix``"""
        raise NotImplementedError

    def placeAudio(self, audio: Any, placement: Placement) -> None:
        """Hear ``audio`` as ``placement`` says"""
        if isinstance(audio, graph.Panner):
            audio.set_gains(placement.left, placement.right)
            audio.propagation_delay = placement.delay
        else:
            audio.gain = placement.level


class Sound(Placed, x3d.Sound):
    """X3D's (and VRML97's) Sound: its `source` heard between two ellipsoids

    Full `intensity` inside the inner ellipsoid (`minFront`, `minBack`),
    silence outside the outer (`maxFront`, `maxBack`), and between them a ramp
    linear in decibels down to -20 dB (:func:`omi_audio.spatial.ellipsoid_gain_at`),
    both ellipsoids with a focus at `location` and their axis along
    `direction`. With `spatialize` the sound is panned by its bearing from the
    listener; without it, a source's channels are kept apart.

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#Sound
    """

    def audioInputs(self) -> list[Any]:
        """The `source`, where it is a sound node"""
        return [self.source] if isinstance(self.source, SoundNode) else []

    def placement(self, matrix: Any, hearing: Hearing) -> Placement:
        if not self.enabled:
            return SILENT
        rows = matrix.tolist()
        location = _point(rows, self.location)
        way, distance = hearing.offset(location)
        if distance == 0.0:
            gain = 1.0
        else:
            axis = _direction(rows, self.direction)
            length = math.sqrt(_dot(axis, axis))
            cosine = _dot(axis, way) / (length * distance) if length > 0.0 else 1.0
            gain = spatial.ellipsoid_gain(
                distance, cosine, min_front=float(self.minFront), min_back=float(self.minBack),
                max_front=float(self.maxFront), max_back=float(self.maxBack))
        level = float(self.intensity) * gain
        left, right = hearing.ears(location, level, bool(self.spatialize))
        return Placement(left, right, level)


class SpatialSound(Placed, x3d.SpatialSound):
    """A Web Audio panner: its children heard from `location`

    The level is `gain` times `intensity` times the distance model's gain
    (`distanceModel`, `referenceDistance`, `maxDistance`, `rolloffFactor`)
    times the cone's (`coneInnerAngle`, `coneOuterAngle`, `coneOuterGain`
    about `direction`), panned by the bearing from the listener. With
    `dopplerEnabled` the sound arrives the distance over the speed of sound
    late, up to :data:`MAX_PROPAGATION_DELAY`, so a sound moving toward or away
    from the listener changes pitch. `enableHRTF` is not read: the pan is
    equal power between two ears.

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#SpatialSound
    """

    def __init__(self, **named: Any) -> None:
        super().__init__(**named)
        self._positional = model.PositionalProperties(shapeType=spatial.ShapeType.CONE.value)

    def positional(self) -> model.PositionalProperties:
        """The distance and cone fields as omi_audio's record, rewritten in place"""
        record = self._positional
        record.coneInnerAngle = float(self.coneInnerAngle)
        record.coneOuterAngle = max(float(self.coneOuterAngle), record.coneInnerAngle)
        record.coneOuterGain = float(self.coneOuterGain)
        record.distanceModel = str(self.distanceModel).lower()
        record.maxDistance = float(self.maxDistance)
        record.refDistance = max(float(self.referenceDistance), MIN_REFERENCE_DISTANCE)
        record.rolloffFactor = float(self.rolloffFactor)
        return record

    def placement(self, matrix: Any, hearing: Hearing) -> Placement:
        if not self.enabled:
            return SILENT
        rows = matrix.tolist()
        location = _point(rows, self.location)
        way, distance = hearing.offset(location)
        angle = 0.0
        axis = _direction(rows, self.direction)
        length = math.sqrt(_dot(axis, axis))
        if distance > 0.0 and length > 0.0:
            angle = math.acos(max(-1.0, min(1.0, _dot(axis, way) / (length * distance))))
        level = float(self.gain) * float(self.intensity) * self.positional().gain(distance, angle)
        left, right = hearing.ears(location, level, bool(self.spatialize))
        delay = distance / SPEED_OF_SOUND if self.dopplerEnabled else 0.0
        return Placement(left, right, level, min(delay, MAX_PROPAGATION_DELAY))


# ----------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------

class _Samples(NamedTuple):
    """Samples a node's fields describe: ``(channels, frames)`` at ``rate``; 0 is the engine's"""

    data: NDArray[np.float32]
    rate: float


def _clip_samples(owner: Any, urls: Sequence[str], engine: Any) -> Optional[_Samples]:
    """The first of ``urls`` that decodes, as samples; None for none"""
    clip = clip_from_urls(owner, urls, engine)
    if clip is None:
        return None
    return _Samples(clip.samples.reshape(1, -1), float(clip.sample_rate))


class Buffered(Timed):
    """A source playing samples: a BufferSource started where its time has reached"""

    loop: Any
    position: Any

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.BufferSource()

    def playedSamples(self, engine: Any) -> Optional[_Samples]:
        """The samples to play, kept until the fields they come from change"""
        held = cache.CACHE.getData(self, SAMPLES_KEY)
        if held is None:
            held = (self._readSamples(engine),)
            holder = cache.CACHE.holder(self, held, SAMPLES_KEY)
            for name in self._samplesFrom():
                holder.depend(self, name)
            self._loaded(held[0], engine)
        return held[0]  # type: ignore[no-any-return]  # the cache holds what was put

    def _samplesFrom(self) -> tuple[str, ...]:
        return ('url',)

    def _readSamples(self, engine: Any) -> Optional[_Samples]:
        raise NotImplementedError

    def _loaded(self, samples: Optional[_Samples], engine: Any) -> None:
        """Send what the samples tell of themselves"""

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        found = self.playedSamples(made.engine)
        if made.changed(self, 'samples', found):
            if found is None:
                audio.set_buffer(_EMPTY, made.engine.sample_rate)
            else:
                audio.set_buffer(found.data, found.rate or made.engine.sample_rate)
            audio.playing = False
        assign(audio, 'loop', bool(self.loop))

    def startAudio(self, audio: Any) -> None:
        audio.start(offset=self.position())

    def reportAudio(self, audio: Any, made: SoundGraph) -> None:
        """Nothing: what the samples are is sent as they are read"""


class AudioClip(Buffered, timing.AudioClip):
    """A sound file: the first of `url` that decodes, at `pitch`

    The url is read as the document's other references are
    (:func:`~OpenGLContext.scenegraph.audio.clip_from_urls`), decoded to one
    channel at the engine's rate. A clip that starts after its `startTime`
    plays from where its time has reached.

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#AudioClip
    """

    def _readSamples(self, engine: Any) -> Optional[_Samples]:
        return _clip_samples(self, self.url, engine)

    def _loaded(self, samples: Optional[_Samples], engine: Any) -> None:
        self.setDuration(None if samples is None else samples.data.shape[1] / samples.rate)

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'playback_rate', self.playingPitch())


class BufferAudioSource(Buffered, timing.BufferAudioSource):
    """Samples in the node: `buffer` (each channel's after the last's) or the first of `url`

    `buffer` is played where it holds samples, at `sampleRate` (the engine's
    rate where that is 0); otherwise `url` is read as an AudioClip's is.

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#BufferAudioSource
    """

    def _samplesFrom(self) -> tuple[str, ...]:
        return ('url', 'buffer', 'numberOfChannels', 'sampleRate')

    def _readSamples(self, engine: Any) -> Optional[_Samples]:
        data = self.samples_from_buffer()
        if data.shape[1] == 0 and self.url:
            return _clip_samples(self, self.url, engine)
        return _Samples(data, float(self.sampleRate))

    def samples_from_buffer(self) -> NDArray[np.float32]:
        """`buffer` as ``(channels, frames)``"""
        return timing.BufferAudioSource.samples(self)

    def _loaded(self, samples: Optional[_Samples], engine: Any) -> None:
        if samples is None:
            self.setBuffer(0, 0, 0.0)
            return
        channels, frames = samples.data.shape
        self.setBuffer(frames, channels, samples.rate or engine.sample_rate)

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'loop_start', float(self.loopStart))
        assign(audio, 'loop_end', float(self.loopEnd))
        assign(audio, 'playback_rate', float(self.playbackRate))
        assign(audio, 'detune', float(self.detune))


class PeriodicWave(SoundNode, x3d.PeriodicWave):
    """One cycle of a waveform: SINE, SQUARE, SAWTOOTH, TRIANGLE, or CUSTOM from `optionsReal` and `optionsImag`

    CUSTOM is a Fourier series as Web Audio's PeriodicWave defines it, the
    first of each list ignored, normalised to a peak of 1.
    """

    WAVE_KEY = 'x3dsound-wave'

    def wave(self) -> graph.PeriodicWave:
        """The omi_audio wave, kept until `type` or a coefficient list changes"""
        found: Optional[graph.PeriodicWave] = cache.CACHE.getData(self, self.WAVE_KEY)
        if found is None:
            kind = str(self.type).lower()
            if kind == 'custom' or kind not in graph.WAVE_TYPES:
                found = graph.PeriodicWave(real=list(self.optionsReal),
                                           imag=list(self.optionsImag))
            else:
                found = graph.PeriodicWave.of_type(kind)
            holder = cache.CACHE.holder(self, found, self.WAVE_KEY)
            for name in ('type', 'optionsReal', 'optionsImag'):
                holder.depend(self, name)
        return found


class OscillatorSource(Timed, timing.OscillatorSource):
    """A periodic waveform at `frequency` hertz and `detune` cents: a sine, or its `periodicWave`

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#OscillatorSource
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Oscillator()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        wave = self.periodicWave
        chosen = wave.wave() if isinstance(wave, PeriodicWave) else None
        if made.changed(self, 'wave', chosen):
            audio.wave = chosen
        assign(audio, 'frequency', float(self.frequency))
        assign(audio, 'detune', float(self.detune))

    def startAudio(self, audio: Any) -> None:
        audio.start()


class Captured(Timed):
    """A source playing an audio input, opened only where the application allows capture

    :meth:`captureDevice` names the input. The
    :class:`~OpenGLContext.audio.x3dgraph.SoundGraph` opens it while the node
    is heard and running and capture is allowed, and closes it otherwise.
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.CaptureSource()

    def captureDevice(self) -> str:
        """The input to open, by part of its name; empty is the system's default"""
        raise NotImplementedError


class MicrophoneSource(Captured, timing.MicrophoneSource):
    """The input `mediaDeviceID` names, or the system's default input

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/sound.html#MicrophoneSource
    """

    def captureDevice(self) -> str:
        return str(self.mediaDeviceID)


class StreamAudioSource(Captured, timing.StreamAudioSource):
    """The input the first `streamIdentifier` names, or the system's default input

    A desktop engine has no W3C media streams; its streams of audio are its
    inputs.
    """

    def captureDevice(self) -> str:
        return str(self.streamIdentifier[0]) if self.streamIdentifier else ''


class ListenerPointSource(Timed, timing.ListenerPointSource):
    """Where the Sound and SpatialSound nodes are heard from, while `trackCurrentView` is FALSE

    The listening point is `position`, facing `orientation` applied to -Z,
    in the node's frame. With `trackCurrentView` TRUE the camera is the
    listener. As an input to another node it is silence: the engine mixes
    one listener's hearing. `interauralDistance` is not read.
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Gain()

    def listener(self, matrix: Any) -> Optional[spatial.Listener]:
        """The listener this node places at ``matrix``; None while it tracks the view or is off"""
        if self.trackCurrentView or not self.enabled or not self.running():
            return None
        axis = np.asarray(self.orientation[:3], dtype='d')
        rotation = _rotation(axis, float(self.orientation[3]))
        forward = direction_to_world(rotation @ np.array([0.0, 0.0, -1.0]), matrix)
        up = direction_to_world(rotation @ np.array([0.0, 1.0, 0.0]), matrix)
        return spatial.Listener(point_to_world(self.position, matrix), forward, up)


def _rotation(axis: NDArray[np.float64], angle: float) -> NDArray[np.float64]:
    """The 3x3 matrix turning column vectors ``angle`` radians about ``axis``"""
    length = float(np.linalg.norm(axis))
    if length == 0.0 or not math.isfinite(angle):
        return np.identity(3)
    x, y, z = axis / length
    cos, sin = math.cos(angle), math.sin(angle)
    turn = 1.0 - cos
    return np.array([
        [cos + x * x * turn, x * y * turn - z * sin, x * z * turn + y * sin],
        [y * x * turn + z * sin, cos + y * y * turn, y * z * turn - x * sin],
        [z * x * turn - y * sin, z * y * turn + x * sin, cos + z * z * turn],
    ])


# ----------------------------------------------------------------------
# Processing
# ----------------------------------------------------------------------

class Gain(Processing, timing.Gain):
    """Its input times `gain`"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Gain()


class Delay(Processing, timing.Delay):
    """Its input `delayTime` seconds later, up to `maxDelayTime`"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Delay()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'max_delay_time', float(self.maxDelayTime))
        assign(audio, 'delay_time', float(self.delayTime))


class BiquadFilter(Processing, timing.BiquadFilter):
    """A second-order filter of `type`; its `gain` is the shelf or peak boost in decibels"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.BiquadFilter()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        audio.gain = 1.0
        kind = str(self.type).lower()
        assign(audio, 'kind', kind if kind in graph.FILTER_TYPES else 'lowpass')
        assign(audio, 'frequency', float(self.frequency))
        assign(audio, 'q', float(self.qualityFactor))
        assign(audio, 'detune', float(self.detune))
        assign(audio, 'filter_gain', float(self.gain))


class Convolver(Processing, timing.Convolver):
    """Its input convolved with `buffer`, one channel of impulse response

    X3D's Convolver gives no channel count for its buffer, so the response is
    one channel.
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.Convolver()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'normalize', bool(self.normalize))
        response = self.buffer
        if made.changed(self, 'buffer', response):
            audio.set_response(np.asarray(response, dtype='d').reshape(-1))


class DynamicsCompressor(Processing, timing.DynamicsCompressor):
    """A compressor; sends `reduction`, the gain reduction in decibels"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.DynamicsCompressor()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'threshold', float(self.threshold))
        assign(audio, 'knee', float(self.knee))
        assign(audio, 'ratio', float(self.ratio))
        assign(audio, 'attack', float(self.attack))
        assign(audio, 'release', float(self.release))

    def reportAudio(self, audio: Any, made: SoundGraph) -> None:
        super().reportAudio(audio, made)
        reduction = round(float(audio.reduction), 3)
        if made.changed(self, 'reduction', reduction):
            self.reduction = reduction


class WaveShaper(Processing, timing.WaveShaper):
    """Each sample through `curve`, oversampled NONE, 2X or 4X"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.WaveShaper()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        oversample = str(self.oversample).lower()
        assign(audio, 'oversample', oversample if oversample in graph.OVERSAMPLING else 'none')
        curve = self.curve
        if made.changed(self, 'curve', curve):
            audio.curve = np.asarray(curve, dtype='d').reshape(-1)


class Analyser(Processing, timing.Analyser):
    """Its input unchanged, with the recent past kept to look at

    :meth:`frequencyData` and :meth:`timeDomainData` (and their byte forms)
    are the Web Audio AnalyserNode's, from the graph node of the latest
    graph the analyser is heard in; empty where it is in none. `gain`
    scales what is analysed, not the signal.
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        made_node = graph.Analyser()
        self.__dict__['_analyserNode'] = made_node
        return made_node

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'fft_size', int(self.fftSize))
        assign(audio, 'min_decibels', float(self.minDecibels))
        assign(audio, 'max_decibels', float(self.maxDecibels))
        assign(audio, 'smoothing', float(self.smoothingTimeConstant))
        if int(self.frequencyBinCount) != audio.frequency_bin_count:
            self.frequencyBinCount = audio.frequency_bin_count

    def _analysed(self) -> Optional[graph.Analyser]:
        found = self.__dict__.get('_analyserNode')
        return found if found is not None and found.graph is not None else None

    def frequencyData(self) -> NDArray[np.float64]:
        """Each frequency bin's smoothed level in decibels; one smoothing step a call"""
        found = self._analysed()
        return found.frequency_data() if found is not None else np.zeros(0)

    def timeDomainData(self) -> NDArray[np.float32]:
        """The latest `fftSize` samples analysed, oldest first"""
        found = self._analysed()
        return found.time_domain_data() if found is not None else np.zeros(0, np.float32)

    def byteFrequencyData(self) -> NDArray[np.uint8]:
        """:meth:`frequencyData` from `minDecibels` to `maxDecibels` as 0 to 255"""
        found = self._analysed()
        return found.byte_frequency_data() if found is not None else np.zeros(0, np.uint8)

    def byteTimeDomainData(self) -> NDArray[np.uint8]:
        """:meth:`timeDomainData` from -1 to 1 as 0 to 255"""
        found = self._analysed()
        return found.byte_time_domain_data() if found is not None else np.zeros(0, np.uint8)


# ----------------------------------------------------------------------
# Channels
# ----------------------------------------------------------------------

class ChannelSplitter(SoundNode, x3d.ChannelSplitter):
    """Its input's channels kept apart: each of `outputs` reads one, in order

    A ChannelSelector reading the splitter takes one channel of it too.
    """

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.ChannelSplitter()

    def audioOutputs(self) -> Sequence[Any]:
        return [found for found in self.outputs if isinstance(found, SoundNode)]


class ChannelMerger(SoundNode, x3d.ChannelMerger):
    """One channel for each child, in order, each mixed to mono"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.ChannelMerger()


class ChannelSelector(SoundNode, x3d.ChannelSelector):
    """Channel `channelSelection` of its input, counting from 0"""

    def makeAudio(self, made: SoundGraph) -> graph.Node:
        return graph.ChannelSelector()

    def applyAudio(self, audio: Any, made: SoundGraph) -> None:
        super().applyAudio(audio, made)
        assign(audio, 'selection', int(self.channelSelection))


#: Every class here, by X3D name, for the registry.
NODES: dict[str, type[node.Node]] = {
    cls.__name__: cls for cls in (
        Analyser, AudioClip, AudioDestination, BiquadFilter, BufferAudioSource,
        ChannelMerger, ChannelSelector, ChannelSplitter, Convolver, Delay,
        DynamicsCompressor, Gain, ListenerPointSource, MicrophoneSource,
        OscillatorSource, PeriodicWave, Sound, SpatialSound, StreamAudioDestination,
        StreamAudioSource, WaveShaper,
    )
}
