"""The physics cannon game's rules, with no window: the kick, the hit and the misses.

``tests/using_physics.py`` leaves every question about the flight to the
physics world, so these fire real shots and read what the world answered.
"""
import functools
import importlib.util
import math
import random
import sys

import pytest

from OpenGLContext.physics.gltf_world import node_mesh
from OpenGLContext.testing.paths import tests_root


def _load():
    path = tests_root(__file__) / 'using_physics.py'
    spec = importlib.util.spec_from_file_location('_using_physics', path)
    module = importlib.util.module_from_spec(spec)
    # A dataclass looks its module up by name to read its annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


game = _load()


def along(bearing, elevation):
    """The unit vector a barrel at ``bearing`` and ``elevation`` degrees points along.

    Bearing 0 is along +x, and a positive bearing turns towards -z.  Written
    from the trigonometry, apart from the cannon's nodes that are checked
    against it.
    """
    turn, rise = math.radians(bearing), math.radians(elevation)
    return (math.cos(turn) * math.cos(rise), math.sin(rise),
            -math.sin(turn) * math.cos(rise))


def aimed_game(seed=1):
    """A course with the cannon turned along the line to the target, at 45 degrees."""
    course = game.Game(random.Random(seed))
    course.aim.bearing = math.degrees(math.atan2(-(course.target.z - course.cannon.z),
                                                 course.target.x - course.cannon.x))
    course.aim.elevation = 45.0
    course.point()
    return course


def shoot(course, power=None, bearing=None):
    """Fire and run the world until the shot is decided; the game's state: ``won`` for a hit."""
    course.state = 'aiming'
    if power is not None:
        course.aim.power = power
    if bearing is not None:
        course.aim.bearing = bearing
    course.point()
    course.fire()
    for _ in range(int(game.LONGEST / 0.05) + 10):
        course.tick(0.05)
        if course.state != 'flying':
            break
    return course.state


@functools.cache
def winning_power(seed=1):
    """The power at which the physics world lands the ball on the target.

    Found by firing, a shot at a time, since the world is what says whether
    one hits.  The same course is played by every test, so it is found once.
    """
    course = aimed_game(seed)
    for tenth in range(100, 400, 2):
        if shoot(course, tenth / 10.0) == 'won':
            return tenth / 10.0
    pytest.fail('no power in range hit the target')


class TestTheKick:
    def test_the_impulse_gives_the_ball_the_power_along_the_barrel(self):
        course = aimed_game()
        course.aim.power = 20.0
        course.fire()
        expected = along(course.aim.bearing, course.aim.elevation)
        velocity = course.world.linear_velocity[course.ball.index]
        assert tuple(velocity) == pytest.approx(tuple(20.0 * part for part in expected),
                                                rel=1e-6)

    def test_the_ball_starts_in_the_mouth_of_the_barrel(self):
        course = aimed_game()
        course.fire()
        assert course.position == pytest.approx(course.muzzle, abs=1e-6)

    def test_the_aim_is_locked_while_the_ball_is_in_the_air(self):
        course = aimed_game()
        course.fire()
        before = course.aim.bearing
        course.adjust(bearing=5)
        assert course.aim.bearing == before

    def test_a_new_shot_takes_the_last_ball_out_of_the_world(self):
        course = aimed_game()
        shoot(course, 12.0)
        before = course.world.live_body_count
        shoot(course, 12.0)
        assert course.world.live_body_count == before


class TestWhatThePhysicsDecides:
    def test_a_ball_that_comes_to_rest_over_the_target_is_a_hit(self):
        course = aimed_game()
        assert shoot(course, winning_power()) == 'won'

    def test_too_little_power_is_a_miss(self):
        assert shoot(aimed_game(), winning_power() - 3.0) == 'aiming'

    def test_too_much_power_is_a_miss(self):
        assert shoot(aimed_game(), winning_power() + 4.0) == 'aiming'

    @pytest.mark.parametrize('turn', [8.0, -8.0])
    def test_a_bearing_to_either_side_is_a_miss(self, turn):
        course = aimed_game()
        power = winning_power()
        assert shoot(course, power, course.aim.bearing + turn) == 'aiming'

    def test_a_miss_allows_another_shot(self):
        course = aimed_game()
        assert shoot(course, 8.0) == 'aiming'
        course.fire()
        assert course.state == 'flying'

    def test_a_ball_fired_into_its_own_tower_is_a_miss(self):
        course = aimed_game()
        course.aim.elevation = -10.0
        assert shoot(course, 10.0) == 'aiming'

    def test_a_ball_that_leaves_the_world_ends_the_shot(self):
        course = aimed_game()
        course.world.gravity.gravity = 0.0
        assert shoot(course, 40.0, 0.0) == 'aiming'

    def test_the_next_fire_after_a_win_lays_out_a_new_course(self):
        course = aimed_game()
        shoot(course, winning_power())
        old = course.target
        course.fire()
        assert course.state == 'aiming'
        assert course.target != old


