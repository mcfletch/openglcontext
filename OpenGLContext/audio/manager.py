"""Playing a sound with a call: ``audio.play('thud.ogg', at=hit.point)``.

:class:`Audio` is the call-shaped route to :mod:`omi_audio` beside the scene
nodes. It holds no GL and imports no context, so a game's logic and its tests
use it without a window. A context makes one and exposes it as ``context.audio``.

The thread rule
    :class:`~omi_audio.engine.AudioEngine` is single-threaded. The thread that
    made the :class:`Audio` is the render thread (:meth:`Audio.bind` names
    another). :meth:`Audio.play` called there starts the engine voice in the
    call. Called from any other thread it returns a :class:`Voice` at once and
    queues the start in an :class:`~OpenGLContext.events.handoff.Inbox`;
    :meth:`Audio.frame`, called once a frame on the render thread, drains it.
    A sound started from a physics callback is at most one frame late.

Silence
    Sound switched off in the settings, a device that fails to open and a
    clip that does not decode each give an inert voice and one logged
    warning. A missing ``miniaudio`` gives an engine on a silent device, whose
    voices play to nothing. No call raises for want of sound.
"""
from __future__ import annotations

import enum
import logging
import os
import threading
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple

import numpy as np
from omi_audio import model
from omi_audio.clip import Clip, DecodeError, decode_bytes
from omi_audio.device import describe as describe_device
from omi_audio.device import open_device
from omi_audio.engine import DEFAULT_FORWARD, AudioEngine
from omi_audio.mixer import VoiceHandle
from omi_audio.spatial import ViewPlatform

from OpenGLContext.audio.settings import AudioSettings, settings_for
from OpenGLContext.events.handoff import Inbox
from OpenGLContext.loaders import resolver

__all__ = ['Audio', 'Point', 'SoundSource', 'Voice']

log = logging.getLogger(__name__)

#: A path or URL as text or as a path object, a name given to :meth:`Audio.load`,
#: or a decoded :class:`~omi_audio.clip.Clip`.
SoundSource = Clip | str | os.PathLike[str]

#: A world position as three numbers.
Point = tuple[float, float, float]

#: Where a scene node is: its world position, or None where it has none yet.
Placement = Callable[[Any], Sequence[float] | None]

#: What a centred sound gives each ear, the equal-power split of one.
_CENTRE = float(np.sqrt(0.5))

_DEFAULT_EMITTER = model.AudioEmitter()


class _Command(NamedTuple):
    """A request queued for the render thread: ``start``, ``apply`` or ``stop``."""

    kind: str
    voice: Voice
    handle: VoiceHandle | None = None


class _State(enum.Enum):
    PENDING = 'pending'
    LIVE = 'live'
    ENDED = 'ended'


class Voice:
    """One sound started with :meth:`Audio.play`.

    ``gain`` multiplies the sound's own level and its distance attenuation;
    ``rate`` is the playback speed, pitch included, as 1.0 for the clip's own.
    Both can be set from any thread: on the render thread they take effect
    in the call, elsewhere at the next :meth:`Audio.frame`. A voice that never
    started, whose clip ended or that was stopped is not :attr:`playing`, and
    setting it does nothing.
    """

    def __init__(self, audio: Audio, source: SoundSource, *, gain: float, rate: float,
                 priority: float, loop: bool, emitter: model.AudioEmitter | None,
                 track: Callable[[], Point | None] | None) -> None:
        self._audio = audio
        self._source = source
        self._priority = priority
        self._loop = loop
        self._emitter = emitter
        self._track = track
        self._place: Point | None = None
        self._lock = threading.Lock()
        self._state = _State.PENDING
        self._handle: VoiceHandle | None = None
        self._gain = float(gain)
        self._rate = float(rate)
        self._revision = 0

    @classmethod
    def inert(cls, audio: Audio, source: SoundSource) -> Voice:
        """A voice that never plays; every call on it does nothing."""
        voice = cls(audio, source, gain=1.0, rate=1.0, priority=0.0, loop=False,
                    emitter=None, track=None)
        voice._state = _State.ENDED
        return voice

    @classmethod
    def without_engine(cls, audio: Audio, source: SoundSource, *, gain: float, rate: float,
                       priority: float, loop: bool, emitter: model.AudioEmitter | None) -> Voice:
        """A voice that plays until stopped, with no engine behind it."""
        voice = cls(audio, source, gain=gain, rate=rate, priority=priority, loop=loop,
                    emitter=emitter, track=None)
        voice._state = _State.LIVE
        return voice

    def __repr__(self) -> str:
        return '<Voice %s%s>' % (self._state.value, ' playing' if self.playing else '')

    @property
    def playing(self) -> bool:
        """Whether the sound is sounding, or is queued to start."""
        state = self._state
        if state is _State.PENDING:
            return True
        if state is _State.ENDED:
            return False
        handle = self._handle
        return handle is None or handle.playing

    @property
    def gain(self) -> float:
        """This voice's level, 1.0 as played."""
        return self._gain

    @gain.setter
    def gain(self, value: float) -> None:
        with self._lock:
            self._gain = float(value)
            self._revision += 1
        self._audio._voice_changed(self)

    @property
    def rate(self) -> float:
        """Playback speed, 1.0 as recorded."""
        return self._rate

    @rate.setter
    def rate(self, value: float) -> None:
        with self._lock:
            self._rate = float(value)
            self._revision += 1
        self._audio._voice_changed(self)

    def stop(self) -> None:
        """Silence the sound, or cancel it if it has not started yet."""
        with self._lock:
            if self._state is _State.ENDED:
                return
            self._state = _State.ENDED
            handle = self._handle
        self._audio._voice_stopped(self, handle)

    def _end(self) -> None:
        """Mark the voice over where the engine did not start it."""
        with self._lock:
            self._state = _State.ENDED


