"""Sound in the scenegraph: glTF's emitters and sources.

Two nodes, and the split between them is the same split glTF's
``KHR_audio_emitter`` makes:

:class:`AudioSource`
    One clip and how it is played -- gain, loop, playback rate, whether it
    starts by itself.  Several emitters may share one.
:class:`AudioEmitter`
    Where the sound comes from, and how it fades with distance and direction.
    Put it under a ``Transform`` and the sound is wherever that transform is.

X3D's (and VRML97's) ``Sound`` and the rest of X3D's Sound component are
:mod:`OpenGLContext.scenegraph.x3dsound`, played through omi_audio's
processing graph.

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

import logging
import os
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np
from vrml import field, node, protofunctions
from vrml.vrml97 import nodetypes

from omi_audio import formats, model, spatial
from OpenGLContext import entropy
from OpenGLContext.loaders import resolver

log = logging.getLogger(__name__)

#: A glTF emitter faces its own ``-Z``, as glTF cameras and
#: ``KHR_lights_punctual`` do.
FORWARD = np.array([0.0, 0.0, -1.0, 0.0])

#: How often a *playing* sound's gains are worked out again, in seconds.
#:
#: Aiming turns a position into two volumes -- a distance, a cone angle, an
#: azimuth and an equal-power pan -- and a level with a few dozen emitters
#: asking for that every frame is a measurable part of the frame. What it buys
#: is a pair of numbers that move continuously and slowly: a listener walking at
#: a few metres a second changes them by a fraction over a frame.
#:
#: Fifteen a second, which is faster than a source's gain can audibly step for
#: any speed a person moves at, and slow enough that the cost stops scaling with
#: the frame rate. **Starting** a sound is not delayed by it -- a source is
#: aimed the first time it is seen -- so this never affects where a sound
#: appears to come from, only how often a sound already playing is re-asked.
AIM_INTERVAL = 1.0 / 15.0

#: How a generated settings page presents the distance models.
DISTANCE_MODELS = tuple(entry.value for entry in spatial.DistanceModel)
SHAPE_TYPES = tuple(entry.value for entry in spatial.ShapeType)


def document_resolver(node: Any) -> Optional[Any]:
    """The resolver confining ``node``'s references to its own document, if it has one.

    A node read out of a scene file may only reach what that document's own
    location permits: audio under its directory, or same-origin audio for a
    document fetched over http(s). Its ``url`` came from the file rather than
    from the application.  A node built in code has no document
    behind it and is not confined.
    """
    root = protofunctions.root(node)
    base = getattr(root, 'baseURI', None) if root is not None else None
    if not base:
        return None
    if resolver.is_url(base):
        return resolver.Resolver(base_url=base)
    return resolver.Resolver(base_dir=os.path.dirname(os.path.abspath(base)))


def clip_from_urls(node: Any, urls: Sequence[str], engine: Any) -> Any:
    """The first of ``urls`` that decodes through ``engine``, or None.

    Each entry is resolved against ``node``'s document first
    (:func:`document_resolver`), so a name the document is not allowed to
    reach is skipped rather than opened.
    """
    confine = document_resolver(node)
    for name in urls:
        if confine is not None:
            try:
                name = confine.resolve(name)
            except IOError:
                log.warning('%s url %r is outside its document; ignored',
                            type(node).__name__, name)
                continue
        found = engine.clip(name)
        if found is not None:
            return found
    return None


def point_to_world(point: Sequence[float] | np.ndarray, matrix: Any) -> np.ndarray:
    """A point in a node's own frame, in world coordinates."""
    homogeneous = np.array([point[0], point[1], point[2], 1.0])
    return np.asarray(np.dot(homogeneous, matrix))[:3]


def direction_to_world(direction: Sequence[float] | np.ndarray, matrix: Any) -> np.ndarray:
    """A direction in a node's own frame, in world coordinates.

    The fourth component is zero, so the transform's translation is ignored --
    a direction has no position to move.
    """
    homogeneous = np.array([direction[0], direction[1], direction[2], 0.0])
    return np.asarray(np.dot(homogeneous, matrix))[:3]


def pose_from_matrix(matrix: Any) -> tuple[np.ndarray, np.ndarray]:
    """A node's world position and forward axis, from its accumulated matrix."""
    return np.asarray(matrix)[3, :3].copy(), np.asarray(np.dot(FORWARD, matrix))[:3]