class TestTheScene:
    def test_the_world_is_geometry_before_it_is_physics(self):
        course = game.build_course(random.Random(5), game.looks())
        assert len(course.solids) == 3          # the ground and the two towers
        assert len(course.nodes) == 6           # and the target's mark and the cannon
        assert node_mesh(course.pad) is not None

    def test_the_courses_nodes_are_bodies_in_the_world(self):
        course = aimed_game()
        bound = {body.transform for body in course.manager.bodies}
        assert set(course.course.solids) <= bound
        assert course.course.pad in bound
        assert course.course.pad not in course.course.nodes

    def test_the_bodies_write_their_poses_onto_the_nodes(self):
        course = aimed_game()
        course.fire()
        start = tuple(course.ball.transform.translation)
        course.tick(0.5)
        assert tuple(course.ball.transform.translation) != start

    def test_a_hit_calls_on_success_and_a_miss_on_failure(self):
        heard = []
        course = aimed_game()
        course.on_success = lambda: heard.append('success')
        course.on_failure = lambda: heard.append('failure')
        shoot(course, 8.0)
        shoot(course, winning_power())
        assert heard == ['failure', 'success']


class TestTheHitSlab:
    """The trigger is a few centimetres over the target's top and 30 cm deep."""

    def test_the_slab_stands_5_cm_over_the_top_and_reaches_30_cm_down(self):
        course = aimed_game()
        low, high = node_mesh(course.course.pad)[0].min(axis=0), node_mesh(course.course.pad)[0].max(axis=0)
        centre = course.course.pad.translation
        top = course.target.top
        assert centre[1] + high[1] == pytest.approx(top + game.PAD_ABOVE, abs=1e-5)
        assert centre[1] + low[1] == pytest.approx(top - game.PAD_DEPTH, abs=1e-5)
        assert tuple(high - low)[0] == pytest.approx(2 * game.TARGET_HALF)

    def drop_at(self, height_over_top):
        """A ball with no gravity, put at a height over the target's top; was it a hit?"""
        course = aimed_game()
        course.world.gravity.gravity = 0.0
        course.state = 'flying'
        node = game.surfaces.shape(game.surfaces.sphere(game.BALL_RADIUS), course.look['steel'],
                                   translation=(course.target.x,
                                                course.target.top + height_over_top,
                                                course.target.z))
        course.ball = course.manager.attach(
            node, game.model.Motion(type=game.model.DYNAMIC, mass=game.BALL_MASS),
            strategy='primitive')
        for _ in range(10):
            course.manager.advance(1 / 60)
        return course.state == 'won'

    def test_a_ball_resting_on_the_target_is_a_hit(self):
        assert self.drop_at(game.BALL_RADIUS)

    def test_a_ball_20_cm_clear_of_the_top_is_not(self):
        assert not self.drop_at(game.BALL_RADIUS + game.PAD_ABOVE + 0.20)


