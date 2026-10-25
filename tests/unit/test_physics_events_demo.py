"""``oglc-physics-events``' yard, driven the way the demo drives it.

The yard holds the whole demo and no GL: crates that thud, two panes of glass
that break two different ways, a hitscan gun and a pressure plate that opens a
door. Each is tested here on a standalone inline physics service and a
recording audio, with no window and no sound device.
"""
import numpy as np
import pytest

from OpenGLContext.audio.manager import Audio
from OpenGLContext.audio.settings import AudioSettings
from OpenGLContext.bin import physics_events_demo as demo
from OpenGLContext.bin.physics_events_demo import CollisionYard
from OpenGLContext.physics.service import Physics
from OpenGLContext.testing.audio import RecordingAudio

FRAME = 1.0 / 60.0
RATE = 8000


@pytest.fixture
def audio():
    return RecordingAudio()


@pytest.fixture
def yard(audio):
    physics = Physics(demo.definition())
    made = CollisionYard(physics, audio, sample_rate=RATE)
    yield made
    physics.close()


def heard(yard, audio):
    """The names of the sounds played so far, in order."""
    return [next(name for name, clip in yard.clips.items() if clip is call.source)
            for call in audio.plays]


def run(yard, audio, seconds, frame=FRAME):
    """Frames of the demo, as the context's frame hook gives them; the names of the sounds each started."""
    before = len(audio.plays)
    for _ in range(max(1, round(seconds / frame))):
        yard.physics.frame(frame)
    return heard(yard, audio)[before:]


class TestCrates:
    def test_dropped_crates_thud(self, yard, audio):
        yard.drop()
        assert run(yard, audio, 3.0).count('thud') >= len(demo.CRATE_SPOTS)

    def test_resting_crates_are_quiet(self, yard, audio):
        yard.drop()
        run(yard, audio, 8.0)
        assert 'thud' not in run(yard, audio, 2.0)

    def test_a_slow_frame_rate_hears_every_landing(self):
        def thuds(frame):
            audio = RecordingAudio()
            physics = Physics(demo.definition())
            yard = CollisionYard(physics, audio, sample_rate=RATE)
            yard.drop()
            count = run(yard, audio, 4.0, frame).count('thud')
            physics.close()
            return count

        assert thuds(1.0 / 20.0) == thuds(1.0 / 120.0)

    def test_the_frame_cap_toggles(self, yard):
        assert yard.frame_cap is None
        assert yard.toggle_cap() == demo.CAPPED_FRAME
        assert yard.toggle_cap() is None

    def test_a_thud_is_placed_where_the_crate_struck_and_louder_for_a_harder_landing(self, yard, audio):
        yard.drop()
        run(yard, audio, 3.0)
        thuds = [call for call in audio.plays if call.source is yard.clips['thud']]
        assert all(0.0 < call.gain <= 1.0 for call in thuds)
        assert all(call.emitter is yard.placed for call in thuds)
        assert all(-0.5 < call.at[1] < 1.5 for call in thuds)
        assert max(call.gain for call in thuds) > min(call.gain for call in thuds)


class TestPanes:
    def test_the_blow_breaks_both_panes(self, yard, audio):
        yard.launch()
        sounds = run(yard, audio, 1.5)
        assert sounds.count('shatter') == 2
        assert yard.broken == {'after', 'before'}
        assert len(yard.fragments) == 2 * demo.FRAGMENTS

    def test_a_pane_broken_after_the_solve_turned_the_ball(self, yard, audio):
        yard.launch()
        run(yard, audio, 1.5)
        assert yard.balls['after'].velocity[2] > -1.0

    def test_a_pane_broken_before_the_solve_let_it_through(self, yard, audio):
        yard.launch()
        run(yard, audio, 0.4)
        assert 'before' in yard.broken
        ball = yard.balls['before']
        assert ball.velocity[2] < -0.8 * demo.LAUNCH_SPEED
        assert ball.position[2] < demo.PANE_Z - 0.5

    def test_a_gentle_ball_does_not_break_them(self, yard, audio):
        yard.launch(speed=1.0)
        sounds = run(yard, audio, 3.0)
        assert 'shatter' not in sounds
        assert yard.broken == set()

    def test_mending_puts_them_back(self, yard, audio):
        yard.launch()
        run(yard, audio, 1.5)
        yard.mend()
        assert yard.broken == set()
        assert yard.fragments == []
        yard.launch()
        assert run(yard, audio, 1.5).count('shatter') == 2


class TestGun:
    def test_a_shot_pushes_the_crate_it_hits(self, yard, audio):
        run(yard, audio, 0.5)
        crate = yard.crates[0]
        x, y, z = crate.position
        hit = yard.fire((x, y, z + 6.0), (0, 0, -1))
        assert hit is crate
        assert heard(yard, audio) == ['ping']                   # it pings in the call
        run(yard, audio, FRAME)
        assert crate.velocity[2] < -0.5

    def test_a_shot_at_nothing_hits_nothing(self, yard):
        assert yard.fire((0, 20, 0), (0, 1, 0)) is None

    def test_a_shot_at_the_floor_is_not_a_ping(self, yard, audio):
        run(yard, audio, 0.5)
        assert yard.fire((9.0, 3.0, 9.0), (0, -1, 0)) is not None
        assert heard(yard, audio) == []


class TestPlate:
    def test_weight_on_the_plate_opens_the_door(self, yard, audio):
        closed = yard.door_height()
        yard.toggle_weight()
        run(yard, audio, 3.0)
        assert yard.plate_pressed
        assert yard.door_height() == pytest.approx(closed + demo.DOOR_TRAVEL, abs=0.01)

    def test_lifting_it_closes_the_door(self, yard, audio):
        closed = yard.door_height()
        yard.toggle_weight()
        run(yard, audio, 3.0)
        yard.toggle_weight()
        run(yard, audio, 3.0)
        assert not yard.plate_pressed
        assert yard.door_height() == pytest.approx(closed, abs=0.01)


def test_it_runs_with_the_sound_switched_off():
    physics = Physics(demo.definition())
    silent = Audio(settings=AudioSettings(enabled=False))
    yard = CollisionYard(physics, silent, sample_rate=RATE)
    yard.drop()
    for _ in range(120):
        physics.frame(FRAME)
    assert yard.crates[0].position[1] < 2.0
    physics.close()


def test_the_scene_has_every_body(yard):
    scene = yard.scene()
    assert scene is not None
    yard.physics.frame(FRAME)
    assert all(np.isfinite(body.position).all() for body in (*yard.crates, yard.weight, yard.door))
