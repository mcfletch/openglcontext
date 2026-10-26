"""RecordingAudio: what a game's tests assert sounds on."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest
from omi_audio import model, synth

import OpenGLContext.testing as testing
from OpenGLContext.audio.manager import Audio, Voice
from OpenGLContext.audio.settings import AudioSettings
from OpenGLContext.testing.audio import Call, RecordingAudio


class Crate:
    """A game object that makes a sound when it breaks."""

    def __init__(self, audio: Audio) -> None:
        self.audio = audio
        self.position = (1.0, 2.0, 3.0)

    def break_open(self) -> None:
        self.audio.play('crack.ogg', at=self.position, gain=0.8)


@pytest.fixture
def audio() -> RecordingAudio:
    return RecordingAudio()


class TestRecording:
    def test_it_is_an_audio(self, audio: RecordingAudio) -> None:
        assert isinstance(audio, Audio)
        assert testing.RecordingAudio is RecordingAudio

    def test_a_play_is_recorded_with_its_arguments(self, audio: RecordingAudio) -> None:
        emitter = model.AudioEmitter()
        voice = audio.play('thud.ogg', at=(1, 2, 3), gain=0.5, rate=1.5, priority=0.9,
                           loop=True, emitter=emitter)
        [call] = audio.calls
        assert call == Call('play', source='thud.ogg', at=(1, 2, 3), gain=0.5, rate=1.5,
                            priority=0.9, loop=True, emitter=emitter, voice=voice)

    def test_defaults_are_those_of_a_real_play(self, audio: RecordingAudio) -> None:
        audio.play('thud.ogg')
        [call] = audio.calls
        assert (call.at, call.gain, call.rate, call.priority, call.loop, call.emitter) == (
            None, 1.0, 1.0, 0.5, False, None)

    def test_the_game_code_under_test_is_observed_without_a_device(
            self, audio: RecordingAudio) -> None:
        Crate(audio).break_open()
        [call] = audio.played('crack.ogg')
        assert call.at == (1.0, 2.0, 3.0)
        assert call.gain == 0.8
        assert audio.engine is None

    def test_nothing_is_played_before_it_is_asked_for(self, audio: RecordingAudio) -> None:
        assert audio.calls == []
        assert audio.plays == []
        assert audio.played('crack.ogg') == []

    def test_calls_is_a_snapshot(self, audio: RecordingAudio) -> None:
        snapshot = audio.calls
        audio.play('a.ogg')
        assert snapshot == []
        assert len(audio.calls) == 1

    def test_clear_forgets_the_calls(self, audio: RecordingAudio) -> None:
        audio.play('a.ogg')
        audio.clear()
        assert audio.calls == []


class TestAsking:
    def test_played_with_no_argument_is_every_play(self, audio: RecordingAudio) -> None:
        audio.play('a.ogg')
        audio.play('b.ogg')
        audio.volume = 0.5
        assert [call.source for call in audio.played()] == ['a.ogg', 'b.ogg']

    def test_played_selects_by_path(self, audio: RecordingAudio) -> None:
        audio.play('a.ogg')
        audio.play('b.ogg')
        audio.play(Path('a.ogg'))
        assert len(audio.played('a.ogg')) == 2
        assert len(audio.played(Path('b.ogg'))) == 1

    def test_a_loaded_name_and_its_path_are_the_same_sound(self, audio: RecordingAudio) -> None:
        audio.load('thud', 'sounds/thud.ogg')
        audio.play('thud')
        audio.play('sounds/thud.ogg')
        assert len(audio.played('thud')) == 2
        assert len(audio.played('sounds/thud.ogg')) == 2
        assert audio.played('other') == []

    def test_played_selects_a_clip_by_identity_and_by_name(self, audio: RecordingAudio) -> None:
        beep = synth.tone(440.0, 0.1, sample_rate=8000)
        other = synth.tone(880.0, 0.1, sample_rate=8000)
        audio.play(beep)
        audio.play(other)
        assert [call.source for call in audio.played(beep)] == [beep]
        assert [call.source for call in audio.played(other.name)] == [other]
        assert audio.played(synth.tone(220.0, 0.1, sample_rate=8000)) == []

    def test_a_path_never_matches_an_unnamed_clip(self, audio: RecordingAudio) -> None:
        from omi_audio.clip import Clip
        import numpy as np
        unnamed = Clip(np.zeros(8, dtype=np.float32), 8000)
        audio.play(unnamed)
        assert audio.played('') == []
        assert len(audio.played(unnamed)) == 1


class TestVoices:
    def test_a_voice_plays_until_stopped(self, audio: RecordingAudio) -> None:
        voice = audio.play('a.ogg')
        assert isinstance(voice, Voice)
        assert voice.playing
        voice.stop()
        assert not voice.playing

    def test_voice_changes_and_stops_are_recorded(self, audio: RecordingAudio) -> None:
        voice = audio.play('a.ogg')
        voice.gain = 0.25
        voice.rate = 2.0
        voice.stop()
        voice.stop()
        kinds = [call.kind for call in audio.calls]
        assert kinds == ['play', 'update', 'update', 'stop']
        update = audio.calls[2]
        assert (update.voice, update.gain, update.rate) == (voice, 0.25, 2.0)
        assert audio.calls[3].voice is voice

    def test_a_voice_that_follows_something_is_still_just_a_record(
            self, audio: RecordingAudio) -> None:
        class Body:
            position = (1.0, 0.0, 0.0)

        body = Body()
        audio.play('engine.ogg', at=body, loop=True)
        assert audio.played('engine.ogg')[0].at is body


class TestSettings:
    def test_volume_muffle_and_mix_are_recorded_and_read_back(self, audio: RecordingAudio) -> None:
        audio.volume = 0.4
        audio.muffle = 1.0
        audio.mix = 0.3
        assert audio.volume == pytest.approx(0.4)
        assert audio.muffle == 1.0
        assert audio.mix == pytest.approx(0.3)
        assert [(call.kind, call.value) for call in audio.calls] == [
            ('volume', 0.4), ('muffle', 1.0), ('mix', 0.3)]

    def test_given_settings_are_the_ones_written(self) -> None:
        settings = AudioSettings(volume=0.9)
        audio = RecordingAudio(settings=settings)
        audio.volume = 0.1
        assert settings.volume == pytest.approx(0.1)

    def test_load_is_recorded_with_its_name_and_path(self, audio: RecordingAudio) -> None:
        audio.load('thud', 'sounds/thud.ogg')
        [call] = audio.calls
        assert (call.kind, call.source, call.value) == ('load', 'sounds/thud.ogg', 'thud')

    def test_add_is_recorded_and_opens_no_engine(
            self, audio: RecordingAudio, monkeypatch: pytest.MonkeyPatch) -> None:
        beep = synth.tone(440.0, 0.1, sample_rate=8000)
        monkeypatch.setattr('OpenGLContext.audio.manager.open_device', None)
        audio.add('beep', beep)
        [call] = audio.calls
        assert (call.kind, call.source, call.value) == ('add', beep, 'beep')
        audio.play('beep')
        assert len(audio.played('beep')) == 1
        assert len(audio.played(beep)) == 1
        assert audio.engine is None

    def test_frame_has_nothing_queued(self, audio: RecordingAudio) -> None:
        audio.play('a.ogg')
        assert audio.frame() == 0

    def test_after_close_nothing_more_is_recorded(self, audio: RecordingAudio) -> None:
        voice = audio.play('a.ogg')
        audio.close()
        late = audio.play('b.ogg')
        assert not voice.playing
        assert not late.playing
        assert audio.played('b.ogg') == []


class TestThreads:
    def test_a_play_from_another_thread_is_recorded_at_once(
            self, audio: RecordingAudio) -> None:
        worker = threading.Thread(target=lambda: audio.play('hit.ogg', at=(0, 0, 1)))
        worker.start()
        worker.join()
        assert len(audio.played('hit.ogg')) == 1

    def test_many_threads_lose_nothing(self, audio: RecordingAudio) -> None:
        def burst(index: int) -> None:
            for count in range(25):
                voice = audio.play('hit.ogg', gain=index + count / 100)
                voice.gain = 0.5

        workers = [threading.Thread(target=burst, args=(index,)) for index in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        assert len(audio.played('hit.ogg')) == 100
        assert len(audio.calls) == 200


def test_the_calls_have_a_readable_repr() -> None:
    call: Any = Call('play', source='a.ogg')
    assert 'play' in repr(call)
    assert 'a.ogg' in repr(call)
