"""An :class:`~OpenGLContext.audio.manager.Audio` that plays nothing and records the calls.

A game's tests assert on sounds with it: hand it to the code under test in
place of ``context.audio``, run the code, and ask what was played. It opens no
device and has no engine, so nothing in a test run depends on a sound card.
Every method is safe from any thread and records at once, with no
:meth:`~OpenGLContext.audio.manager.Audio.frame` between the call and its record.

.. code-block:: python

    audio = RecordingAudio()
    crate = Crate(audio)
    crate.break_open()
    [call] = audio.played('crack.ogg')
    assert call.at == crate.position
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any

from omi_audio import model
from omi_audio.clip import Clip
from omi_audio.engine import AudioEngine

from OpenGLContext.audio.manager import Audio, SoundSource, Voice

__all__ = ['Call', 'RecordingAudio']


@dataclass(frozen=True)
class Call:
    """One call made on a :class:`RecordingAudio`.

    ``kind`` is ``'play'``, ``'load'``, ``'add'``, ``'update'`` (a voice's gain
    or rate set), ``'stop'``, ``'volume'``, ``'muffle'`` or ``'mix'``. A play
    carries the arguments it was made with and its ``voice``; a load carries
    the path as ``source`` and the name as ``value``; an add carries the clip as
    ``source`` and the name as ``value``; an update carries the voice with its
    ``gain`` and ``rate`` after the change; a setting carries its new ``value``.
    """

    kind: str
    source: SoundSource | None = None
    at: Any = None
    gain: float = 1.0
    rate: float = 1.0
    priority: float = 0.5
    loop: bool = False
    emitter: model.AudioEmitter | None = None
    voice: Voice | None = None
    value: Any = None


class RecordingAudio(Audio):
    """An :class:`~OpenGLContext.audio.manager.Audio` whose calls are kept in :attr:`calls`.

    A voice it returns plays until it is stopped. A source named by
    :meth:`~OpenGLContext.audio.manager.Audio.load` and the path it was loaded
    from count as one sound for :meth:`played`.
    """

    def __init__(self, *args: Any, **named: Any) -> None:
        super().__init__(*args, **named)
        self._calls: list[Call] = []
        self._record_lock = threading.Lock()
        self._loaded_from: dict[str, str] = {}
        self._added: dict[str, Clip] = {}

    # ------------------------------------------------------------------
    # What was done
    # ------------------------------------------------------------------

    @property
    def calls(self) -> list[Call]:
        """Every call so far, oldest first, as a list of its own."""
        with self._record_lock:
            return list(self._calls)

    @property
    def plays(self) -> list[Call]:
        """The ``play`` calls so far."""
        return [call for call in self.calls if call.kind == 'play']

    def played(self, source: SoundSource | None = None) -> list[Call]:
        """The ``play`` calls for ``source``, or every play where it is None.

        A path matches the same path, whether ``str`` or ``Path``. A name from
        ``load`` matches plays of the name and of the path it was loaded from.
        A clip matches plays of that clip and of any clip with its name.
        """
        plays = self.plays
        if source is None:
            return plays
        return [call for call in plays
                if call.source is not None and self._same(call.source, source)]

    def clear(self) -> None:
        """Forget the calls so far."""
        with self._record_lock:
            self._calls.clear()

    def _same(self, recorded: SoundSource, wanted: SoundSource) -> bool:
        if recorded is wanted:
            return True
        return bool(self._names(recorded) & self._names(wanted))

    def _names(self, source: SoundSource) -> set[str]:
        """The names ``source`` goes by; a clip's own name, a path with where it was loaded."""
        if isinstance(source, Clip):
            return ({source.name} - {''}) | {
                name for name, clip in self._added.items() if clip is source}
        name = os.fspath(source)
        return {name, self._loaded_from.get(name, name)}

    def _record(self, call: Call) -> None:
        with self._record_lock:
            self._calls.append(call)

    # ------------------------------------------------------------------
    # The Audio interface
    # ------------------------------------------------------------------

    @property
    def engine(self) -> AudioEngine | None:
        """None: a recording has no engine."""
        return None

    def play(self, source: SoundSource, at: Any = None, gain: float = 1.0,
             rate: float = 1.0, priority: float = 0.5, loop: bool = False,
             emitter: model.AudioEmitter | None = None) -> Voice:
        """Record the play and return a voice that plays until stopped."""
        if self._closed:
            return Voice.inert(self, source)
        voice = Voice.without_engine(self, source, gain=gain, rate=rate, priority=priority,
                                     loop=loop, emitter=emitter)
        self._record(Call('play', source, at, gain, rate, priority, loop, emitter, voice))
        return voice

    def load(self, name: str, path: str | os.PathLike[str]) -> None:
        """Record the load; nothing is decoded."""
        self._loaded_from[name] = os.fspath(path)
        self._record(Call('load', os.fspath(path), value=name))

    def add(self, name: str, clip: Clip) -> None:
        """Record the clip and the name it is played by; no engine is opened."""
        self._added[name] = clip
        self._record(Call('add', clip, value=name))

    def _open_engine(self) -> AudioEngine | None:
        return None

    def frame(self) -> int:
        """Nothing is queued, so nothing is applied."""
        return 0

    def close(self) -> None:
        """Stop every voice and stop recording."""
        super().close()
        for call in self.plays:
            if call.voice is not None:
                call.voice.stop()

    def _setting_changed(self, name: str, value: float) -> None:
        if not self._closed:
            self._record(Call(name, value=value))

    def _voice_changed(self, voice: Voice) -> None:
        if not self._closed:
            self._record(Call('update', voice=voice, gain=voice.gain, rate=voice.rate))

    def _voice_stopped(self, voice: Voice, handle: Any) -> None:
        if not self._closed:
            self._record(Call('stop', voice=voice))