class AudioSource(node.Node):
    """One sound and the settings it is played with.

    The fields are ``KHR_audio_emitter``'s, by name, so a source authored in
    Blender or Godot and one written by hand in VRML mean the same thing.
    ``url`` is a list because a scene may offer the same sound in several
    formats, most preferred first, and the first that decodes wins.  That is how
    the glTF codec extensions (``OMI_audio_ogg_vorbis``, ``OMI_audio_opus``) are
    read: :func:`emitters_from_document` puts every encoding a document offers
    into ``url``, better before worse, ending with the MP3 the base extension
    guarantees.
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
        self._library: Any = None
        self._made: Any = None
        self._source: Optional[model.AudioSource] = None
        self._record = model.AudioSource()
        self._wanted = False

    def play(self) -> None:
        """Start this source from the beginning on the next frame.

        For a sound that answers an event -- a door, a crash, a turret firing --
        rather than one that starts with the scene.  It plays whether or not
        :attr:`autoplay` is set and whether or not it has played before, and a
        source that is still sounding starts again from the top, so one source
        is one voice at a time.  A sound that should overlap itself, such as
        rapid fire, is played through the engine instead.

        A request made before the clip has resolved is dropped rather than held,
        so a sound whose file is still arriving does not sound late.
        """
        self._wanted = True

    def takeRequest(self) -> bool:
        """Whether :meth:`play` was called since the last frame; clears it."""
        wanted, self._wanted = self._wanted, False
        return wanted

    def useClip(self, clip: Any) -> None:
        """Play a clip the application made, rather than one ``url`` names.

        :mod:`omi_audio.synth` builds clips out of arithmetic, and a sound a
        game *computes* -- a motor note from wheel speed, wind from road speed,
        a footstep varied so that two in a row are not the same one twice --
        has no file behind it to put in :attr:`url`.  Handing the clip over is
        the whole of it; everything after this is the path a decoded clip
        takes, so such a sound is positioned, attenuated, mixed and voiced
        exactly as any other.

        The clip arrives at the engine's own sample rate, resampled if it is
        not already there, because the mixer runs at the rate the device was
        opened at and a clip at another would play at the wrong pitch.  That is
        the same courtesy :meth:`omi_audio.clip.ClipCache.put` does a clip
        registered by name.

        Takes precedence over :attr:`url` and over a document's audio library:
        an application that hands a clip over has said which sound it means.
        """
        self._made = clip
        self._resolved = False

    def useLibrary(self, library: Any, source: model.AudioSource) -> None:
        """Take this source's clip from a glTF document's audio library.

        A document names its audio by index rather than by anything this node
        could open -- a ``bufferView`` has no name at all -- so
        :class:`omi_audio.library.AudioLibrary` holds the loader's own resolver
        and hands back samples.  Used instead of walking :attr:`url`, which for
        a document-backed source records where the audio is rather than how it
        is fetched.

        ``source`` is the document's own record rather than an audio index,
        because a source may name several encodings of one sound through the
        codec extensions in :mod:`omi_audio.formats`, and choosing between them
        is the library's job.
        """
        self._library = library
        self._source = source
        self._resolved = False

    def clip(self, engine: Any) -> Any:
        """The clip this source plays, or None if it will not resolve.

        Resolution may touch a disk or a network, so the answer is kept.  A
        source that resolves to nothing is remembered as nothing: a missing
        sound must not be looked for again every frame.
        """
        if not self._resolved:
            self._resolved = True
            if self._made is not None:
                self._clip = self._atEngineRate(self._made, engine)
            elif self._library is not None:
                self._clip = self._fromLibrary(engine)
            else:
                self._clip = self._fromUrl(engine)
        return self._clip

    @staticmethod
    def _atEngineRate(clip: Any, engine: Any) -> Any:
        """``clip`` at the rate the mixer runs at, resampled if it is not."""
        rate = engine.clips.sample_rate
        return clip if clip.sample_rate == rate else clip.resampled(rate)

    def _fromLibrary(self, engine: Any) -> Any:
        """The clip the document's own audio library resolves for this source."""
        # The library is built while the document loads, before there is an
        # engine to ask, and the engine's clip cache is what fixes the rate
        # everything is decoded and mixed at.  Hand it over once one exists.
        self._library.cache = engine.clips
        return self._library.clip_for(self._source)

    def _fromUrl(self, engine: Any) -> Any:
        """The first of :attr:`url` that decodes; see :func:`clip_from_urls`."""
        return clip_from_urls(self, self.url, engine)

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

    #: How much of the emitter the zones let through, from 0 to 1: the share
    #: of the zones naming it that the listener is in, set each frame by
    #: :func:`OpenGLContext.audio.areas.apply_zones`. 1 for an emitter no
    #: zone names. Not a field, since it is worked out rather than authored.
    zoneGain = 1.0

    #: The fields that make up the record's ``positional`` sub-object.
    POSITIONAL_FIELDS = ('shapeType', 'coneInnerAngle', 'coneOuterAngle',
                          'coneOuterGain', 'distanceModel', 'maxDistance',
                          'refDistance', 'rolloffFactor')

    def __init__(self, **named: Any) -> None:
        super(AudioEmitter, self).__init__(**named)
        self._record = model.AudioEmitter()
        #: The engine's handle for each source this emitter started.
        self._playing: dict[AudioSource, Any] = {}
        #: When each finished one-shot may sound again, by source, for the
        #: sources that have a :attr:`AudioSource.repeatInterval`.
        self._repeats: dict[AudioSource, float] = {}
        # Ambient timing is presentation and not simulation -- nothing reads a
        # repeat back -- so the session's own stream is enough. Emitters draw
        # from it in turn rather than each from the same place, which is what
        # keeps two speakers of one clip from drifting together, and it means a
        # recorded session repeats the same ambience it had.
        self._jitter = entropy.randomizer('audio-jitter')
        #: When each playing source was last re-aimed, by source.  See
        #: :data:`AIM_INTERVAL`.
        self._aimed: dict[AudioSource, float] = {}
        #: How far through its first aiming interval this emitter starts, so a
        #: level's worth of them do not all re-aim on the same frame and turn a
        #: saving into a stutter every few frames.  Drawn from the session's own
        #: stream like the ambient timing above, so a recorded session repeats.
        self._aimPhase = self._jitter.random() * AIM_INTERVAL

    def record(self) -> model.AudioEmitter:
        """This node's fields as the ``KHR_audio_emitter`` record.

        Rewritten in place, so following a scene's emitters every frame costs
        no allocation.
        """
        record = self._record
        record.type = self.type
        record.gain = self.gain * self.zoneGain
        if not record.positional_audio:
            record.positional = None
        else:
            if record.positional is None:
                record.positional = model.PositionalProperties()
            for name in self.POSITIONAL_FIELDS:
                setattr(record.positional, name, getattr(self, name))
        return record

    def play(self) -> None:
        """Start every source from the beginning on the next frame.

        :meth:`AudioSource.play` for each of :attr:`sources`: the call for a
        sound found by name, such as ``scene.sounds['door']`` from a glTF
        document, whose emitter usually holds one source.
        """
        for source in self.sources:
            source.play()

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

    def _dueToAim(self, source: Any, now: float) -> bool:
        """Whether a playing source's gains should be worked out again now.

        Aiming is two gains from a distance, a cone angle and an azimuth, and a
        level's worth of emitters asking for them every frame is a measurable
        part of the frame -- for an answer that is a pair of volumes, changing
        continuously and slowly.  See :data:`AIM_INTERVAL` for why the interval
        is the size it is.

        A source is always aimed the first time it is seen, so a sound that has
        just started is placed before it is heard rather than up to an interval
        later.
        """
        last = self._aimed.get(source)
        if last is None:
            self._aimed[source] = now + self._aimPhase
            return True
        if now - last < AIM_INTERVAL:
            return False
        self._aimed[source] = now
        return True

    def repeatsAt(self, source: Any) -> Optional[float]:
        """When ``source`` next sounds, or None if it is not waiting to.

        Reported so a debug overlay and a test can see the timer; nothing in
        the playing path reads it back.
        """
        return self._repeats.get(source)

    def _updateSource(self, engine: Any, source: Any, record: model.AudioEmitter,
                      position: np.ndarray, forward: np.ndarray,
                      now: float = 0.0) -> None:
        """Keep one source of this emitter in step with the world."""
        handle = self._playing.get(source)
        wanted = source.takeRequest()
        if handle is not None and wanted:
            handle.stop()
            self._forget(source)
        elif handle is not None:
            if handle.playing:
                # Every frame rather than at the aim interval: it is one float,
                # and a pitch that moved fifteen times a second would step.
                handle.set_rate(source.playbackRate)
                if self._dueToAim(source, now):
                    engine.aim(handle, record, position, forward,
                               gain=source.gain)
                return
            if not source.loop and self._stillFinished(source, now):
                return
            # Either a loop that lost its voice to stealing -- nothing else
            # ends one, so it may take another when one frees -- or a one-shot
            # whose repeat has come round.  Both start again from here.
            self._forget(source)
        if not (source.autoplay or wanted):
            return
        clip = source.clip(engine)
        if clip is None:
            return
        started = engine.play(clip, emitter=record, position=position,
                              forward=forward, gain=source.gain,
                              priority=source.priority, loop=source.loop,
                              rate=source.playbackRate)
        if started is not None:
            self._playing[source] = started

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
        due = self._repeats.get(source)
        if due is None:
            self._repeats[source] = now + self._wait(source, interval)
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
        self._aimed.clear()

    def _forget(self, source: AudioSource) -> None:
        """Drop what this emitter holds for a source it is about to start again."""
        self._playing.pop(source, None)
        self._repeats.pop(source, None)
        self._aimed.pop(source, None)


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


