"""The cannon-ball game's rules, with no window: the parabola, the verdicts and the turn.

``tests/using_animation.py`` keeps its rules in plain classes so a shot can be
worked out and checked here.
"""
import importlib.util
import math
import random

import pytest

from OpenGLContext.testing.paths import tests_root


def _load():
    path = tests_root(__file__) / 'using_animation.py'
    spec = importlib.util.spec_from_file_location('_using_animation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


game = _load()

SOURCE = game.Platform(-12.0, 0.0, 3.0)
TARGET = game.Platform(12.0, 0.0, 3.0)


def shot(bearing=0.0, elevation=45.0, power=15.0, source=SOURCE, target=TARGET):
    start = (source.x, source.top + 1.0, source.z)
    velocity = tuple(power * part for part in game.direction(bearing, elevation))
    return game.fly(start, velocity, source, target)


def power_for_range(distance, elevation=45.0):
    """The speed that carries a ball ``distance`` metres on level ground."""
    return math.sqrt(distance * game.GRAVITY / math.sin(2 * math.radians(elevation)))


class TestParabola:
    def test_the_path_is_the_equation_of_motion(self):
        flight = shot()
        velocity = tuple(15.0 * part for part in game.direction(0.0, 45.0))
        for t in (0.5, 1.0, 1.5):
            x, y, z = flight.at(t)
            assert x == pytest.approx(-12.0 + velocity[0] * t, abs=1e-3)
            assert y == pytest.approx(4.0 + velocity[1] * t - game.GRAVITY * t * t / 2, abs=1e-3)
            assert z == pytest.approx(0.0, abs=1e-6)

    def test_a_positive_bearing_turns_to_the_left(self):
        assert game.direction(30.0, 0.0)[2] < 0.0

    def test_the_ball_is_where_the_flight_ends_when_time_runs_past_it(self):
        flight = shot()
        assert flight.at(flight.duration + 5.0) == flight.points[-1]


class TestVerdicts:
    def test_a_ball_coming_down_on_the_target_wins(self):
        flight = shot(power=power_for_range(24.0, 45.0) * 0.99)
        assert flight.verdict.kind == 'hit'
        assert flight.verdict.won

    def test_the_ball_comes_to_rest_on_top_of_the_target(self):
        flight = shot(power=power_for_range(24.0, 45.0) * 0.99)
        assert flight.points[-1][1] == pytest.approx(TARGET.top + game.BALL_RADIUS)

    def test_too_little_power_is_short_by_the_distance_to_the_edge(self):
        verdict = shot(power=power_for_range(14.0)).verdict
        assert verdict.kind == 'short'
        assert verdict.distance == pytest.approx(4.4, abs=0.2)

    def test_too_much_power_is_past(self):
        verdict = shot(power=power_for_range(40.0)).verdict
        assert verdict.kind == 'past'
        assert verdict.distance > 5.0

    def test_a_bearing_to_the_left_is_left(self):
        verdict = shot(bearing=8.0, power=power_for_range(24.0)).verdict
        assert verdict.kind == 'left'

    def test_a_bearing_to_the_right_is_right(self):
        verdict = shot(bearing=-8.0, power=power_for_range(24.0)).verdict
        assert verdict.kind == 'right'

    def test_left_and_right_follow_the_line_between_offset_towers(self):
        source = game.Platform(-12.0, -4.0, 3.0)
        target = game.Platform(12.0, 4.0, 3.0)
        aimed = math.degrees(math.atan2(-8.0, 24.0))     # the bearing along the line
        power = power_for_range(math.hypot(24.0, 8.0))
        assert shot(aimed + 8.0, power=power, source=source, target=target).verdict.kind == 'left'
        assert shot(aimed - 8.0, power=power, source=source, target=target).verdict.kind == 'right'
        assert shot(aimed, power=power * 0.99, source=source, target=target).verdict.won

    def test_a_ball_that_reaches_the_ground_ends_the_flight(self):
        flight = shot(elevation=0.0, power=12.0)
        assert flight.points[-1][1] == pytest.approx(game.BALL_RADIUS)

    def test_a_ball_that_strikes_the_side_of_the_target_is_short(self):
        high = game.Platform(12.0, 0.0, 6.0)
        verdict = shot(elevation=10.0, power=power_for_range(24.0, 10.0), target=high).verdict
        assert verdict.kind == 'short'

    def test_a_ball_into_its_own_tower_is_short(self):
        assert shot(elevation=-10.0, power=10.0).verdict.kind == 'short'

    def test_the_message_names_the_miss_and_its_size(self):
        assert game.Verdict('past', 3.14).message() == 'Past by 3.1 m'
        assert 'hit' in game.Verdict('hit').message().lower()


class TestAim:
    def test_adjusting_stays_within_the_limits(self):
        aim = game.Aim()
        aim.adjust(bearing=500, elevation=500, power=500)
        assert (aim.bearing, aim.elevation, aim.power) == (
            game.BEARING_LIMIT[1], game.ELEVATION_LIMIT[1], game.POWER_LIMIT[1])
        aim.adjust(bearing=-500, elevation=-500, power=-500)
        assert (aim.bearing, aim.elevation, aim.power) == (
            game.BEARING_LIMIT[0], game.ELEVATION_LIMIT[0], game.POWER_LIMIT[0])

    @pytest.mark.parametrize('bearing, elevation', [(0, 0), (25, 40), (-35, 70), (50, -10)])
    def test_the_camera_looks_along_the_barrel(self, bearing, elevation):
        position, orientation = game.barrel_camera((0, 0, 0), bearing, elevation)
        axis, angle = orientation[:3], orientation[3]
        # A camera looks along -z; Rodrigues' rotation of that by the orientation.
        z = (0.0, 0.0, -1.0)
        dot = sum(a * b for a, b in zip(axis, z))
        cross = (axis[1] * z[2] - axis[2] * z[1], axis[2] * z[0] - axis[0] * z[2],
                 axis[0] * z[1] - axis[1] * z[0])
        looking = tuple(z[i] * math.cos(angle) + cross[i] * math.sin(angle)
                        + axis[i] * dot * (1 - math.cos(angle)) for i in range(3))
        assert looking == pytest.approx(game.direction(bearing, elevation), abs=1e-6)
        # ... from behind the pivot and above the barrel.
        assert sum(p * d for p, d in zip(position, game.direction(bearing, elevation))) < 0


class TestGame:
    def make(self):
        return game.Game(random.Random(7))

    def test_a_course_puts_the_towers_apart_at_varied_heights(self):
        seen = set()
        for seed in range(20):
            course = game.Game(random.Random(seed))
            assert 40 <= course.target.x - course.cannon.x <= 70
            assert 2.0 <= course.cannon.top <= 5.0 and 1.0 <= course.target.top <= 8.0
            seen.add((round(course.cannon.top, 2), round(course.target.z, 2)))
        assert len(seen) == 20

    def test_the_opening_aim_is_nowhere_near_a_hit(self):
        for seed in range(20):
            course = game.Game(random.Random(seed))
            course.fire()
            assert not course.flight.verdict.won
            assert course.flight.verdict.distance > 15.0

    def test_firing_flies_the_ball_and_a_miss_allows_another_shot(self):
        course = self.make()
        course.aim.power = game.POWER_LIMIT[0]
        course.fire()
        assert course.state == 'flying'
        course.tick(60.0)
        assert course.state == 'aiming'
        assert course.message.startswith('Short')
        course.fire()
        assert course.state == 'flying'

    def test_the_aim_is_locked_while_the_ball_is_in_the_air(self):
        course = self.make()
        course.fire()
        before = course.aim.bearing
        course.adjust(bearing=5)
        assert course.aim.bearing == before

    def test_a_hit_wins_and_the_next_fire_lays_out_a_new_course(self):
        course = self.make()
        distance = math.hypot(course.target.x - course.cannon.x,
                              course.target.z - course.cannon.z)
        course.aim.bearing = math.degrees(math.atan2(-(course.target.z - course.cannon.z),
                                                     course.target.x - course.cannon.x))
        course.aim.elevation = 45.0
        course.aim.power = power_for_range(distance) * 1.0
        # Search the power for a hit; the arithmetic is the game's own.
        for push in range(-30, 31):
            course.state, course.flight = 'aiming', None
            course.aim.power = min(max(power_for_range(distance) + push * 0.1, 5.0), 40.0)
            course.fire()
            if course.flight.verdict.won:
                break
        else:
            pytest.fail('no power in range hit the target')
        course.tick(60.0)
        assert course.state == 'won'
        old = course.target
        course.fire()
        assert course.state == 'aiming'
        assert course.target != old

    def test_the_ball_waits_in_the_mouth_of_the_barrel(self):
        course = self.make()
        assert course.ball == course.muzzle

    def test_the_bounds_hold_both_towers(self):
        course = self.make()
        low, high = course.bounds()
        for tower in (course.cannon, course.target):
            assert low[0] <= tower.x - tower.half and tower.x + tower.half <= high[0]
            assert low[2] <= tower.z - tower.half and tower.z + tower.half <= high[2]
            assert high[1] > tower.top
