"""The audio demo's yard, driven the way ``oglc-audio-demo`` drives it.

The yard is the whole of the demo's behaviour and holds no GL, so each thing it
shows -- a collision, an event, an area, a sound that follows the simulation --
is tested here with a silent device and no window.
"""

import numpy as np
import pytest

from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine
from vrml.vrml97 import nodepath, nodetypes

from OpenGLContext.bin import audio_demo
from OpenGLContext.bin.audio_demo import AudioYard
from OpenGLContext.scenegraph.audio import update_scene_audio

FRAME = 1.0 / 60.0
RATE = 8000


@pytest.fixture
def engine():
    made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=32)
    yield made
    made.close()


def auditory_paths(root):
    """The paths to every sound in a scene, as the render pass collects them."""
    found, todo = [], [(root, nodepath.NodePath([]))]
    while todo:
        node, parents = todo.pop(0)
        path = parents + node
        if isinstance(node, nodetypes.Auditory):
            found.append(path)
        for child in getattr(node, 'renderedChildren', lambda: [])():
            todo.append((child, path))
    return found


@pytest.fixture
def yard(engine):
    made = AudioYard(sample_rate=RATE)
    made.paths = auditory_paths(made.scene())
    made.clock = 0.0
    return made


OUTSIDE = (0.0, 1.6, 12.0)


def run(yard, engine, seconds, where=OUTSIDE):
    """Frames of the demo, each with its share of mixing; sounds started.

    Each frame steps the yard, then drives its sound nodes as the render pass
    would, then mixes a frame's worth of samples as a device would pull them.
    """
    started = 0
    for _ in range(max(1, int(round(seconds / FRAME)))):
        started += yard.step(FRAME, where, engine)
        yard.clock += FRAME
        update_scene_audio(engine, yard.paths, yard.clock)
        engine.mixer.mix(int(FRAME * RATE))
    return started


class TestCollisions:
    def test_dropped_balls_thud_on_the_floor(self, yard, engine):
        yard.drop()
        assert run(yard, engine, 3.0) > 0

    def test_balls_at_rest_are_quiet(self, yard, engine):
        yard.drop()
        run(yard, engine, 10.0)
        assert run(yard, engine, 2.0) == 0

    def test_they_can_be_dropped_again(self, yard, engine):
        yard.drop()
        run(yard, engine, 10.0)
        yard.drop()
        assert run(yard, engine, 3.0) > 0


class TestEvents:
    def test_the_bell_rings_when_struck(self, yard, engine):
        run(yard, engine, 0.1)
        before = engine.active_voices
        yard.ring()
        run(yard, engine, FRAME)
        assert engine.active_voices == before + 1

    def test_striking_it_again_restarts_rather_than_stacking(self, yard, engine):
        yard.ring()
        run(yard, engine, 0.1)
        voices = engine.active_voices
        yard.ring()
        run(yard, engine, FRAME)
        assert engine.active_voices == voices

    def test_a_shot_is_centred(self, yard, engine):
        engine.stop_all()
        assert yard.fire(engine) is not None
        block = engine.mixer.mix(64)
        assert np.abs(block[:, 0]).max() == pytest.approx(
            float(np.abs(block[:, 1]).max()))

    def test_firing_with_no_engine_is_harmless(self, yard):
        assert yard.fire(None) is None


class TestAreas:
    def test_the_cave_is_heard_inside_it(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.CAVE_CENTRE)
        assert yard.cave.gain == pytest.approx(audio_demo.AREA_LEVEL)
        assert yard.stream.gain == 0.0

    def test_the_stream_is_heard_inside_it(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.STREAM_CENTRE)
        assert yard.stream.gain == pytest.approx(audio_demo.AREA_LEVEL)
        assert yard.cave.gain == 0.0

    def test_neither_is_heard_from_the_start(self, yard, engine):
        run(yard, engine, FRAME)
        assert yard.cave.gain == yard.stream.gain == 0.0


class TestTheMotor:
    def test_it_spins_up_and_rises_in_pitch(self, yard, engine):
        yard.toggle_motor()
        run(yard, engine, 4.0)
        assert yard.motor.gain > 0.0
        assert yard.motor.playbackRate > 1.0

    def test_it_spins_down_to_silence(self, yard, engine):
        yard.toggle_motor()
        run(yard, engine, 4.0)
        yard.toggle_motor()
        run(yard, engine, 8.0)
        assert yard.motor.gain == 0.0

    def test_its_pitch_reaches_the_playing_voice(self, yard, engine):
        yard.toggle_motor()
        run(yard, engine, 4.0)
        rates = [voice.rate for voice in engine.mixer.voices
                 if voice.active and voice.loop]
        assert max(rates) > 1.0

    def test_the_rotor_turns_with_it(self, yard, engine):
        yard.toggle_motor()
        run(yard, engine, 1.0)
        assert yard.rotor.rotation[3] != 0.0


class TestWithoutSound:
    def test_the_yard_runs_with_no_engine(self, yard):
        yard.drop()
        yard.ring()
        yard.toggle_motor()
        for _ in range(60):
            assert yard.step(FRAME, OUTSIDE, None) == 0

    def test_the_scene_holds_every_sound(self, yard):
        assert len(yard.paths) == 3        # the bell, the motor, the areas