def audio_location(audio: model.Audio,
                   resolve: Optional[Callable[[str], str]] = None) -> list[str]:
    """Where a piece of a document's audio is, as something a reader can act on.

    Empty where there is no location to give: a ``bufferView`` lives inside the
    document, and a ``data:`` URI *is* the content rather than a place to find
    it.  Empty too where ``resolve`` refuses the reference -- a uri pointing
    outside what the document may reach costs the sound, not the scene.
    """
    if not audio.uri or audio.uri.startswith('data:'):
        return []
    if resolve is None:
        return [audio.uri]
    try:
        return [resolve(audio.uri)]
    except (OSError, ValueError) as error:
        log.warning('audio %r is not a reference this document may make: %s',
                    audio.uri, error)
        return []


def emitters_from_document(document: model.AudioDocument,
                           emitters: Optional[Sequence[model.AudioEmitter]] = None,
                           library: Optional[Any] = None,
                           resolve: Optional[Callable[[str], str]] = None
                           ) -> list[AudioEmitter]:
    """Scenegraph nodes for emitters a parsed glTF document declares.

    ``emitters`` is what a glTF node or scene names, already resolved --
    :meth:`~omi_audio.model.AudioDocument.emitters_for_node` and
    :meth:`~omi_audio.model.AudioDocument.emitters_for_scene` turn a reference
    into records, skip an index that points at nothing, and enforce the rule
    that a scene carries only global emitters.  Defaults to every emitter the
    document declares.

    ``library`` is where a source's samples come from.  A document names its
    audio by index, and :class:`omi_audio.library.AudioLibrary` is what turns
    one into a clip using the loader's own resolver -- so audio embedded in the
    document plays exactly as audio beside it does.  Without one, sources fall
    back to opening :attr:`AudioSource.url`, which embedded audio does not have.

    ``resolve`` turns an audio ``uri`` into the absolute one to record in
    :attr:`AudioSource.url`.  The extension states that a uri is relative to the
    document, and only the loader knows where that was.

    Where a source offers its sound in several encodings -- the glTF codec
    extensions, :mod:`omi_audio.formats` -- every one of them is recorded in
    :attr:`AudioSource.url`, best first, including any this build cannot decode:
    ``url`` says where the sound is, and the node already takes the first entry
    that decodes.  Which one is actually *fetched* is the library's decision,
    and it asks only for codecs it can read.
    """
    if emitters is None:
        emitters = document.emitters
    nodes = []
    for emitter in emitters:
        sources = []
        for source in document.sources_for(emitter):
            options = document.audio_options(source, formats.ENCODINGS)
            if not options:
                continue
            built = AudioSource(
                url=[url for audio in options
                     for url in audio_location(audio, resolve)],
                gain=source.gain, playbackRate=source.playbackRate,
                loop=source.loop, autoplay=source.autoplay)
            if library is not None:
                built.useLibrary(library, source)
            sources.append(built)
        named: dict[str, Any] = {'type': emitter.type, 'gain': emitter.gain,
                                 'sources': sources}
        if emitter.positional is not None:
            for name in AudioEmitter.POSITIONAL_FIELDS:
                named[name] = getattr(emitter.positional, name)
        nodes.append(AudioEmitter(**named))
    return nodes
