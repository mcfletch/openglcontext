"""Sound in the scenegraph: emitters, sources, and VRML97's ``Sound`` node.

Three nodes, and the split between them is the same split glTF's
``KHR_audio_emitter`` makes:

:class:`AudioSource`
    One clip and how it is played -- gain, loop, playback rate, whether it
    starts by itself.  Several emitters may share one.
:class:`AudioEmitter`
    Where the sound comes from, and how it fades with distance and direction.
    Put it under a ``Transform`` and the sound is wherever that transform is.
:class:`Sound`
    VRML97's own node, which pyvrml97 has always declared and nothing has ever
    played.  It attenuates differently -- two ellipsoids rather than a distance
    curve -- so it computes its own gain and shares everything else.

Every node has the same job once per frame: **be told where it is, and keep its
sounds in step with that**.  The render pass calls :meth:`AudioEmitter.updateAudio`
with the node's accumulated world matrix and the current time; the node starts
what should be playing and re-aims what already is.  Nothing here draws, and
nothing here touches the audio thread: it reads fields, works out two gains, and
writes them onto a voice.

A node with no engine, no clip or no device does nothing at all and says
nothing about it.  That is what lets a scene with sound in it run unchanged on a
machine with none.
"""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from vrml import field, node
from vrml.vrml97 import basenodes, nodetypes

from OpenGLContext.audio import model, spatial

#: A glTF emitter faces its own ``-Z``, as glTF cameras and
#: ``KHR_lights_punctual`` do.
FORWARD = np.array([0.0, 0.0, -1.0, 0.0])

#: How a generated settings page presents the distance models.
DISTANCE_MODELS = tuple(entry.value for entry in spatial.DistanceModel)
SHAPE_TYPES = tuple(entry.value for entry in spatial.ShapeType)


def point_to_world(point: Sequence[float], matrix: Any) -> np.ndarray:
    """A point in a node's own frame, in world coordinates."""
    homogeneous = np.array([point[0], point[1], point[2], 1.0])
    return np.asarray(np.dot(homogeneous, matrix))[:3]


def direction_to_world(direction: Sequence[float], matrix: Any) -> np.ndarray:
    """A direction in a node's own frame, in world coordinates.

    The fourth component is zero, so the transform's translation is ignored --
    a direction has no position to move.
    """
    homogeneous = np.array([direction[0], direction[1], direction[2], 0.0])
    return np.asarray(np.dot(homogeneous, matrix))[:3]


def pose_from_matrix(matrix: Any) -> Tuple[np.ndarray, np.ndarray]:
    """A node's world position and forward axis, from its accumulated matrix."""
    return np.asarray(matrix)[3, :3].copy(), np.asarray(np.dot(FORWARD, matrix))[:3]


