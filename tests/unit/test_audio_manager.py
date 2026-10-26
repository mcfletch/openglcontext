"""Audio: the call-shaped route to sound, and the thread rule it keeps.

The engine is real and sits on a NullDevice, so a voice advances only when a
test mixes a block; the levels read back are what a player would hear.
"""
from __future__ import annotations

import logging
import threading
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from omi_audio import AudioEngine, model, synth
from omi_audio.device import NullDevice

from OpenGLContext.audio import manager as audiomanager
from OpenGLContext.audio import scene as audioscene
from OpenGLContext.audio.manager import Audio, Voice
from OpenGLContext.audio.settings import AudioSettings
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.loaders import resolver
from OpenGLContext.move import viewplatform

RATE = 8000
BLOCK = 256


class Factory:
    """Makes silent engines, and remembers them."""

    def __init__(self, voices: int = 16) -> None:
        self.voices = voices
        self.engines: list[AudioEngine] = []

    def __call__(self) -> AudioEngine:
        engine = AudioEngine(device=NullDevice(sample_rate=RATE), voices=self.voices)
        self.engines.append(engine)
        return engine

    @property
    def engine(self) -> AudioEngine:
        return self.engines[-1]


class Mover:
    """A physics body's shape: a position that changes."""

    def __init__(self, position: tuple[float, float, float]) -> None:
        self.position = position


class Context:
    """The parts of a context an Audio reads."""

    def __init__(self, **audio: Any) -> None:
        self.contextDefinition = ContextDefinition()
        if audio:
            self.contextDefinition.audio = AudioSettings(**audio)
        self.platform = viewplatform.ViewPlatform(position=(0.0, 0.0, 0.0))

    def getViewPlatform(self) -> Any:
        return self.platform


@pytest.fixture
def factory() -> Factory:
    return Factory()


@pytest.fixture
def audio(factory: Factory) -> Any:
    made = Audio(engine_factory=factory)
    yield made
    made.close()


@pytest.fixture
def tone() -> Any:
    return synth.tone(440.0, 1.0, sample_rate=RATE)


def on_thread(function: Callable[[], Any]) -> Any:
    """``function()`` run on another thread, and what it returned."""
    outcome: list[Any] = []
    failure: list[BaseException] = []

    def run() -> None:
        try:
            outcome.append(function())
        except Exception as error:
            failure.append(error)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join()
    if failure:
        raise failure[0]
    return outcome[0]


def heard(engine: AudioEngine) -> tuple[float, float]:
    """The loudest sample in each ear of the next block, after the gains settle."""
    engine.mixer.mix(BLOCK)
    block = engine.mixer.mix(BLOCK)
    return float(np.abs(block[:, 0]).max()), float(np.abs(block[:, 1]).max())


def write_wave(path: Path, seconds: float = 0.5) -> Path:
    samples = (np.sin(np.arange(int(RATE * seconds)) * 0.2) * 12000).astype('<i2')
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(samples.tobytes())
    return path


def warnings_logged(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.WARNING]