class TestTheReport:
    RATE = 8000

    @pytest.fixture
    def engine(self):
        from omi_audio.device import NullDevice
        from omi_audio.engine import AudioEngine
        made = AudioEngine(device=NullDevice(sample_rate=self.RATE), voices=8)
        yield made
        made.close()

    def test_the_report_is_a_boom_that_dies_away(self):
        clip = game.Report(self.RATE).clip
        assert clip.sample_rate == self.RATE
        assert len(clip.samples) / self.RATE > 0.9
        assert float(abs(clip.samples).max()) <= 1.0
        loud = float(abs(clip.samples[:self.RATE // 10]).max())
        late = float(abs(clip.samples[-self.RATE // 10:]).max())
        assert late < 0.3 * loud

    def test_playing_the_report_starts_a_voice_in_the_engine(self, engine):
        report = game.Report(self.RATE)
        assert report.play(engine, (0.0, 3.0, 0.0)) is not None
        engine.mixer.mix(self.RATE // 10)
        assert engine.mixer.active_voices > 0

    def test_a_report_with_no_engine_is_silence_and_no_error(self):
        assert game.Report(self.RATE).play(None, (0.0, 0.0, 0.0)) is None


class TestTheLimitOnShots:
    def miss(self, course):
        shoot(course, 8.0)

    def test_each_shot_uses_one(self):
        course = aimed_game()
        assert course.shots_left == game.MAX_SHOTS
        self.miss(course)
        assert course.shots_left == game.MAX_SHOTS - 1

    def test_the_tenth_miss_loses_the_game(self):
        heard = []
        course = aimed_game()
        course.on_game_over = lambda: heard.append('over')
        for _ in range(game.MAX_SHOTS - 1):
            self.miss(course)
            assert course.state == 'aiming'
        self.miss(course)
        assert course.state == 'lost'
        assert heard == ['over']

    def test_a_lost_game_takes_no_more_shots_until_space_starts_the_next(self):
        course = aimed_game()
        for _ in range(game.MAX_SHOTS):
            self.miss(course)
        old = course.target
        course.fire()
        assert course.state == 'aiming'
        assert course.target != old
        assert course.shots_left == game.MAX_SHOTS

    def test_a_hit_on_the_last_shot_wins(self):
        course = aimed_game()
        for _ in range(game.MAX_SHOTS - 1):
            self.miss(course)
        shoot(course, winning_power())
        assert course.state == 'won'

    def test_a_win_does_not_call_game_over(self):
        heard = []
        course = aimed_game()
        course.on_game_over = lambda: heard.append('over')
        shoot(course, winning_power())
        assert heard == []


class TestTheCannonsFrames:
    """The barrel's direction, its mouth and the camera all come from the nodes."""

    ANGLES = [(0, 0), (25, 40), (-35, 70), (50, -10)]

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_barrel_points_where_the_bearing_and_elevation_say(self, bearing, elevation):
        gun = game.build_course(random.Random(2), game.looks()).gun
        gun.aim(bearing, elevation)
        assert tuple(gun.along) == pytest.approx(along(bearing, elevation), abs=1e-6)

    def test_the_camera_is_30_cm_to_the_right_of_the_barrel(self):
        gun = game.build_course(random.Random(2), game.looks()).gun
        gun.aim(0, 0)                  # barrel along +x, so its right is +z
        eye = gun.to_world(game.EYE)
        pivot = gun.turn.translation
        assert eye[2] - pivot[2] == pytest.approx(0.3, abs=1e-6)

    def test_one_cannon_aimed_again_and_again_follows_each_aim(self):
        """The paths keep their matrices until a rotation above them changes."""
        gun = game.build_course(random.Random(2), game.looks()).gun
        for bearing, elevation in self.ANGLES + self.ANGLES[::-1]:
            gun.aim(bearing, elevation)
            assert tuple(gun.along) == pytest.approx(along(bearing, elevation), abs=1e-6)
            assert gun.eye_path.quaternion().XYZR() is not None

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_muzzle_is_a_barrel_length_from_the_pivot(self, bearing, elevation):
        gun = game.build_course(random.Random(2), game.looks()).gun
        gun.aim(bearing, elevation)
        pivot = gun.turn.translation
        expected = tuple(p + game.BARREL * d
                         for p, d in zip(pivot, along(bearing, elevation)))
        assert tuple(gun.muzzle) == pytest.approx(expected, abs=1e-5)

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_camera_stands_behind_the_pivot_and_looks_along_the_barrel(
            self, bearing, elevation):
        gun = game.build_course(random.Random(2), game.looks()).gun
        gun.aim(bearing, elevation)

        class Platform:
            position = None
            orientation = None

            def setPosition(self, position):
                self.position = tuple(position)[:3]

            def setOrientation(self, orientation):
                self.orientation = tuple(orientation)

            def setFrustum(self, *arguments):
                pass

        class Context:
            platform = Platform()

        gun.look_through(Context)
        behind = tuple(a - b for a, b in zip(Context.platform.position, gun.turn.translation))
        assert sum(x * d for x, d in zip(behind, along(bearing, elevation))) < 0
        # The orientation is a VRML97 one: a turn that takes the camera's -z to where it looks.
        x, y, z, angle = Context.platform.orientation
        sees = (0.0, 0.0, -1.0)
        dot = x * sees[0] + y * sees[1] + z * sees[2]
        cross = (y * sees[2] - z * sees[1], z * sees[0] - x * sees[2], x * sees[1] - y * sees[0])
        looking = tuple(sees[i] * math.cos(angle) + cross[i] * math.sin(angle)
                        + (x, y, z)[i] * dot * (1 - math.cos(angle)) for i in range(3))
        assert looking == pytest.approx(along(bearing, elevation), abs=1e-6)
