"""A vehicle's sound as a piece of scene, played through the audio engine.

The behaviour is :mod:`omi_audio.vehicle`'s and is tested there; what is here
is the nodes: one global emitter with a source per voice, the gains and rates
written onto them from the vehicle's own wheels, and a one-shot impact that
plays once per call.
"""
import numpy as np
import pytest
from omi_audio import model
from omi_audio.vehicle import VehicleSoundTuning

from OpenGLContext.audio.vehicle import VehicleSoundtrack

FRAME = 1.0 / 60.0
RATE = 8000


class _Wheel:
    def __init__(self, slip=0.0, grounded=True):
        self.slip, self.grounded = slip, grounded


class _Vehicle:
    """What the soundtrack reads of an ``omi_physics`` ``RaycastVehicle``."""

    def __init__(self, speed=0.0, throttle=0.0, slip=0.0, grounded=True):
        self._speed = speed
        self.throttle = throttle
        self.wheels = [_Wheel(slip, grounded) for _ in range(4)]

    def speed(self):
        return self._speed


@pytest.fixture
def engine():
    from omi_audio.device import NullDevice
    from omi_audio.engine import AudioEngine
    made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=8)
    yield made
    made.close()


def _frame(track, engine, vehicle, now):
    """One frame of a game: the soundtrack read, the node driven, and a
    frame's worth of audio pulled, as a device would."""
    track.update(FRAME, vehicle)
    track.node.updateAudio(engine, np.identity(4), now)
    engine.mixer.mix(int(FRAME * RATE))


class TestItIsAPieceOfScene:
    def test_one_global_emitter_carrying_every_voice(self) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        assert len(track.node.sources) == 4
        assert track.node.type == model.GLOBAL

    def test_driving_writes_the_gains_and_rate_onto_the_nodes(self) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        for _ in range(120):
            track.update(FRAME, _Vehicle(speed=50.0, throttle=1.0, slip=4.0))
        assert track.motor.gain == pytest.approx(track.sound.motor.gain)
        assert track.motor.playbackRate == pytest.approx(track.sound.motor.rate)
        assert track.tyres.gain == pytest.approx(track.sound.tyres.gain)
        assert track.wind.gain == pytest.approx(track.sound.wind.gain)
        assert track.tyres.gain > 0.3

    def test_the_speed_can_be_given_instead(self) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        for _ in range(120):
            track.update(FRAME, _Vehicle(speed=0.0), speed=50.0)
        assert track.sound.wind.gain > 0.1

    def test_a_vehicle_in_the_air_is_read_off_its_wheels(self) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        for _ in range(120):
            track.update(FRAME, _Vehicle(speed=40.0, slip=9.0, grounded=False))
        assert track.tyres.gain == pytest.approx(0.0, abs=1e-3)

    def test_it_sounds_with_the_tuning_it_was_given(self) -> None:
        tuning = VehicleSoundTuning(motor_idle=0.5)
        track = VehicleSoundtrack(tuning, sample_rate=RATE)
        track.update(FRAME, _Vehicle())
        assert track.motor.playbackRate == pytest.approx(0.5)


class TestItPlaysThroughTheEngine:
    def test_the_three_loops_take_a_voice_each(self, engine) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        for step in range(120):
            _frame(track, engine, _Vehicle(speed=30.0), step * FRAME)
        assert engine.active_voices == 3

    def test_an_impact_sounds_once(self, engine) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        _frame(track, engine, _Vehicle(speed=30.0), 0.0)
        assert track.hit(15.0) > 0.0
        _frame(track, engine, _Vehicle(speed=30.0), FRAME)
        assert engine.active_voices == 4, 'the bang did not sound'
        for step in range(2, 400):
            _frame(track, engine, _Vehicle(speed=30.0), step * FRAME)
        assert engine.active_voices == 3

    def test_a_nudge_is_silent(self, engine) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        _frame(track, engine, _Vehicle(speed=30.0), 0.0)
        assert track.hit(0.2) == 0.0
        _frame(track, engine, _Vehicle(speed=30.0), FRAME)
        assert engine.active_voices == 3

    def test_no_engine_is_a_silent_run(self) -> None:
        track = VehicleSoundtrack(sample_rate=RATE)
        track.update(FRAME, _Vehicle(speed=30.0))
        track.node.updateAudio(None, np.identity(4), 0.0)