class AudioSource(node.Node):
    """One sound and the settings it is played with.

    The fields are ``KHR_audio_emitter``'s, by name, so a source authored in
    Blender or Godot and one written by hand in VRML mean the same thing.
    ``url`` is a list because a scene may offer the same sound in several
    formats; the first that decodes wins, which is how the glTF codec extensions
    (``OMI_audio_ogg_vorbis``, ``OMI_audio_opus``) are meant to be read.
    """

    PROTO = 'AudioSource'

    #: Where the sound is, most-preferred first.
    url = field.newField('url', 'MFString', 1, list)
    #: Linear multiplier on the file's own level; 0.5 is half amplitude.
    gain = field.newField('gain', 'SFFloat', 1, 1.0)
    #: Speed and pitch together, as speeding up a record does.
    playbackRate = field.newField('playbackRate', 'SFFloat', 1, 1.0)
    #: Whether the sound restarts when it reaches its end.
    loop = field.newField('loop', 'SFBool', 1, False)
    #: Whether the sound starts as soon as its emitter is in a live scene.
    autoplay = field.newField('autoplay', 'SFBool', 1, True)
    #: Which sounds survive when there are more than there are voices; 1.0 is
    #: the most important.  ``KHR_audio_emitter`` has no such field, so this is
    #: an addition, named as VRML97's ``Sound.priority`` is.
    priority = field.newField('priority', 'SFFloat', 1, 0.0)
    #: Seconds of quiet before a one-shot plays again; 0 means it plays once.
    #: The other way a sound recurs, and it is not :attr:`loop`: a distant
    #: rumble every half minute is a one-shot on a timer, and looping it would
    #: give a continuous noise where the author wrote an occasional one.  A
    #: second addition beyond ``KHR_audio_emitter``, for the same reason
    #: :attr:`priority` is: ambience wants it and the extension has nowhere to
    #: say it.  Ignored while :attr:`loop` is set -- a loop has no gaps to time.
    repeatInterval = field.newField('repeatInterval', 'SFFloat', 1, 0.0)
    #: Seconds of spread on :attr:`repeatInterval`, so that two speakers of the
    #: same sound drift apart instead of beating together for ever.  The spread
    #: is symmetric and the wait is never negative.
    repeatVariance = field.newField('repeatVariance', 'SFFloat', 1, 0.0)

    UI_HINTS = {
        'gain': {'label': 'Volume', 'minimum': 0.0, 'maximum': 2.0, 'step': 0.05},
        'playbackRate': {'label': 'Speed', 'minimum': 0.25, 'maximum': 4.0,
                         'step': 0.05},
        'loop': {'label': 'Repeat'},
        'priority': {'label': 'Priority', 'minimum': 0.0, 'maximum': 1.0,
                     'step': 0.05},
        'repeatInterval': {'label': 'Repeat every (s)', 'minimum': 0.0,
                           'maximum': 600.0, 'step': 1.0},
        'repeatVariance': {'label': 'Repeat spread (s)', 'minimum': 0.0,
                           'maximum': 120.0, 'step': 1.0},
    }

    def __init__(self, **named: Any) -> None:
        super(AudioSource, self).__init__(**named)
        self._clip: Any = None
        self._resolved = False
        self._record = model.AudioSource()

    def clip(self, engine: Any) -> Any:
        """The first of :attr:`url` that decodes, or None if none does.

        Resolution walks a list and may touch a disk, so the answer is kept.  A
        url that resolves to nothing is remembered as nothing: a missing sound
        must not be looked for again every frame.
        """
        if not self._resolved:
            self._resolved = True
            for name in self.url:
                found = engine.clip(name)
                if found is not None:
                    self._clip = found
                    break
        return self._clip

    def record(self) -> model.AudioSource:
        """This node's fields as the ``KHR_audio_emitter`` record.

        Rewritten in place rather than rebuilt, so a scene full of sources
        costs no allocation per frame.
        """
        record = self._record
        record.gain = self.gain
        record.playbackRate = self.playbackRate
        record.loop = self.loop
        record.autoplay = self.autoplay
        return record


