"""The audio demo's yard, driven the way ``oglc-audio-demo`` drives it.

The yard is the whole of the demo's behaviour and holds no GL, so each thing it
shows -- a collision, an event, an area, a sound that follows the simulation --
is tested here with a silent device and no window.
"""

import subprocess
import sys

import numpy as np
import pytest

from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine
from vrml.vrml97 import nodepath, nodetypes

from OpenGLContext.audio.areas import apply_zones
from OpenGLContext.audio.manager import Audio
from OpenGLContext.audio.settings import AudioSettings
from OpenGLContext.bin import audio_demo
from OpenGLContext.bin.audio_demo import AudioYard
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.zones import scene_zones
from OpenGLContext.scenegraph.audio import update_scene_audio

FRAME = 1.0 / 60.0
RATE = 8000


@pytest.fixture
def engine():
    made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=32)
    yield made
    made.close()


@pytest.fixture
def audio(engine):
    """The service that plays what the yard asks for, on the silent engine."""
    made = Audio(engine_factory=lambda: engine)
    made.engine  # opened here, so the scene's nodes and the calls share it
    yield made
    made.close()


class Counted:
    """What ``audio.play`` is asked to play, for a test to count the thuds."""

    def __init__(self, audio):
        self.sources = []
        self._play = audio.play
        audio.play = self.play

    def play(self, source, *args, **named):
        self.sources.append(source)
        return self._play(source, *args, **named)


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


def make(audio, rate=RATE):
    """A yard in a standalone physics service, with what the render pass would collect from its scene."""
    physics = Physics(audio_demo_definition())
    yard = AudioYard(physics, audio, sample_rate=rate)
    scene = yard.scene()
    yard.paths = auditory_paths(scene)
    yard.zones = scene_zones(scene)
    yard.clock = 0.0
    yard.counted = Counted(audio)
    return yard


def audio_demo_definition():
    return PhysicsDefinition(mode='inline', colliders='explicit', maxCatchUp=2.0)


@pytest.fixture
def yard(audio):
    made = make(audio)
    yield made
    made.physics.close()


OUTSIDE = (0.0, 1.6, 12.0)


def run(yard, engine, seconds, where=OUTSIDE, frame=FRAME):
    """Frames of the demo, each with its share of mixing; the thuds started.

    Each frame steps the physics, turns the motor, then sets the zones' gains
    and reverb and drives its sound nodes as the render pass would with the
    camera at ``where``, then mixes a frame's worth of samples as a device
    would pull them.
    """
    before = len(yard.counted.sources)
    for _ in range(max(1, int(round(seconds / frame)))):
        yard.physics.frame(frame)
        yard.update(frame)
        yard.clock += frame
        apply_zones(engine, [path[-1] for path in yard.paths], yard.zones, where)
        update_scene_audio(engine, yard.paths, yard.clock)
        engine.mixer.mix(int(frame * RATE))
    return len([source for source in yard.counted.sources[before:] if source is yard.thud])


class TestCollisions:
    def test_dropped_balls_thud_on_the_floor(self, yard, engine):
        yard.drop()
        assert run(yard, engine, 3.0) > 0

    def test_balls_at_rest_are_quiet(self, yard, engine):
        yard.drop()
        run(yard, engine, 10.0)
        assert run(yard, engine, 2.0) == 0

    def test_a_slow_frame_rate_hears_every_bounce(self, engine, audio):
        def thuds(frame):
            yard = make(audio)
            yard.drop()
            count = run(yard, engine, 4.0, frame=frame)
            yard.physics.close()
            return count

        at_120 = thuds(1.0 / 120.0)
        assert at_120 > len(audio_demo.BALL_SPOTS)
        assert thuds(1.0 / 20.0) == at_120

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
        assert yard.fire().playing
        block = engine.mixer.mix(64)
        assert np.abs(block[:, 0]).max() == pytest.approx(
            float(np.abs(block[:, 1]).max()))

    def test_firing_with_the_sound_switched_off_is_harmless(self):
        silent = Audio(settings=AudioSettings(enabled=False))
        yard = make(silent)
        assert not yard.fire().playing
        yard.physics.close()


class TestAreas:
    """The cave and the stream are zones; the render pass sets their gains."""

    def test_the_cave_is_heard_inside_it(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.CAVE_CENTRE)
        assert yard.cave_sound.zoneGain == pytest.approx(1.0)
        assert yard.stream_sound.zoneGain == 0.0

    def test_the_stream_is_heard_inside_it(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.STREAM_CENTRE)
        assert yard.stream_sound.zoneGain == pytest.approx(1.0)
        assert yard.cave_sound.zoneGain == 0.0

    def test_neither_is_heard_from_the_start(self, yard, engine):
        run(yard, engine, FRAME)
        assert yard.cave_sound.zoneGain == yard.stream_sound.zoneGain == 0.0

    def test_the_cave_echoes(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.CAVE_CENTRE)
        assert engine.reverb.level == pytest.approx(audio_demo.CAVE_REVERB)
        assert engine.reverb.decay == pytest.approx(audio_demo.CAVE_DECAY)

    def test_the_stream_does_not(self, yard, engine):
        run(yard, engine, FRAME, where=audio_demo.STREAM_CENTRE)
        assert engine.reverb.level == 0.0

    def test_the_cave_fades_in_over_the_margin_outside_it(self, yard, engine):
        x, y, z = audio_demo.CAVE_CENTRE
        edge = x + audio_demo.AREA_HALF_SIZE[0] + audio_demo.AREA_MARGIN / 2
        run(yard, engine, FRAME, where=(edge, y, z))
        assert 0.0 < yard.cave_sound.zoneGain < 1.0


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


class TestThePlayersControls:
    def test_muffle_toggles(self, yard, engine):
        assert yard.toggle_muffle() == 1.0
        assert engine.muffle == 1.0
        assert yard.toggle_muffle() == 0.0

    def test_the_volume_moves_within_its_range(self, yard):
        yard.audio.volume = 0.95
        assert yard.change_volume(0.1) == 1.0
        assert yard.change_volume(-0.3) == pytest.approx(0.7)
        yard.audio.volume = 0.05
        assert yard.change_volume(-0.1) == 0.0


class TestWithoutSound:
    def test_the_yard_runs_with_the_sound_switched_off(self):
        silent = Audio(settings=AudioSettings(enabled=False))
        yard = make(silent)
        yard.drop()
        yard.ring()
        yard.toggle_motor()
        for _ in range(60):
            yard.physics.frame(FRAME)
            yard.update(FRAME)
        assert yard.balls[0].position[1] < audio_demo.DROP_HEIGHTS[0]
        yard.physics.close()

    def test_the_scene_holds_every_sound(self, yard):
        assert len(yard.paths) == 4        # the bell, the motor, the two areas


def test_importing_the_demo_chooses_no_window_backend():
    """``oglc-audio-demo --help`` and these tests import the module; only
    ``main()`` picks a GL backend."""
    found = subprocess.run(
        [sys.executable, '-c', 'import sys, OpenGLContext.bin.audio_demo; '
         'print("OpenGLContext.testingcontext" in sys.modules)'],
        capture_output=True, text=True, check=True)
    assert found.stdout.strip() == 'False'
    assert 'default context' not in found.stdout + found.stderr