def _point(value: Any) -> Point | None:
    """``value`` as three finite-or-not floats, or None where it is not a point."""
    try:
        numbers = np.asarray(value, dtype='d').reshape(-1)
    except (TypeError, ValueError):
        return None
    if numbers.size < 3:
        return None
    return (float(numbers[0]), float(numbers[1]), float(numbers[2]))


def _camera(owner: Any) -> ViewPlatform | None:
    """The owner's camera, however it exposes one."""
    getter = getattr(owner, 'getViewPlatform', None)
    if getter is not None:
        found: ViewPlatform | None = getter()
        return found
    found = getattr(owner, 'platform', None)
    return found


class Audio:
    """Sounds played by call, for one owner (normally a context).

    ``owner`` supplies the player's settings (``contextDefinition.audio``) and
    the camera the listener follows, and with the default ``engine_factory`` the
    engine the scene nodes already share. ``engine_factory`` makes the
    :class:`~omi_audio.engine.AudioEngine` on the first play; it may return None
    for no sound. ``settings`` overrides the owner's. ``follow`` turns a scene
    node passed as ``at=`` into a world position each frame. ``render_thread``
    is the identity of the thread that frames the audio and starts the engine;
    None names the thread that makes the object.
    """

    def __init__(self, owner: Any = None, *,
                 engine_factory: Callable[[], AudioEngine | None] | None = None,
                 settings: AudioSettings | None = None,
                 follow: Placement | None = None,
                 render_thread: int | None = None) -> None:
        self._owner = owner
        self._factory = engine_factory
        self._explicit_settings = settings
        self._own_settings = AudioSettings()
        #: The placement callable for scene nodes passed as ``at=``.
        self.follow = follow
        #: The view platform the sounds are heard from; None for the owner's camera.
        self.listener: ViewPlatform | None = None
        self._render_thread = threading.get_ident() if render_thread is None else render_thread
        self._inbox = Inbox()
        self._engine: AudioEngine | None = None
        self._engine_failed = False
        self._closed = False
        self._clips: dict[str, Clip] = {}
        self._failed: set[str] = set()
        self._warned: set[str] = set()
        self._warn_lock = threading.Lock()
        self._tracked: list[Voice] = []
        self._muffle: float | None = None
        self._muffle_pending = False
        self._mix: float | None = None
        self._mix_pending = False
        #: Names given to :meth:`add` that the engine's clip cache does not hold yet.
        self._unpublished: set[str] = set()

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def bind(self) -> None:
        """Make the calling thread the render thread."""
        self._render_thread = threading.get_ident()

    def _on_render_thread(self) -> bool:
        return threading.get_ident() == self._render_thread

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _settings(self) -> AudioSettings:
        if self._explicit_settings is not None:
            return self._explicit_settings
        if self._owner is not None:
            return settings_for(self._owner)
        return self._own_settings

    @property
    def enabled(self) -> bool:
        """Whether sounds play: the player's switch is on and the audio is open."""
        return not self._closed and bool(self._settings().enabled)

    @property
    def volume(self) -> float:
        """The player's volume from 0 to 1, as the audio settings hold it."""
        return float(self._settings().volume)

    @volume.setter
    def volume(self, value: float) -> None:
        self._settings().volume = float(value)
        self._setting_changed('volume', float(value))
        if self._engine is not None and self._on_render_thread():
            self._engine.volume = self.volume

    @property
    def muffle(self) -> float:
        """How low-passed the whole mix is: 0 clear, 1 underwater."""
        if self._engine is not None:
            return float(self._engine.muffle)
        return self._muffle if self._muffle is not None else 0.0

    @muffle.setter
    def muffle(self, value: float) -> None:
        self._muffle = float(value)
        self._setting_changed('muffle', self._muffle)
        if self._engine is not None and self._on_render_thread():
            self._engine.muffle = self._muffle
        else:
            self._muffle_pending = True

    @property
    def mix(self) -> float:
        """The application's level for its whole mix, 1.0 as recorded.

        It multiplies the player's :attr:`volume`, which stays the player's
        own: a demo that plays quietly sets this, and the settings screen still
        moves the volume over it.
        """
        if self._engine is not None:
            return float(self._engine.master_gain)
        return self._mix if self._mix is not None else 1.0

    @mix.setter
    def mix(self, value: float) -> None:
        if not float(value) >= 0.0:
            raise ValueError('mix is a gain of zero or more, not %r' % (value,))
        self._mix = float(value)
        self._setting_changed('mix', self._mix)
        if self._engine is not None and self._on_render_thread():
            self._engine.master_gain = self._mix
        else:
            self._mix_pending = True

    # ------------------------------------------------------------------
    # What is playing
    # ------------------------------------------------------------------

    @property
    def silent(self) -> bool:
        """Whether nothing can be heard: sound switched off, no engine open, or a silent device."""
        engine = self._engine
        return not self.enabled or engine is None or bool(engine.silent)

    @property
    def level(self) -> float:
        """The loudest voice's level as it reaches the output, from 0 to 1.

        The voice's gain after distance and direction, times the mix and the
        volume; 0 with no engine or no voice playing. Render thread only.
        """
        engine = self._engine
        if engine is None:
            return 0.0
        loudest = max((voice.audibility for voice in engine.mixer.voices if voice.active),
                      default=0.0)
        return float(engine.master_gain * engine.volume * loudest)

    def describe(self) -> str:
        """One line naming the output, the voices playing and the levels, for a log or an overlay."""
        if not self.enabled:
            return 'audio: off'
        engine = self._engine
        if engine is None:
            return 'audio: not open'
        return '%s | voices %d | volume %.2f | mix %.2f | muffle %.2f' % (
            describe_device(engine.device), engine.active_voices, engine.volume,
            engine.master_gain, engine.muffle)

    # ------------------------------------------------------------------
    # The engine
    # ------------------------------------------------------------------

    @property
    def engine(self) -> AudioEngine | None:
        """The engine, opened by the first ask; None where there is no sound.

        The engine is not thread-safe. Use it on the render thread only.
        """
        return self._open_engine()

    def _make_engine(self) -> AudioEngine | None:
        if self._factory is not None:
            return self._factory()
        if self._owner is not None:
            from OpenGLContext.audio import scene
            return scene.engine_for(self._owner)
        return AudioEngine(device=open_device(), voices=int(self._settings().voices))

    def _open_engine(self) -> AudioEngine | None:
        if self._engine is not None:
            return self._engine
        if self._engine_failed or not self.enabled:
            return None
        try:
            engine = self._make_engine()
        except Exception as error:
            self._engine_failed = True
            self._warn_once('engine', 'no sound: the audio engine did not start (%s)', error)
            return None
        if engine is None:
            return None
        engine.volume = self.volume
        if self._muffle is not None:
            engine.muffle = self._muffle
        self._muffle_pending = False
        if self._mix is not None:
            engine.master_gain = self._mix
        self._mix_pending = False
        self._engine = engine
        self._publish(engine)
        return engine

    def _warn_once(self, key: str, message: str, *arguments: Any) -> None:
        with self._warn_lock:
            if key in self._warned:
                return
            self._warned.add(key)
        log.warning(message, *arguments)

    # ------------------------------------------------------------------
    # Clips
    # ------------------------------------------------------------------

    def load(self, name: str, path: str | os.PathLike[str]) -> None:
        """Decode ``path`` now and make it playable as ``name``.

        ``path`` is a file or an http(s) URL. Safe from any thread, so a loader
        can decode ahead; a file that does not decode logs one warning and
        leaves ``name`` unplayable. Does nothing while sound is switched off.
        """
        if not self.enabled:
            return
        self._failed.discard(name)
        clip = self._decode(os.fspath(path), name)
        if clip is not None:
            self._clips[name] = clip

    def add(self, name: str, clip: Clip) -> None:
        """Make ``clip`` playable as ``name``, by :meth:`play` and by the scene's sources.

        An ``AudioSource`` node whose url is ``name`` plays it, so a scene can
        name a sound made in code (:mod:`OpenGLContext.audio.sounds`). The
        engine opens here, so the clip is in its cache before the scene first
        asks. Safe from any thread; from another thread the engine opens and the
        clip reaches it at the next :meth:`frame`.
        """
        self._clips[name] = clip
        self._failed.discard(name)
        self._unpublished.add(name)
        if self._on_render_thread():
            engine = self._open_engine()
            if engine is not None:
                self._publish(engine)

    def _publish(self, engine: AudioEngine) -> None:
        """Put the clips given to :meth:`add` in ``engine``'s cache. Render thread only."""
        while self._unpublished:
            name = self._unpublished.pop()
            clip = self._clips.get(name)
            if clip is not None:
                engine.clips.put(name, clip)

    def _decode(self, location: str, key: str) -> Clip | None:
        """The clip at a file or URL, or None with ``key`` remembered as failed.

        Files are read through the resolver's checked paths, URLs through its
        cached fetch.
        """
        try:
            found = resolver.checked_source(location)
            if isinstance(found, resolver.CheckedURL):
                data = resolver.fetch_url(found)
            else:
                data = resolver.read_contained(found, what=location)
            return decode_bytes(data, name=location)
        except (DecodeError, OSError, ValueError) as error:
            self._failed.add(key)
            self._warn_once('clip:' + key, 'no sound for %s: %s', key, error)
            return None

    def _resolve(self, source: SoundSource, engine: AudioEngine) -> Clip | None:
        """``source`` as a clip: a loaded name, else a file or URL the engine caches."""
        if isinstance(source, Clip):
            return source
        name = os.fspath(source)
        held = self._clips.get(name)
        if held is not None:
            return held
        if name in engine.clips:
            return engine.clips.get(name)
        if name in self._failed:
            return None
        clip = self._decode(name, name)
        return engine.clips.put(name, clip) if clip is not None else None

    # ------------------------------------------------------------------
    # Playing
    # ------------------------------------------------------------------

    def play(self, source: SoundSource, at: Any = None, gain: float = 1.0,
             rate: float = 1.0, priority: float = 0.5, loop: bool = False,
             emitter: model.AudioEmitter | None = None) -> Voice:
        """Start ``source``; the voice is returned at once.

        ``source`` is a path, URL, name given to :meth:`load` or
        :class:`~omi_audio.clip.Clip`. ``at`` places the sound: None centres it,
        a world point fixes it, an object with a ``position`` attribute (a
        physics body) is followed, and any other object is a scene node placed by
        ``follow``. ``emitter`` is an :class:`~omi_audio.model.AudioEmitter` giving
        the distance and cone profile. A full voice pool drops the lowest
        ``priority`` voice, not the one that asked.

        On the render thread the engine voice starts in the call. From another
        thread it starts in the next :meth:`frame`.
        """
        if not self.enabled:
            self._warn_once('disabled', 'sound is switched off; %r is not played', source)
            return Voice.inert(self, source)
        track = self._tracker(at)
        if emitter is None and track is not None:
            emitter = _DEFAULT_EMITTER
        voice = Voice(self, source, gain=gain, rate=rate, priority=priority, loop=loop,
                      emitter=emitter, track=track)
        if self._on_render_thread():
            self._start(voice)
        else:
            self._inbox.post(_Command('start', voice))
        return voice

    def _tracker(self, at: Any) -> Callable[[], Point | None] | None:
        """How to learn where ``at`` is each frame, or None for a centred sound."""
        if at is None:
            return None
        if hasattr(at, 'position'):
            return lambda: _point(at.position)
        fixed = _point(at)
        if fixed is not None:
            return lambda: fixed
        follow = self.follow
        if follow is None:
            self._warn_once('follow', 'no placement is set for scene nodes, so %r is '
                            'played centred; pass follow= to Audio', at)
            return None
        return lambda: _point(follow(at))

    def _start(self, voice: Voice) -> None:
        """Start the engine voice. Render thread only."""
        engine = self._open_engine()
        if engine is None:
            voice._end()
            return
        with voice._lock:
            if voice._state is not _State.PENDING:
                return
            revision, gain, rate = voice._revision, voice._gain, voice._rate
        clip = self._resolve(voice._source, engine)
        if clip is None:
            voice._end()
            return
        position = self._position(voice)
        handle = engine.play(clip, emitter=voice._emitter, position=position,
                             forward=DEFAULT_FORWARD, gain=gain, priority=voice._priority,
                             loop=voice._loop, rate=rate)
        if handle is None:
            voice._end()
            return
        with voice._lock:
            if voice._state is not _State.PENDING:
                handle.stop()
                return
            voice._state = _State.LIVE
            voice._handle = handle
            changed = voice._revision != revision
        if voice._emitter is not None:
            self._tracked.append(voice)
        if changed:
            self._apply(voice)

    def _position(self, voice: Voice) -> Point | None:
        """Where ``voice`` is now: its tracker's answer, else the last answer."""
        if voice._track is not None:
            found = voice._track()
            if found is not None:
                voice._place = found
        return voice._place

    def _apply(self, voice: Voice, *, rate: bool = True) -> None:
        """Put ``voice``'s rate, gain and place on its engine voice. Render thread only."""
        handle, engine = voice._handle, self._engine
        if handle is None or engine is None or not handle.playing:
            return
        if rate:
            handle.set_rate(voice._rate)
        emitter = voice._emitter
        if emitter is None:
            level = voice._gain * _CENTRE
            handle.set_gain(level, level)
        else:
            engine.aim(handle, emitter, self._position(voice), DEFAULT_FORWARD, voice._gain)

    # ------------------------------------------------------------------
    # Voice callbacks
    # ------------------------------------------------------------------

    def _setting_changed(self, name: str, value: float) -> None:
        """Called when ``volume`` or ``muffle`` is set; for a subclass that records."""

    def _voice_changed(self, voice: Voice) -> None:
        if voice._state is not _State.LIVE:
            return
        if self._on_render_thread():
            self._apply(voice)
        else:
            self._inbox.post(_Command('apply', voice))

    def _voice_stopped(self, voice: Voice, handle: VoiceHandle | None) -> None:
        if handle is None:
            return
        if self._on_render_thread():
            handle.stop()
        else:
            self._inbox.post(_Command('stop', voice, handle))

    # ------------------------------------------------------------------
    # The frame
    # ------------------------------------------------------------------

    def frame(self) -> int:
        """Apply what other threads queued and keep the sounds in step; render thread.

        Starts queued voices, applies their gain, rate and stop changes,
        sets the engine's volume from the player's setting, moves the listener to
        the camera (or :attr:`listener`) and re-aims every voice with a place.
        Call it after the scene's own audio update, which also sets the listener
        from the camera. Returns how many queued commands it applied.
        """
        commands = self._inbox.drain()
        if self._closed:
            return 0
        for command in commands:
            if command.kind == 'start':
                self._start(command.voice)
            elif command.kind == 'apply':
                self._apply(command.voice)
            elif command.handle is not None:
                command.handle.stop()
        engine = self._engine
        if engine is None and self._unpublished:
            engine = self._open_engine()
        if engine is None:
            return len(commands)
        if not self.enabled:
            self._silence(engine)
            return len(commands)
        engine.volume = self.volume
        if self._muffle_pending and self._muffle is not None:
            engine.muffle = self._muffle
            self._muffle_pending = False
        if self._mix_pending and self._mix is not None:
            engine.master_gain = self._mix
            self._mix_pending = False
        self._publish(engine)
        platform = self.listener if self.listener is not None else _camera(self._owner)
        if platform is not None:
            engine.listen(platform)
        self._tracked = [voice for voice in self._tracked if voice.playing]
        for voice in self._tracked:
            self._apply(voice, rate=False)
        return len(commands)

    def _silence(self, engine: AudioEngine) -> None:
        """Stop everything this audio started."""
        engine.stop_all()
        self._tracked = []

    def close(self) -> None:
        """Stop every voice and release the engine. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        for command in self._inbox.drain():
            command.voice._end()
        for voice in self._tracked:
            voice._end()
        self._tracked = []
        engine, self._engine = self._engine, None
        if engine is not None:
            engine.stop_all()
        if self._owner is not None and self._factory is None:
            from OpenGLContext.audio import scene
            scene.close(self._owner)
        elif engine is not None:
            engine.close()