class AudioEmitter(nodetypes.Auditory, nodetypes.Children, node.Node):
    """Where sound comes from, in the scene.

    Place it under a ``Transform`` and its sounds come from there.  The fields
    are ``KHR_audio_emitter``'s, flattened: an emitter's ``positional``
    sub-object is a set of fields here rather than a nested node, because a
    settings screen and a file format both read a flat node more easily than a
    nested one, and the record :meth:`record` builds puts the nesting back.

    ``type`` is ``positional`` for a sound in the world and ``global`` for one
    that ignores the listener -- music, ambience, narration.
    """

    PROTO = 'AudioEmitter'

    #: ``positional`` (a place in the world) or ``global`` (everywhere).
    type = field.newField('type', 'SFString', 1, model.POSITIONAL)
    #: Linear multiplier on every source this emitter plays.
    gain = field.newField('gain', 'SFFloat', 1, 1.0)
    #: The sounds this emitter plays.
    sources = field.newField('sources', 'MFNode', 1, list)
    #: ``omnidirectional`` or ``cone``.
    shapeType = field.newField('shapeType', 'SFString', 1,
                               spatial.ShapeType.OMNIDIRECTIONAL.value)
    #: Angular diameter of the cone inside which nothing is attenuated.
    coneInnerAngle = field.newField('coneInnerAngle', 'SFFloat', 1, spatial.TAU)
    #: Angular diameter of the cone outside which ``coneOuterGain`` applies.
    coneOuterAngle = field.newField('coneOuterAngle', 'SFFloat', 1, spatial.TAU)
    #: Level outside the outer cone; 0 is silent behind the emitter.
    coneOuterGain = field.newField('coneOuterGain', 'SFFloat', 1, 0.0)
    #: ``inverse``, ``linear`` or ``exponential``.
    distanceModel = field.newField('distanceModel', 'SFString', 1,
                                   spatial.DistanceModel.INVERSE.value)
    #: Where the falloff stops; 0 means it never does.
    maxDistance = field.newField('maxDistance', 'SFFloat', 1, 0.0)
    #: Inside this, the emitter is at full level.
    refDistance = field.newField('refDistance', 'SFFloat', 1, 1.0)
    #: How sharply the level falls beyond ``refDistance``.
    rolloffFactor = field.newField('rolloffFactor', 'SFFloat', 1, 1.0)

    UI_HINTS = {
        'gain': {'label': 'Volume', 'minimum': 0.0, 'maximum': 2.0, 'step': 0.05},
        'type': {'label': 'Placement', 'options': (model.POSITIONAL, model.GLOBAL),
                 'optionLabels': ('In the world', 'Everywhere')},
        'shapeType': {'label': 'Shape', 'options': SHAPE_TYPES,
                      'optionLabels': ('All directions', 'Cone')},
        'distanceModel': {'label': 'Falloff', 'options': DISTANCE_MODELS,
                          'optionLabels': ('Linear', 'Inverse', 'Exponential')},
        'refDistance': {'label': 'Full-volume radius', 'minimum': 0.1,
                        'maximum': 100.0, 'step': 0.1},
        'maxDistance': {'label': 'Cut-off distance', 'minimum': 0.0,
                        'maximum': 1000.0, 'step': 1.0},
        'rolloffFactor': {'label': 'Falloff sharpness', 'minimum': 0.0,
                          'maximum': 10.0, 'step': 0.1},
    }

    #: The fields that make up the record's ``positional`` sub-object.
    POSITIONAL_FIELDS = ('shapeType', 'coneInnerAngle', 'coneOuterAngle',
                          'coneOuterGain', 'distanceModel', 'maxDistance',
                          'refDistance', 'rolloffFactor')

    def __init__(self, **named: Any) -> None:
        super(AudioEmitter, self).__init__(**named)
        self._record = model.AudioEmitter()
        self._playing: Dict[int, Any] = {}
        #: When each finished one-shot may sound again, by source, for the
        #: sources that have a :attr:`AudioSource.repeatInterval`.
        self._repeats: Dict[int, float] = {}
        # Ambient timing is presentation and not simulation -- nothing reads a
        # repeat back -- so an ordinary generator is enough, and one per
        # emitter keeps two speakers of the same clip from drifting together.
        self._jitter = random.Random()

    def record(self) -> model.AudioEmitter:
        """This node's fields as the ``KHR_audio_emitter`` record.

        Rewritten in place, so following a scene's emitters every frame costs
        no allocation.
        """
        record = self._record
        record.type = self.type
        record.gain = self.gain
        if not record.positional_audio:
            record.positional = None
        else:
            if record.positional is None:
                record.positional = model.PositionalProperties()
            for name in self.POSITIONAL_FIELDS:
                setattr(record.positional, name, getattr(self, name))
        return record

    def updateAudio(self, engine: Any, matrix: Any, now: float = 0.0) -> None:
        """Start what should be playing, and re-aim what already is.

        Called once a frame by the render pass with this node's accumulated
        world matrix.  ``engine`` may be None -- an application with no audio
        still traverses the scene -- in which case there is nothing to do.
        """
        if engine is None:
            return
        record = self.record()
        position, forward = pose_from_matrix(matrix)
        for source in self.sources:
            self._updateSource(engine, source, record, position, forward, now)

    def repeatsAt(self, source: Any) -> Optional[float]:
        """When ``source`` next sounds, or None if it is not waiting to.

        Reported so a debug overlay and a test can see the timer; nothing in
        the playing path reads it back.
        """
        return self._repeats.get(id(source))

    def _updateSource(self, engine: Any, source: Any, record: model.AudioEmitter,
                      position: np.ndarray, forward: np.ndarray,
                      now: float = 0.0) -> None:
        """Keep one source of this emitter in step with the world."""
        handle = self._playing.get(id(source))
        if handle is not None:
            if handle.playing:
                engine.aim(handle, record, position, forward, gain=source.gain)
                return
            if not source.loop and self._stillFinished(source, now):
                return
            # Either a loop that lost its voice to stealing -- nothing else
            # ends one, so it may take another when one frees -- or a one-shot
            # whose repeat has come round.  Both start again from here.
            self._playing.pop(id(source), None)
            self._repeats.pop(id(source), None)
        if not source.autoplay:
            return
        clip = source.clip(engine)
        if clip is None:
            return
        started = engine.play(clip, emitter=record, position=position,
                              forward=forward, gain=source.gain,
                              priority=source.priority, loop=source.loop,
                              rate=source.playbackRate)
        if started is not None:
            self._playing[id(source)] = started

    def _stillFinished(self, source: Any, now: float) -> bool:
        """Whether a one-shot that has ended should stay silent.

        A one-shot with no :attr:`AudioSource.repeatInterval` stays finished
        for ever, which is the ordinary case.  One with an interval is silent
        until that interval has passed, timed from the frame its clip was
        noticed to have ended -- so a long clip and a short one leave the same
        gap of quiet, which is what an author setting a repeat means by it.
        """
        interval = float(source.repeatInterval)
        if interval <= 0.0:
            return True
        due = self._repeats.get(id(source))
        if due is None:
            self._repeats[id(source)] = now + self._wait(source, interval)
            return True
        return now < due

    def _wait(self, source: Any, interval: float) -> float:
        """One interval, moved within its spread and never negative."""
        variance = float(source.repeatVariance)
        if variance <= 0.0:
            return interval
        return max(0.0, interval + self._jitter.uniform(-variance, variance))

    def stopAudio(self) -> None:
        """Silence everything this emitter started, and forget its timers."""
        for handle in self._playing.values():
            handle.stop()
        self._playing.clear()
        self._repeats.clear()


