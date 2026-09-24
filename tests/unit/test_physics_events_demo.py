"""``oglc-physics-events``' yard, driven the way the demo drives it.

The yard holds the whole demo and no GL: crates that thud, two panes of glass
that break two different ways, a hitscan gun and a pressure plate that opens a
door. Each is tested here with a silent sound device and no window.
"""
import numpy as np
import pytest

from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine

from OpenGLContext.bin import physics_events_demo as demo
from OpenGLContext.bin.physics_events_demo import CollisionYard

FRAME = 1.0 / 60.0
RATE = 8000


@pytest.fixture
def engine():
    made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=64)
    yield made
    made.close()


@pytest.fixture
def yard():
    return CollisionYard(sample_rate=RATE)


def run(yard, engine, seconds, frame=FRAME):
    """Frames of the demo; the sounds each started, by name."""
    heard = []
    for _ in range(max(1, round(seconds / frame))):
        heard += yard.step(frame, engine)
        if engine is not None:
            engine.mixer.mix(int(frame * RATE))
    return heard


class TestCrates:
    def test_dropped_crates_thud(self, yard, engine):
        yard.drop()
        assert run(yard, engine, 3.0).count('thud') >= len(demo.CRATE_SPOTS)

    def test_resting_crates_are_quiet(self, yard, engine):
        yard.drop()
        run(yard, engine, 8.0)
        assert 'thud' not in run(yard, engine, 2.0)

    def test_a_slow_frame_rate_hears_every_landing(self, engine):
        def thuds(frame):
            yard = CollisionYard(sample_rate=RATE)
            yard.drop()
            return run(yard, engine, 4.0, frame).count('thud')

        assert thuds(1.0 / 20.0) == thuds(1.0 / 120.0)

    def test_the_frame_cap_toggles(self, yard):
        assert yard.frame_cap is None
        assert yard.toggle_cap() == demo.CAPPED_FRAME
        assert yard.toggle_cap() is None


class TestPanes:
    def test_the_blow_breaks_both_panes(self, yard, engine):
        yard.launch()
        heard = run(yard, engine, 1.5)
        assert heard.count('shatter') == 2
        assert yard.broken == {'after', 'before'}
        assert len(yard.fragments) == 2 * demo.FRAGMENTS

    def test_a_pane_broken_after_the_solve_turned_the_ball(self, yard, engine):
        yard.launch()
        run(yard, engine, 1.5)
        ball = yard.balls['after']
        assert yard.world.linear_velocity[ball.index][2] > -1.0

    def test_a_pane_broken_before_the_solve_let_it_through(self, yard, engine):
        yard.launch()
        run(yard, engine, 0.4)
        assert 'before' in yard.broken
        ball = yard.balls['before']
        assert yard.world.linear_velocity[ball.index][2] < -0.8 * demo.LAUNCH_SPEED
        assert yard.world.position[ball.index][2] < demo.PANE_Z - 1.0

    def test_a_gentle_ball_does_not_break_them(self, yard, engine):
        yard.launch(speed=1.0)
        heard = run(yard, engine, 3.0)
        assert 'shatter' not in heard
        assert yard.broken == set()

    def test_mending_puts_them_back(self, yard, engine):
        yard.launch()
        run(yard, engine, 1.5)
        yard.mend()
        assert yard.broken == set()
        assert yard.fragments == []
        yard.launch()
        assert run(yard, engine, 1.5).count('shatter') == 2


class TestGun:
    def test_a_shot_pushes_the_crate_it_hits(self, yard, engine):
        run(yard, engine, 0.5)
        crate = yard.crates[0]
        x, y, z = yard.world.position[crate.index]
        hit = yard.fire((x, y, z + 6.0), (0, 0, -1))
        assert hit is crate
        heard = run(yard, engine, FRAME)
        assert heard == ['ping']
        assert yard.world.linear_velocity[crate.index][2] < -0.5

    def test_a_shot_at_nothing_hits_nothing(self, yard, engine):
        assert yard.fire((0, 20, 0), (0, 1, 0)) is None


class TestPlate:
    def test_weight_on_the_plate_opens_the_door(self, yard, engine):
        closed = yard.door_height()
        yard.toggle_weight()
        run(yard, engine, 3.0)
        assert yard.plate_pressed
        assert yard.door_height() == pytest.approx(closed + demo.DOOR_TRAVEL, abs=0.01)

    def test_lifting_it_closes_the_door(self, yard, engine):
        closed = yard.door_height()
        yard.toggle_weight()
        run(yard, engine, 3.0)
        yard.toggle_weight()
        run(yard, engine, 3.0)
        assert not yard.plate_pressed
        assert yard.door_height() == pytest.approx(closed, abs=0.01)


def test_it_runs_without_a_sound_device(yard):
    yard.drop()
    assert 'thud' in run(yard, None, 2.0)


def test_the_scene_has_every_body(yard):
    scene = yard.scene()
    assert scene is not None
    assert np.isfinite(yard.world.position).all()