class TestRenderThread:
    def test_the_device_opens_on_the_first_play(self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        assert factory.engines == []
        audio.play(tone)
        assert len(factory.engines) == 1
        audio.close()

    def test_play_starts_the_engine_voice_in_the_call(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone)
        assert factory.engine.active_voices == 1
        assert voice.playing

    def test_one_engine_serves_every_play(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone)
        audio.play(tone)
        assert len(factory.engines) == 1
        assert factory.engine.active_voices == 2
        assert audio.engine is factory.engine

    def test_a_centred_sound_is_heard_in_both_ears_alike(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone)
        left, right = heard(factory.engine)
        assert left > 0.05
        assert left == pytest.approx(right)

    def test_gain_scales_what_is_heard(self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone, gain=1.0)
        full, _ = heard(factory.engine)
        voice.gain = 0.25
        assert voice.gain == 0.25
        quiet, _ = heard(factory.engine)
        assert quiet == pytest.approx(full * 0.25, rel=0.05)

    def test_rate_changes_how_fast_the_clip_is_consumed(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone)
        voice.rate = 2.0
        assert voice.rate == 2.0
        factory.engine.mixer.mix(BLOCK)
        handle = voice._handle
        assert handle is not None
        assert handle.elapsed == pytest.approx(2 * BLOCK / RATE, rel=0.02)

    def test_stop_silences_the_voice(self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone)
        voice.stop()
        assert not voice.playing
        assert factory.engine.active_voices == 0
        voice.stop()

    def test_a_clip_that_ends_is_no_longer_playing(
            self, audio: Audio, factory: Factory) -> None:
        voice = audio.play(synth.tone(440.0, 0.05, sample_rate=RATE))
        factory.engine.mixer.mix(BLOCK * 2)
        assert not voice.playing

    def test_a_loop_keeps_playing_past_the_clip(
            self, audio: Audio, factory: Factory) -> None:
        voice = audio.play(synth.tone(440.0, 0.05, sample_rate=RATE), loop=True)
        factory.engine.mixer.mix(BLOCK)
        assert voice.playing

    def test_priority_decides_which_voice_a_full_pool_drops(self, tone: Any) -> None:
        factory = Factory(voices=1)
        audio = Audio(engine_factory=factory)
        important = audio.play(tone, priority=0.9)
        trivial = audio.play(tone, priority=0.1)
        assert important.playing
        assert not trivial.playing
        audio.close()

    def test_a_voice_the_pool_refuses_is_inert(self, tone: Any) -> None:
        factory = Factory(voices=1)
        audio = Audio(engine_factory=factory)
        first = audio.play(tone, priority=0.9)
        refused = audio.play(tone, priority=0.1)
        refused.gain = 0.5
        refused.stop()
        assert first.playing
        audio.close()

    def test_a_voice_stolen_by_the_pool_stops_playing(self, tone: Any) -> None:
        factory = Factory(voices=1)
        audio = Audio(engine_factory=factory)
        stolen = audio.play(tone, priority=0.1)
        audio.play(tone, priority=0.9)
        assert not stolen.playing
        audio.close()


class TestOtherThreads:
    def test_play_returns_at_once_and_starts_nothing(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = on_thread(lambda: audio.play(tone))
        assert isinstance(voice, Voice)
        assert voice.playing
        assert factory.engines == []

    def test_frame_starts_the_queued_voice(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = on_thread(lambda: audio.play(tone))
        assert audio.frame() == 1
        assert factory.engine.active_voices == 1
        assert voice.playing

    def test_stop_before_the_start_cancels_it(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        def play_and_stop() -> Voice:
            voice = audio.play(tone)
            voice.stop()
            return voice

        voice = on_thread(play_and_stop)
        assert not voice.playing
        audio.frame()
        assert factory.engine.active_voices == 0
        assert not voice.playing

    def test_stop_after_the_start_is_applied_by_the_next_frame(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = on_thread(lambda: audio.play(tone))
        audio.frame()
        on_thread(voice.stop)
        assert not voice.playing
        assert factory.engine.active_voices == 1
        audio.frame()
        assert factory.engine.active_voices == 0

    def test_gain_and_rate_set_from_a_thread_are_applied_by_the_frame(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone)
        full, _ = heard(factory.engine)

        def change() -> None:
            voice.gain = 0.25
            voice.rate = 2.0

        on_thread(change)
        assert heard(factory.engine)[0] == pytest.approx(full)
        audio.frame()
        assert heard(factory.engine)[0] == pytest.approx(full * 0.25, rel=0.05)

    def test_gain_set_before_the_queued_start_is_what_starts(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        def play_quietly() -> Voice:
            voice = audio.play(tone)
            voice.gain = 0.25
            voice.rate = 1.5
            return voice

        on_thread(play_quietly)
        audio.frame()
        quiet, _ = heard(factory.engine)
        assert quiet < 0.2

    def test_many_threads_play_and_every_sound_starts(
            self, tone: Any) -> None:
        factory = Factory(voices=128)
        audio = Audio(engine_factory=factory)

        def burst() -> None:
            for _ in range(20):
                audio.play(tone, priority=0.5)

        workers = [threading.Thread(target=burst) for _ in range(5)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert audio.frame() == 100
        assert factory.engine.active_voices == 100
        audio.close()

    def test_bind_names_the_render_thread(self, factory: Factory, tone: Any) -> None:
        made = on_thread(lambda: Audio(engine_factory=factory))
        voice = made.play(tone)
        assert factory.engines == []
        made.bind()
        started = made.play(tone)
        assert factory.engine.active_voices == 1
        assert started.playing
        assert voice.playing
        made.close()

    def test_a_queued_voice_is_dropped_when_sound_is_switched_off(
            self, tone: Any) -> None:
        factory = Factory()
        context = Context()
        audio = Audio(context, engine_factory=factory)
        voice = on_thread(lambda: audio.play(tone))
        context.contextDefinition.audio.enabled = 0
        audio.frame()
        assert not voice.playing
        assert factory.engines == []
        audio.close()


class TestPlacement:
    def test_a_point_to_the_right_is_heard_on_the_right(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone, at=(6.0, 0.0, 0.0))
        left, right = heard(factory.engine)
        assert right > left * 3

    def test_a_point_to_the_left_is_heard_on_the_left(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone, at=(-6.0, 0.0, 0.0))
        left, right = heard(factory.engine)
        assert left > right * 3

    def test_a_distant_point_is_quieter_than_a_near_one(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone, at=(2.0, 0.0, 0.0))
        near = heard(factory.engine)[1]
        audio.engine.stop_all()
        audio.play(tone, at=(40.0, 0.0, 0.0))
        far = heard(factory.engine)[1]
        assert far < near / 5

    def test_a_body_is_followed_as_it_moves(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        body = Mover((6.0, 0.0, 0.0))
        audio.play(tone, at=body, loop=True)
        left, right = heard(factory.engine)
        assert right > left * 3
        body.position = (-6.0, 0.0, 0.0)
        audio.frame()
        left, right = heard(factory.engine)
        assert left > right * 3

    def test_a_scene_node_is_followed_through_the_placement_callable(
            self, factory: Factory, tone: Any) -> None:
        node = object()
        positions = {node: (6.0, 0.0, 0.0)}
        audio = Audio(engine_factory=factory, follow=positions.__getitem__)
        audio.play(tone, at=node, loop=True)
        assert heard(factory.engine)[1] > heard(factory.engine)[0] * 3
        positions[node] = (-6.0, 0.0, 0.0)
        audio.frame()
        left, right = heard(factory.engine)
        assert left > right * 3
        audio.close()

    def test_a_placement_that_answers_nothing_keeps_the_last_place(
            self, factory: Factory, tone: Any) -> None:
        node = object()
        places: list[Any] = [(6.0, 0.0, 0.0)]
        audio = Audio(engine_factory=factory, follow=lambda found: places[0])
        audio.play(tone, at=node, loop=True)
        places[0] = None
        audio.frame()
        left, right = heard(factory.engine)
        assert right > left * 3
        audio.close()

    def test_a_node_with_no_placement_callable_is_centred_with_one_warning(
            self, audio: Audio, factory: Factory, tone: Any,
            caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            audio.play(tone, at=object())
            audio.play(tone, at=object())
        left, right = heard(factory.engine)
        assert left == pytest.approx(right)
        assert len(warnings_logged(caplog)) == 1

    def test_a_listener_that_moves_changes_what_is_heard(
            self, factory: Factory, tone: Any) -> None:
        context = Context()
        audio = Audio(context, engine_factory=factory)
        audio.play(tone, at=(6.0, 0.0, 0.0), loop=True)
        context.platform.position = (12.0, 0.0, 0.0)
        audio.frame()
        left, right = heard(factory.engine)
        assert left > right * 3
        audio.close()

    def test_a_listener_set_on_the_audio_overrides_the_camera(
            self, factory: Factory, tone: Any) -> None:
        context = Context()
        audio = Audio(context, engine_factory=factory)
        assert audio.listener is None
        audio.listener = viewplatform.ViewPlatform(position=(12.0, 0.0, 0.0))
        audio.play(tone, at=(6.0, 0.0, 0.0), loop=True)
        audio.frame()
        left, right = heard(factory.engine)
        assert left > right * 3
        audio.close()

    def test_an_emitter_gives_the_sound_its_own_profile(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        steep = model.AudioEmitter(positional=model.PositionalProperties(rolloffFactor=4.0))
        gentle = model.AudioEmitter(positional=model.PositionalProperties(rolloffFactor=0.1))
        audio.play(tone, at=(8.0, 0.0, 0.0), emitter=steep)
        loud = heard(factory.engine)[1]
        factory.engine.stop_all()
        audio.play(tone, at=(8.0, 0.0, 0.0), emitter=gentle)
        assert heard(factory.engine)[1] > loud * 2

    def test_a_global_emitter_is_heard_the_same_everywhere(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone, emitter=model.AudioEmitter(type='global'))
        left, right = heard(factory.engine)
        assert left == pytest.approx(right)


class TestSources:
    def test_a_path_is_decoded_and_cached(
            self, audio: Audio, factory: Factory, tmp_path: Path) -> None:
        path = write_wave(tmp_path / 'thud.wav')
        audio.play(str(path))
        audio.play(path)
        assert str(path) in factory.engine.clips
        assert len(factory.engine.clips) == 1
        assert factory.engine.active_voices == 2

    def test_a_loaded_name_plays_the_clip_it_names(
            self, audio: Audio, factory: Factory, tmp_path: Path) -> None:
        audio.load('thud', write_wave(tmp_path / 'thud.wav'))
        voice = audio.play('thud')
        assert voice.playing
        assert heard(factory.engine)[0] > 0.05

    def test_load_decodes_before_any_device_opens(
            self, audio: Audio, factory: Factory, tmp_path: Path) -> None:
        audio.load('thud', write_wave(tmp_path / 'thud.wav'))
        assert factory.engines == []

    def test_load_from_another_thread_serves_the_render_thread(
            self, audio: Audio, factory: Factory, tmp_path: Path) -> None:
        path = write_wave(tmp_path / 'thud.wav')
        on_thread(lambda: audio.load('thud', path))
        assert audio.play('thud').playing

    def test_a_url_is_fetched_once_and_played(
            self, audio: Audio, factory: Factory, tmp_path: Path,
            monkeypatch: pytest.MonkeyPatch) -> None:
        data = write_wave(tmp_path / 'far.wav').read_bytes()
        fetched: list[str] = []

        def fetch(url: str, **named: Any) -> bytes:
            fetched.append(str(url))
            return data

        monkeypatch.setattr(audiomanager.resolver, 'fetch_url', fetch)
        url = 'https://example.com/far.wav'
        assert audio.play(url).playing
        assert audio.play(url).playing
        assert fetched == [url]

    def test_a_url_that_will_not_fetch_is_inert_with_one_warning(
            self, audio: Audio, factory: Factory, caplog: pytest.LogCaptureFixture,
            monkeypatch: pytest.MonkeyPatch) -> None:
        def refuse(url: str, **named: Any) -> bytes:
            raise OSError('unreachable')

        monkeypatch.setattr(audiomanager.resolver, 'fetch_url', refuse)
        with caplog.at_level(logging.WARNING):
            assert not audio.play('https://example.com/far.wav').playing
            assert not audio.play('https://example.com/far.wav').playing
        assert len(warnings_logged(caplog)) == 1

    def test_a_url_over_the_size_cap_is_inert(
            self, audio: Audio, monkeypatch: pytest.MonkeyPatch) -> None:
        def too_big(url: str, **named: Any) -> bytes:
            raise resolver.ResourceTooLarge('too big')

        monkeypatch.setattr(audiomanager.resolver, 'fetch_url', too_big)
        assert not audio.play('https://example.com/big.wav').playing

    def test_a_missing_file_is_inert_with_one_warning(
            self, audio: Audio, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        missing = str(tmp_path / 'gone.wav')
        with caplog.at_level(logging.WARNING):
            first = audio.play(missing)
            second = audio.play(missing)
        assert not first.playing
        assert not second.playing
        assert len(warnings_logged(caplog)) == 1

    def test_a_loaded_name_that_will_not_decode_is_inert_with_one_warning(
            self, audio: Audio, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            audio.load('gone', tmp_path / 'gone.wav')
            audio.load('gone', tmp_path / 'gone.wav')
            assert not audio.play('gone').playing
        assert len(warnings_logged(caplog)) == 1

    def test_a_queued_play_of_a_missing_file_ends_the_voice_at_the_frame(
            self, audio: Audio, tmp_path: Path) -> None:
        voice = on_thread(lambda: audio.play(str(tmp_path / 'gone.wav')))
        assert voice.playing
        audio.frame()
        assert not voice.playing


class TestSwitchedOff:
    def test_a_disabled_audio_returns_an_inert_voice_and_opens_nothing(
            self, factory: Factory, tone: Any, caplog: pytest.LogCaptureFixture) -> None:
        context = Context(enabled=0)
        audio = Audio(context, engine_factory=factory)
        assert not audio.enabled
        with caplog.at_level(logging.WARNING):
            first = audio.play(tone)
            second = audio.play(tone, at=(1.0, 0.0, 0.0))
        first.gain = 0.2
        first.rate = 2.0
        first.stop()
        assert not first.playing
        assert not second.playing
        assert factory.engines == []
        assert len(warnings_logged(caplog)) == 1
        audio.close()

    def test_load_does_nothing_while_disabled(self, factory: Factory, tmp_path: Path) -> None:
        audio = Audio(Context(enabled=0), engine_factory=factory)
        audio.load('thud', write_wave(tmp_path / 'thud.wav'))
        assert not audio.play('thud').playing
        audio.close()

    def test_turning_sound_back_on_plays(self, factory: Factory, tone: Any) -> None:
        context = Context(enabled=0)
        audio = Audio(context, engine_factory=factory)
        assert not audio.play(tone).playing
        context.contextDefinition.audio.enabled = 1
        assert audio.play(tone).playing
        audio.close()

    def test_a_device_that_fails_gives_an_inert_voice_and_one_warning(
            self, tone: Any, caplog: pytest.LogCaptureFixture) -> None:
        calls: list[int] = []

        def broken() -> AudioEngine:
            calls.append(1)
            raise RuntimeError('no such device')

        audio = Audio(engine_factory=broken)
        with caplog.at_level(logging.WARNING):
            first = audio.play(tone)
            second = on_thread(lambda: audio.play(tone))
            audio.frame()
        assert not first.playing
        assert not second.playing
        assert calls == [1]
        assert len(warnings_logged(caplog)) == 1
        assert audio.engine is None
        audio.close()

    def test_a_factory_that_answers_no_engine_gives_inert_voices(self, tone: Any) -> None:
        audio = Audio(engine_factory=lambda: None)
        assert not audio.play(tone).playing
        assert audio.engine is None
        audio.close()

    def test_a_missing_backend_still_plays_on_a_silent_engine(
            self, tone: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audiomanager, 'open_device',
                            lambda **named: NullDevice(sample_rate=RATE))
        audio = Audio()
        assert audio.play(tone).playing
        assert audio.engine is not None
        assert audio.engine.silent
        audio.close()

    def test_a_context_owner_uses_the_scene_engine(
            self, tone: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audioscene, 'open_device',
                            lambda **named: NullDevice(sample_rate=RATE))
        context = Context()
        audio = Audio(context)
        audio.play(tone)
        assert audio.engine is audioscene.existing_engine(context)
        audio.close()
        assert audioscene.existing_engine(context) is None


class TestSettings:
    def test_volume_reads_and_writes_the_players_setting(self) -> None:
        context = Context(volume=0.7)
        audio = Audio(context, engine_factory=Factory())
        assert audio.volume == pytest.approx(0.7)
        audio.volume = 0.4
        assert context.contextDefinition.audio.volume == pytest.approx(0.4)
        audio.close()

    def test_volume_reaches_the_engine_when_it_opens(self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(Context(volume=0.3), engine_factory=factory)
        audio.play(tone)
        assert factory.engine.volume == pytest.approx(0.3)
        audio.close()

    def test_setting_volume_changes_the_open_engine_at_once(self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(Context(), engine_factory=factory)
        audio.play(tone)
        audio.volume = 0.5
        assert factory.engine.volume == pytest.approx(0.5)
        audio.close()

    def test_volume_set_from_another_thread_reaches_the_engine_at_the_frame(
            self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(Context(), engine_factory=factory)
        audio.play(tone)

        def lower() -> None:
            audio.volume = 0.2

        on_thread(lower)
        audio.frame()
        assert factory.engine.volume == pytest.approx(0.2)
        audio.close()

    def test_the_settings_screen_moves_the_engine_through_the_frame(self, tone: Any) -> None:
        factory = Factory()
        context = Context()
        audio = Audio(context, engine_factory=factory)
        audio.play(tone)
        context.contextDefinition.audio.volume = 0.6
        audio.frame()
        assert factory.engine.volume == pytest.approx(0.6)
        audio.close()

    def test_an_audio_with_no_owner_keeps_its_own_settings(self, tone: Any) -> None:
        audio = Audio(engine_factory=Factory())
        assert audio.volume == 1.0
        audio.volume = 0.25
        assert audio.volume == 0.25
        audio.close()

    def test_given_settings_are_the_ones_read(self, tone: Any) -> None:
        settings = AudioSettings(volume=0.1)
        audio = Audio(Context(), engine_factory=Factory(), settings=settings)
        assert audio.volume == pytest.approx(0.1)
        audio.volume = 0.9
        assert settings.volume == pytest.approx(0.9)
        audio.close()

    def test_the_voice_budget_is_the_settings_voices(
            self, tone: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(audiomanager, 'open_device',
                            lambda **named: NullDevice(sample_rate=RATE))
        audio = Audio(settings=AudioSettings(voices=3))
        for _ in range(5):
            audio.play(tone)
        assert audio.engine is not None
        assert audio.engine.active_voices == 3
        audio.close()

    def test_muffle_before_the_engine_exists_is_applied_when_it_opens(
            self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        assert audio.muffle == 0.0
        audio.muffle = 0.8
        assert audio.muffle == pytest.approx(0.8)
        assert factory.engines == []
        audio.play(tone)
        assert factory.engine.muffle == pytest.approx(0.8)
        audio.close()

    def test_muffle_passes_through_to_the_open_engine(self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        audio.play(tone)
        audio.muffle = 1.0
        assert factory.engine.muffle == pytest.approx(1.0)
        factory.engine.muffle = 0.25
        assert audio.muffle == pytest.approx(0.25)
        audio.close()

    def test_an_engine_muffle_set_elsewhere_survives_when_audio_never_set_one(
            self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        audio.play(tone)
        factory.engine.muffle = 0.5
        audio.frame()
        assert factory.engine.muffle == pytest.approx(0.5)
        audio.close()

    def test_muffle_set_from_another_thread_reaches_the_engine_at_the_frame(
            self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        audio.play(tone)
        on_thread(lambda: setattr(audio, 'muffle', 0.7))
        assert factory.engine.muffle == 0.0
        audio.frame()
        assert factory.engine.muffle == pytest.approx(0.7)
        audio.close()


class TestClose:
    def test_close_stops_every_voice_and_closes_the_engine(
            self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        voice = audio.play(tone)
        audio.close()
        assert not voice.playing
        assert factory.engine.active_voices == 0
        assert factory.engine._closed

    def test_play_after_close_is_inert(self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        audio.close()
        assert not audio.enabled
        assert not audio.play(tone).playing
        assert factory.engines == []
        assert audio.frame() == 0

    def test_close_twice_is_safe(self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        voice = audio.play(tone)
        audio.close()
        audio.close()
        assert not voice.playing

    def test_close_without_an_engine_is_safe(self, factory: Factory) -> None:
        Audio(engine_factory=factory).close()
        assert factory.engines == []


class HookedEngine(AudioEngine):
    """An engine that runs a callback while a voice is being started.

    The callback stands in for another thread acting between the engine
    starting the voice and the Audio recording it.
    """

    during_play: Callable[[], None] | None = None

    def play(self, source: Any, *named: Any, **options: Any) -> Any:
        handle = super().play(source, *named, **options)
        if self.during_play is not None:
            self.during_play()
        return handle


class TestRaces:
    def test_a_stop_that_lands_while_the_voice_starts_silences_it(self, tone: Any) -> None:
        engine = HookedEngine(device=NullDevice(sample_rate=RATE), voices=4)
        audio = Audio(engine_factory=lambda: engine)
        made: list[Voice] = []
        engine.during_play = lambda: made[0].stop() if made else None
        voice = Voice(audio, tone, gain=1.0, rate=1.0, priority=0.5, loop=False,
                      emitter=None, track=None)
        made.append(voice)
        audio._start(voice)
        assert not voice.playing
        assert engine.active_voices == 0
        audio.close()

    def test_a_gain_set_while_the_voice_starts_is_applied_after(self, tone: Any) -> None:
        engine = HookedEngine(device=NullDevice(sample_rate=RATE), voices=4)
        audio = Audio(engine_factory=lambda: engine)
        made: list[Voice] = []

        def change() -> None:
            made[0].gain = 0.25

        engine.during_play = change
        voice = Voice(audio, tone, gain=1.0, rate=1.0, priority=0.5, loop=False,
                      emitter=None, track=None)
        made.append(voice)
        audio._start(voice)
        engine.during_play = None
        quiet, _ = heard(engine)
        assert quiet < 0.2
        audio.close()


class TestAfterTheEnd:
    def test_setting_a_voice_whose_clip_ended_does_nothing(
            self, audio: Audio, factory: Factory) -> None:
        voice = audio.play(synth.tone(440.0, 0.05, sample_rate=RATE))
        factory.engine.mixer.mix(BLOCK * 2)
        voice.gain = 0.5
        voice.rate = 2.0
        assert not voice.playing

    def test_setting_a_voice_after_close_does_nothing(
            self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        voice = audio.play(tone)
        audio.close()
        voice.gain = 0.5
        assert not voice.playing

    def test_switching_sound_off_silences_every_voice_at_the_next_frame(
            self, factory: Factory, tone: Any) -> None:
        context = Context()
        audio = Audio(context, engine_factory=factory)
        placed = audio.play(tone, at=(3.0, 0.0, 0.0), loop=True)
        centred = audio.play(tone, loop=True)
        context.contextDefinition.audio.enabled = 0
        audio.frame()
        assert not placed.playing
        assert not centred.playing
        audio.close()

    def test_a_voice_has_a_readable_repr(self, audio: Audio, tone: Any) -> None:
        assert 'live playing' in repr(audio.play(tone))


class TestMix:
    def test_mix_before_the_engine_exists_is_applied_when_it_opens(self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        assert audio.mix == 1.0
        audio.mix = 0.2
        assert audio.mix == pytest.approx(0.2)
        assert factory.engines == []
        audio.play(tone)
        assert factory.engine.master_gain == pytest.approx(0.2)
        audio.close()

    def test_mix_scales_what_is_heard_and_leaves_the_players_volume(self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        audio.play(tone, loop=True)
        full = heard(factory.engine)[0]
        audio.mix = 0.25
        assert heard(factory.engine)[0] == pytest.approx(full * 0.25, rel=0.05)
        assert audio.volume == pytest.approx(1.0)
        audio.close()

    def test_mix_set_from_another_thread_reaches_the_engine_at_the_frame(
            self, tone: Any) -> None:
        factory = Factory()
        audio = Audio(engine_factory=factory)
        audio.play(tone)
        on_thread(lambda: setattr(audio, 'mix', 0.5))
        assert factory.engine.master_gain == pytest.approx(1.0)
        audio.frame()
        assert factory.engine.master_gain == pytest.approx(0.5)
        audio.close()

    def test_a_negative_mix_is_refused(self, audio: Audio) -> None:
        with pytest.raises(ValueError):
            audio.mix = -0.1


class TestNamedClips:
    def test_an_added_clip_plays_by_its_name(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.add('hum', tone)
        assert audio.play('hum').playing
        assert heard(factory.engine)[0] > 0.0

    def test_an_added_clip_is_what_a_scene_source_of_that_name_finds(
            self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        audio.add('hum', tone)
        engine = audio.engine
        assert engine is not None
        assert engine.clips.get('hum') is tone
        audio.add('later', tone)
        assert engine.clips.get('later') is tone
        audio.close()

    def test_a_clip_added_on_another_thread_reaches_the_scene_at_the_frame(
            self, factory: Factory, tone: Any) -> None:
        audio = Audio(engine_factory=factory)
        engine = audio.engine
        assert engine is not None
        on_thread(lambda: audio.add('hum', tone))
        assert 'hum' not in engine.clips
        audio.frame()
        assert engine.clips.get('hum') is tone
        audio.close()


class TestWhatIsPlaying:
    def test_level_is_nothing_with_no_engine_or_no_voice(self, audio: Audio, tone: Any) -> None:
        assert audio.level == 0.0
        voice = audio.play(tone)
        voice.stop()
        assert audio.level == 0.0

    def test_level_follows_the_voice_gain_and_the_mix(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        audio.play(tone, loop=True)
        heard(factory.engine)
        loud = audio.level
        assert 0.0 < loud <= 1.0
        audio.mix = 0.5
        assert audio.level == pytest.approx(loud * 0.5)

    def test_a_distant_sound_has_a_lower_level(
            self, audio: Audio, factory: Factory, tone: Any) -> None:
        voice = audio.play(tone, at=(1.0, 0.0, 0.0), loop=True)
        heard(factory.engine)
        near = audio.level
        voice.stop()
        audio.play(tone, at=(40.0, 0.0, 0.0), loop=True)
        heard(factory.engine)
        assert audio.level < near

    def test_describe_names_the_output_the_voices_and_the_settings(
            self, audio: Audio, tone: Any) -> None:
        assert audio.describe() == 'audio: not open'
        audio.play(tone, loop=True)
        audio.mix = 0.5
        line = audio.describe()
        assert line.startswith('audio: silent')
        assert 'voices 1' in line and 'mix 0.50' in line and 'muffle 0.00' in line
        assert audio.silent

    def test_describe_says_when_sound_is_switched_off(self) -> None:
        audio = Audio(settings=AudioSettings(enabled=0))
        assert audio.describe() == 'audio: off'
        assert audio.silent