class Sound(basenodes.Sound):
    """VRML97's ``Sound`` node, rendered through the audio engine.

    Its geometry is not the glTF one and cannot be expressed as one: two
    ellipsoids sharing a focus at ``location``, with a ramp between them that is
    linear in decibels.  So it works out its own level with
    :func:`~OpenGLContext.audio.spatial.ellipsoid_gain` and hands the engine a
    finished number to pan, which is the one thing the two models share.

    Of VRML97's time-dependent behaviour it honours what can be seen from
    outside: ``startTime`` and ``stopTime`` bound when the clip sounds,
    ``loop`` repeats it, ``pitch`` sets the playback rate, and ``isActive`` and
    ``duration_changed`` are sent.  Fractional seeking into a clip that started
    before the scene did is not implemented; a clip whose ``startTime`` has
    passed begins at its start.

    Reference:
        ISO/IEC 14772-1:1997 (VRML97) 6.42 ``Sound``, 6.2 ``AudioClip``
        https://www.web3d.org/documents/specifications/14772/V2.0/part1/nodesRef.html#Sound
    """

    def __init__(self, **named: Any) -> None:
        super(Sound, self).__init__(**named)
        self._handle: Any = None
        self._clip: Any = None
        self._resolved = False
        # `isActive` is an eventOut: it has no value until something sends one,
        # so reading it back to find out what we last said is an error.  The
        # node remembers what it sent instead.
        self._active = False

    def updateAudio(self, engine: Any, matrix: Any, now: float = 0.0) -> None:
        """Start, aim or stop this sound for the frame at ``now``."""
        if engine is None:
            return
        source = self.source
        if not isinstance(source, basenodes.AudioClip):
            return
        location = point_to_world(self.location, matrix)
        direction = direction_to_world(self.direction, matrix)
        level = self.intensity * self._ellipsoidGain(engine, location, direction)
        if not self._scheduled(source, now):
            self._stop(source)
            return
        if self._handle is not None and self._handle.playing:
            left, right = _pan(engine, location, level, self.spatialize)
            self._handle.set_gain(left, right)
            return
        if self._handle is not None:
            self._stop(source)
            return
        self._start(engine, source, location, level)

    def stopAudio(self) -> None:
        """Silence this sound."""
        source = self.source
        self._stop(source if isinstance(source, basenodes.AudioClip) else None)

    def _ellipsoidGain(self, engine: Any, location: np.ndarray,
                       direction: np.ndarray) -> float:
        """How loud this sound is at the listener, by VRML97's own geometry."""
        listener = engine.listener
        offset = listener.position - location
        distance = float(np.linalg.norm(offset))
        length = float(np.linalg.norm(direction))
        cos_theta = 1.0
        if distance > 0.0 and length > 0.0:
            cos_theta = float(np.dot(direction / length, offset / distance))
        return spatial.ellipsoid_gain(
            distance, cos_theta, min_front=self.minFront, min_back=self.minBack,
            max_front=self.maxFront, max_back=self.maxBack)

    def _scheduled(self, source: Any, now: float) -> bool:
        """Whether the clip's ``startTime``/``stopTime`` allow it to sound.

        ``stopTime`` at or before ``startTime`` means "no stop", which is what
        VRML97's time-dependent nodes specify and what lets the default pair of
        zeroes mean "play from the beginning and never stop".
        """
        if now < source.startTime:
            return False
        return not (source.stopTime > source.startTime and now >= source.stopTime)

    def _start(self, engine: Any, source: Any, location: np.ndarray,
               level: float) -> None:
        """Resolve the clip if need be, and give it a voice."""
        if not self._resolved:
            self._resolved = True
            for name in source.url:
                found = engine.clip(name)
                if found is not None:
                    self._clip = found
                    source.duration_changed = found.duration
                    break
        if self._clip is None:
            return
        left, right = _pan(engine, location, level, self.spatialize)
        self._handle = engine.mixer.play_gains(
            self._clip, left, right, priority=self.priority,
            loop=source.loop, rate=source.pitch)
        if self._handle is not None:
            self._active = True
            source.isActive = True

    def _stop(self, source: Any) -> None:
        """Release the voice and say so, if there was one."""
        if self._handle is not None:
            self._handle.stop()
            self._handle = None
        if self._active:
            self._active = False
            if source is not None:
                source.isActive = False


def _pan(engine: Any, location: np.ndarray, level: float,
         spatialize: bool) -> Tuple[float, float]:
    """``level`` split between the ears for a sound at ``location``.

    A sound the author asked not to spatialise still fades with distance -- the
    ellipsoids and ``intensity`` are already in ``level`` -- but sits in the
    middle of the stereo field wherever it is, which is what VRML97 specifies.
    """
    if level <= 0.0:
        return 0.0, 0.0
    if not spatialize:
        centre = level * math.sqrt(0.5)
        return centre, centre
    azimuth, _ = engine.listener.azimuth_elevation(location)
    left, right = spatial.equal_power_pan(azimuth)
    return level * left, level * right


def update_scene_audio(engine: Any, paths: Sequence[Any], now: float = 0.0) -> int:
    """Drive every audible node on ``paths`` for one frame.

    ``paths`` are the render pass's collected
    :class:`~vrml.vrml97.nodetypes.Auditory` node paths; each knows its own
    accumulated transform, which is the world pose its node needs and the only
    thing the pass has that the node does not.

    Returns how many nodes were updated, which is what a debug overlay shows.
    """
    if engine is None:
        return 0
    updated = 0
    for path in paths:
        update = getattr(path[-1], 'updateAudio', None)
        if update is None:
            continue
        update(engine, path.transformMatrix(), now)
        updated += 1
    return updated


def stop_scene_audio(paths: Sequence[Any]) -> None:
    """Silence every audible node on ``paths``; used when a scene goes away."""
    for path in paths:
        stop = getattr(path[-1], 'stopAudio', None)
        if stop is not None:
            stop()


def emitters_from_document(document: model.AudioDocument,
                           indices: Optional[Sequence[int]] = None,
                           resolve: Optional[Callable[[str], str]] = None
                           ) -> List[AudioEmitter]:
    """Scenegraph nodes for the emitters a parsed glTF document declares.

    ``indices`` selects which of the document's emitters to build -- a glTF node
    or scene names the ones it carries -- and defaults to all of them.  An index
    that names no emitter is skipped rather than raising: content is not always
    well formed, and a bad index should cost a sound, not a scene.

    ``resolve`` turns an audio ``uri`` into something openable.  The extension
    states that a uri is relative to the document, and only the loader knows
    where that was, so the loader supplies this.
    """
    if indices is None:
        indices = range(len(document.emitters))
    nodes = []
    for index in indices:
        if not (0 <= index < len(document.emitters)):
            continue
        emitter = document.emitters[index]
        sources = []
        for source in document.sources_for(emitter):
            audio = document.audio_for(source)
            if audio is None or not audio.uri:
                continue
            uri = resolve(audio.uri) if resolve is not None else audio.uri
            sources.append(AudioSource(
                url=[uri], gain=source.gain, playbackRate=source.playbackRate,
                loop=source.loop, autoplay=source.autoplay))
        named: Dict[str, Any] = {'type': emitter.type, 'gain': emitter.gain,
                                 'sources': sources}
        if emitter.positional is not None:
            for name in AudioEmitter.POSITIONAL_FIELDS:
                named[name] = getattr(emitter.positional, name)
        nodes.append(AudioEmitter(**named))
    return nodes
