"""The physics cannon game's rules, with no window: the balls, the courses and the score.

``tests/using_physics.py`` leaves every question about the flight to the
physics world, so these fire real shots and read what the world answered.
"""
import importlib.util
import math
import random
import sys

import numpy as np
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

#: The ball kinds, and the levels by what is in them.
BALLS = [ammo.name for ammo in game.AMMO]
OPEN, WALL, CRATES, CROSSWIND, FERRY, PORTCULLIS = range(6)

#: The shots that win each course, for ``Game(random.Random(1), level=n)``, in
#: the order they are fired: the ball, the bearing as an offset from straight
#: at the target, the elevation, the power and the seconds to wait before
#: firing.  Each power is in the middle of a run of powers that win, found by
#: ``find_shot`` below.  The crates cover the mark on course 3, so a lead ball
#: clears them for the steel one.  When the physics changes enough to move
#: them, ``find_shot`` finds new ones.
SOLUTIONS: dict[int, list[tuple[str, float, float, float, float]]] = {
    OPEN: [('steel', 0.0, 45.0, 22.913, 0.0)],
    WALL: [('steel', 0.0, 45.0, 22.913, 0.0)],
    CRATES: [('lead', 0.0, 45.0, 22.86, 0.0), ('steel', 0.0, 45.0, 22.86, 0.0)],
    CROSSWIND: [('steel', 1.0, 30.0, 24.42, 0.0)],
    FERRY: [('steel', 0.0, 30.0, 23.96, 2.0)],
    PORTCULLIS: [('steel', 1.0, 30.0, 24.4, 3.0)],
}


def along(bearing, elevation):
    """The unit vector a barrel at ``bearing`` and ``elevation`` degrees points along.

    Bearing 0 is along +x, and a positive bearing turns towards -z.  Written
    from the trigonometry, apart from the cannon's nodes that are checked
    against it.
    """
    turn, rise = math.radians(bearing), math.radians(elevation)
    return (math.cos(turn) * math.cos(rise), math.sin(rise),
            -math.sin(turn) * math.cos(rise))


def toward_target(course):
    """The bearing that points the cannon at the foot of the target."""
    return math.degrees(math.atan2(-(course.target.z - course.cannon.z),
                                   course.target.x - course.cannon.x))


def aimed_game(seed=1, level=OPEN, ammo='steel'):
    """A course with the cannon turned along the line to the target, at 45 degrees."""
    course = game.Game(random.Random(seed), level=level)
    course.select(ammo)
    course.aim.bearing = toward_target(course)
    course.aim.elevation = 45.0
    course.point()
    return course


def shoot(course, power=None, bearing=None, ammo=None, elevation=None, wait=0.0):
    """Fire after ``wait`` seconds and run the world until the shot is decided.

    The game's state is ``cleared`` for a hit.  Waiting is how a shot is
    timed against a sliding target or a gate.
    """
    course.state = 'aiming'
    for _ in range(round(wait * 20)):
        course.tick(0.05)
    if ammo is not None:
        course.select(ammo)
    for name, value in (('power', power), ('bearing', bearing), ('elevation', elevation)):
        if value is not None:
            setattr(course.aim, name, value)
    course.point()
    course.fire()
    for _ in range(int(game.LONGEST / 0.05) + 10):
        if course.state != 'flying':
            break
        course.tick(0.05)
    return course.state


def vacuum_power(course, elevation):
    """The power that would land a ball on the target if the air and the hazards were not there."""
    horizontal = math.hypot(course.target.x - course.cannon.x, course.target.z - course.cannon.z)
    rise = course.target.top + game.BALL_RADIUS - course.muzzle[1]
    angle = math.radians(elevation)
    room = 2.0 * math.cos(angle) ** 2 * (horizontal * math.tan(angle) - rise)
    return math.sqrt(9.81 * horizontal ** 2 / room)


def find_shot(seed, level, ammo='steel', elevation=45.0, offset=0.0, wait=0.0,
              spread=1.5, step=0.1):
    """Every power near the vacuum one that wins, found by firing.

    The bearing is ``offset`` degrees from straight at the target, and the
    shot is fired after ``wait`` seconds.
    """
    probe = aimed_game(seed, level, ammo)
    centre = vacuum_power(probe, elevation)
    wins = []
    for index in range(int(2 * spread / step) + 1):
        power = centre - spread + index * step
        course = aimed_game(seed, level, ammo)
        outcome = shoot(course, power, course.aim.bearing + offset, elevation=elevation,
                        wait=wait)
        if outcome in ('cleared', 'finished'):
            wins.append(round(power, 3))
    return wins


def winning_power():
    """The power at which the physics world lands the ball on the open course's target."""
    return SOLUTIONS[OPEN][0][3]


def put(course, point):
    """Stand the ball at ``point`` with no velocity."""
    index = course.ball.index
    course.world.place_body(index, position=point)
    course.world.linear_velocity[index] = 0.0


class TestTheKick:
    @pytest.mark.parametrize('ammo', BALLS)
    def test_the_impulse_gives_every_ball_the_power_along_the_barrel(self, ammo):
        course = aimed_game(ammo=ammo)
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

    def test_the_aim_can_be_adjusted_while_the_ball_is_in_the_air(self):
        course = aimed_game()
        course.fire()
        before = course.aim.bearing
        course.adjust(bearing=5)
        course.set_aim('power', 30.0)
        assert course.aim.bearing == before + 5
        assert course.aim.power == 30.0
        assert tuple(course.course.gun.along) == pytest.approx(
            along(course.aim.bearing, course.aim.elevation), abs=1e-6)

    def test_adjusting_the_aim_does_not_change_the_ball_in_the_air(self):
        course = aimed_game()
        course.fire()
        velocity = tuple(course.world.linear_velocity[course.ball.index])
        course.adjust(bearing=5, elevation=10, power=10)
        assert tuple(course.world.linear_velocity[course.ball.index]) == velocity
        assert course.state == 'flying'

    def test_the_ball_selected_in_flight_is_the_next_one_fired(self):
        course = aimed_game(level=WALL)
        course.fire()
        course.select('rubber')
        shoot(course, 8.0)
        course.fire()
        assert course.flying.name == 'rubber'

    def test_firing_sends_a_ball_and_says_so(self):
        course = aimed_game()
        assert course.fire() is True
        assert course.state == 'flying'

    def test_nothing_is_fired_while_a_ball_is_in_the_air(self):
        heard = []
        course = aimed_game()
        course.fire()
        ball, left = course.ball, dict(course.stock)
        course.on_event = lambda kind, detail=None: heard.append(kind)
        for _ in range(3):
            assert course.fire() is False
        assert course.ball is ball and course.stock == left
        assert heard == []
        assert course.message == 'Wait for the ball to land.'

    def test_the_next_ball_can_be_fired_once_the_last_has_settled(self):
        course = aimed_game()
        assert shoot(course, 8.0) == 'aiming'
        assert course.fire() is True

    def test_a_ball_far_beyond_the_area_ends_the_shot(self):
        course = aimed_game()
        course.world.gravity.gravity = 0.0
        assert shoot(course, 40.0, 0.0, elevation=0.0) == 'aiming'
        assert course.elapsed < game.LONGEST / 2.0
        assert course.course.beyond(course.position)

    def test_a_ball_within_the_margin_beyond_the_area_is_still_flying(self):
        course = aimed_game()
        low, high = course.course.bounds()
        assert not course.course.beyond((high[0] + game.FAR - 1.0, 0.0, 0.0))
        assert course.course.beyond((high[0] + game.FAR + 1.0, 0.0, 0.0))
        assert course.course.beyond((0.0, 0.0, low[2] - game.FAR - 1.0))
        assert not course.course.beyond((0.0, high[1] + 500.0, 0.0))

    def test_a_new_shot_takes_the_last_ball_out_of_the_world(self):
        course = aimed_game()
        shoot(course, 12.0)
        before = course.world.live_body_count
        shoot(course, 12.0)
        assert course.world.live_body_count == before


class TestTheBalls:
    def test_the_three_kinds_are_light_and_bouncy_through_to_heavy_and_dead(self):
        steel, rubber, lead = (game.AMMO_BY_NAME[name] for name in ('steel', 'rubber', 'lead'))
        assert rubber.mass < steel.mass < lead.mass
        assert rubber.material.restitution > steel.material.restitution > lead.material.restitution

    def test_each_kind_has_a_key_and_a_look(self):
        assert list(game.SELECT_KEYS.values()) == BALLS
        assert all(ammo.look in game.looks() for ammo in game.AMMO)

    def hops(self, ammo, onto='ground'):
        """How high a ball dropped from 6 m rises after its first bounce, in metres."""
        course = aimed_game(level=FERRY, ammo=ammo)
        course.fire()
        spot = course.body_of(onto).transform.translation
        far = 60.0 if onto == 'ground' else 0.0
        put(course, (spot[0], 6.0, spot[2] + far))
        before, peak, bounced = 0.0, 0.0, False
        for _ in range(300):
            course.tick(1 / 60)
            speed = float(course.world.linear_velocity[course.ball.index][1])
            height = float(course.world.position[course.ball.index][1])
            bounced = bounced or (before < -1.0 and speed > 0.0)
            if bounced:
                peak = max(peak, height)
                if speed <= 0.0:
                    break
            before = speed
        return peak

    def test_rubber_hops_higher_than_steel_and_lead_stays_down(self):
        rubber, steel, lead = (self.hops(name) for name in ('rubber', 'steel', 'lead'))
        assert rubber > steel > lead

    def test_the_springboard_throws_rubber_higher_than_the_ground_does(self):
        assert self.hops('rubber', 'springboard') > 2.0 * self.hops('rubber')

    def struck(self, ammo):
        """The fastest a crate is moving after a ball fired at 30 m/s into the stack."""
        course = aimed_game(level=PORTCULLIS, ammo=ammo)
        course.world.gravity.gravity = 0.0
        course.fire()
        centre = np.mean([course.world.position[body.index] for body in course.crates], axis=0)
        put(course, centre - (6.0, 0.0, 0.0))
        course.world.linear_velocity[course.ball.index] = (30.0, 0.0, 0.0)
        fastest = 0.0
        for _ in range(60):
            course.tick(1 / 60)
            speeds = [np.linalg.norm(course.world.linear_velocity[body.index])
                      for body in course.crates]
            fastest = max(fastest, max(speeds))
        return fastest

    def test_a_heavy_ball_sends_crates_flying_faster_than_a_light_one(self):
        assert self.struck('lead') > 1.5 * self.struck('rubber')

    def test_the_wind_moves_a_light_ball_further_than_a_heavy_one(self):
        drift = {}
        for ammo in BALLS:
            course = aimed_game(level=CROSSWIND, ammo=ammo)
            course.world.gravity.gravity = 0.0
            course.aim.bearing, course.aim.elevation = 0.0, 20.0
            course.point()
            course.fire()
            for _ in range(30):
                course.tick(1 / 60)
            drift[ammo] = float(course.world.linear_velocity[course.ball.index][2])
            mass = game.AMMO_BY_NAME[ammo].mass
            assert drift[ammo] == pytest.approx(course.course.wind / mass * 0.5, rel=0.05)
        wind = course.course.wind
        assert abs(drift['rubber']) > abs(drift['steel']) > abs(drift['lead'])
        assert all(np.sign(value) == np.sign(wind) for value in drift.values())


class TestWhatTheShotDoes:
    def test_a_ball_that_comes_to_rest_short_of_the_target_is_a_miss(self):
        course = aimed_game()
        assert shoot(course, winning_power() - 3.0) == 'aiming'
        assert course.message == 'Missed.'

    def test_too_much_power_is_a_miss(self):
        assert shoot(aimed_game(), winning_power() + 4.0) == 'aiming'

    @pytest.mark.parametrize('turn', [8.0, -8.0])
    def test_a_bearing_to_either_side_is_a_miss(self, turn):
        course = aimed_game()
        power = winning_power()
        assert shoot(course, power, course.aim.bearing + turn) == 'aiming'

    def test_a_ball_that_touches_the_ground_is_still_flying(self):
        heard = []
        course = aimed_game()
        course.on_event = lambda kind, detail=None: heard.append((kind, course.state))
        shoot(course, winning_power() - 3.0)
        assert ('impact', 'flying') in heard
        assert heard[-1] == ('miss', 'aiming')

    def test_a_ball_fired_into_its_own_tower_is_a_miss(self):
        course = aimed_game()
        assert shoot(course, 10.0, elevation=-10.0) == 'aiming'

    def test_a_ball_that_flies_too_long_is_a_miss(self, monkeypatch):
        monkeypatch.setattr(game, 'LONGEST', 2.0)
        course = aimed_game()
        course.world.gravity.gravity = 0.0
        assert shoot(course, 40.0, 0.0) == 'aiming'

    def test_a_ball_that_falls_out_of_the_world_is_a_miss(self):
        course = aimed_game()
        course.fire()
        course.world.place_body(course.ball.index, position=(0.0, game.FALLEN - 1.0, 0.0))
        course.tick(1 / 60)
        assert course.state == 'aiming'

    def test_a_ball_that_stops_is_a_miss_after_it_has_been_still_a_while(self):
        course = aimed_game()
        course.fire()
        put(course, (0.0, game.BALL_RADIUS, 0.0))
        course.tick(game.SETTLED_TIME / 2.0)
        assert course.state == 'flying'
        course.tick(game.SETTLED_TIME)
        assert course.state == 'aiming'

    def test_a_miss_allows_another_shot(self):
        course = aimed_game()
        assert shoot(course, 8.0) == 'aiming'
        course.fire()
        assert course.state == 'flying'

    def test_the_events_of_a_shot_come_in_order(self):
        heard = []
        course = aimed_game()
        course.on_event = lambda kind, detail=None: heard.append(kind)
        shoot(course, winning_power())
        assert heard[0] == 'fire'
        assert heard[-1] == 'hit'
        assert set(heard) <= {'fire', 'impact', 'hit'}


class TestTheMark:
    """The mark is a slab a few centimetres over the target's top and 30 cm deep."""

    def pad(self, course):
        return course.course.kind('pad')[0].node

    def test_the_slab_stands_5_cm_over_the_top_and_reaches_30_cm_down(self):
        course = aimed_game()
        points = node_mesh(self.pad(course))[0]
        low, high = points.min(axis=0), points.max(axis=0)
        centre = self.pad(course).translation
        top = course.target.top
        assert centre[1] + high[1] == pytest.approx(top + game.PAD_ABOVE, abs=1e-5)
        assert centre[1] + low[1] == pytest.approx(top - game.PAD_DEPTH, abs=1e-5)
        assert tuple(high - low)[0] == pytest.approx(1.8 * game.TARGET_HALF)

    def test_the_mark_is_drawn(self):
        course = aimed_game()
        assert self.pad(course) in course.course.nodes

    def drop_at(self, height_over_top, level=OPEN):
        """A ball with no gravity, put at a height over the target's top; was it a hit?"""
        course = aimed_game(level=level)
        course.world.gravity.gravity = 0.0
        course.fire()
        put(course, (course.target.x, course.target.top + height_over_top, course.target.z))
        for _ in range(10):
            course.tick(1 / 60)
        return course.state in ('cleared', 'finished')

    def test_a_ball_resting_on_the_target_is_a_hit(self):
        assert self.drop_at(game.BALL_RADIUS)

    def test_a_ball_20_cm_clear_of_the_top_is_not(self):
        assert not self.drop_at(game.BALL_RADIUS + game.PAD_ABOVE + 0.20)

    def test_crates_on_the_mark_are_not_a_hit(self):
        course = aimed_game(level=CRATES)
        course.fire()
        put(course, (0.0, 5.0, 0.0))
        for _ in range(30):
            course.tick(1 / 60)
        assert course.state == 'flying'

    def test_a_ball_on_top_of_the_crates_is_not_a_hit(self):
        assert not self.drop_at(2 * game.CRATE + game.BALL_RADIUS, level=CRATES)


class TestTheScore:
    def test_a_clear_pays_for_the_balls_left_over(self):
        course = aimed_game()
        shoot(course, winning_power())
        assert course.state == 'cleared'
        assert course.score == game.CLEAR_BONUS + game.PER_BALL * course.shots_left

    def test_more_misses_first_pay_less(self):
        first = aimed_game()
        shoot(first, winning_power())
        later = aimed_game()
        shoot(later, 8.0)
        shoot(later, winning_power())
        assert later.score == first.score - game.PER_BALL

    def land_on_mark(self, course):
        course.fire()
        put(course, (course.target.x, course.target.top + game.BALL_RADIUS, course.target.z))
        course.tick(1 / 60)

    def test_crates_knocked_off_their_place_are_paid_for(self):
        course = aimed_game(level=CRATES)
        for body in course.crates:
            course.world.place_body(body.index, position=(0.0, 3.0, 40.0))
        assert course.toppled == len(course.crates) == 8
        self.land_on_mark(course)
        assert course.score == (game.CLEAR_BONUS + game.PER_BALL * course.shots_left
                                + game.PER_CRATE * 8)

    def test_crates_still_standing_are_not_counted(self):
        assert aimed_game(level=CRATES).toppled == 0

    def test_a_ricochet_off_the_springboard_is_paid_for(self):
        course = aimed_game(level=WALL, ammo='rubber')
        course.fire()
        spot = course.body_of('springboard').transform.translation
        put(course, (spot[0], 2.0, spot[2]))
        for _ in range(60):
            course.tick(1 / 60)
            if course.ricochet:
                break
        assert course.ricochet
        put(course, (course.target.x, course.target.top + game.BALL_RADIUS, course.target.z))
        course.tick(1 / 60)
        assert course.score == (game.CLEAR_BONUS + game.PER_BALL * course.shots_left
                                + game.RICOCHET_BONUS)
        assert course.message.startswith('Ricochet!')

    def test_a_hit_with_no_ricochet_does_not_say_so(self):
        course = aimed_game()
        shoot(course, winning_power())
        assert not course.message.startswith('Ricochet')


class TestTheCourses:
    @pytest.mark.parametrize('index', range(len(game.LEVELS)))
    def test_every_course_builds_a_world_with_a_body_for_each_piece(self, index):
        course = aimed_game(level=index)
        bound = {body.transform for body in course.manager.bodies}
        assert {piece.node for piece in course.course.pieces} == bound
        assert course.level is game.LEVELS[index]
        assert course.course.kind('ground') and course.course.kind('pad')

    @pytest.mark.parametrize('index, kinds', [
        (OPEN, set()),
        (WALL, {'wall', 'springboard'}),
        (CRATES, {'crate'}),
        (CROSSWIND, {'wall'}),
        (FERRY, {'springboard'}),
        (PORTCULLIS, {'gate', 'crate'}),
    ])
    def test_each_course_has_the_hazards_it_names(self, index, kinds):
        course = aimed_game(level=index).course
        assert {piece.kind for piece in course.pieces} - {'ground', 'tower', 'pad'} == kinds

    def test_the_crates_stand_in_a_square_of_columns_and_rows_high(self):
        course = aimed_game(level=CRATES)
        assert len(course.crates) == 8
        tops = sorted({round(float(course.world.position[body.index][1]), 1)
                       for body in course.crates})
        assert tops == [round(course.target.top + game.CRATE * (row + 0.5), 1)
                        for row in range(2)]

    def test_the_wall_stands_between_the_towers(self):
        course = aimed_game(level=WALL)
        wall = course.course.kind('wall')[0].node
        assert course.cannon.x < wall.translation[0] < course.target.x
        assert wall.translation[1] == pytest.approx(game.LEVELS[WALL].wall / 2.0)

    def test_the_pole_stands_only_where_the_wind_blows(self):
        assert aimed_game(level=OPEN).course.flag is None
        assert aimed_game(level=CROSSWIND).course.flag is not None

    @pytest.mark.parametrize('seed', [1, 2, 3, 4, 5, 6])
    def test_the_pennant_streams_the_way_the_wind_blows(self, seed):
        course = aimed_game(seed, level=CROSSWIND).course
        pennant = course.flag.children[1]
        assert np.sign(pennant.translation[2] - course.target.z) == np.sign(course.wind)

    def test_the_wind_blows_either_way_from_one_course_to_the_next(self):
        winds = {aimed_game(seed, level=CROSSWIND).course.wind for seed in range(1, 12)}
        assert winds == {-game.LEVELS[CROSSWIND].wind, game.LEVELS[CROSSWIND].wind}

    def test_the_balls_a_course_allows_are_the_ones_it_counts(self):
        course = aimed_game(level=WALL)
        assert course.stock == {'steel': 4, 'rubber': 3, 'lead': 0}
        assert [ammo.name for ammo in course.carried] == ['steel', 'rubber']

    def test_a_ball_the_course_does_not_carry_cannot_be_loaded(self):
        course = aimed_game(level=OPEN)
        course.select('lead')
        assert course.chosen == 'steel'

    def test_a_ball_the_course_carries_can_be_loaded(self):
        course = aimed_game(level=WALL)
        course.select('rubber')
        assert course.chosen == 'rubber'

    def test_the_first_ball_is_the_first_the_course_carries(self):
        assert game.Game(random.Random(1), level=CRATES).chosen == 'steel'

    def test_firing_a_spent_kind_loads_nothing(self):
        course = aimed_game(level=WALL)
        course.stock['rubber'] = 0
        course.select('rubber')
        course.fire()
        assert course.ball is None and course.state == 'aiming'
        assert 'rubber' in course.message

    def test_the_bounds_hold_the_whole_course_and_the_sliding_target(self):
        course = aimed_game(level=FERRY)
        low, high = course.course.bounds()
        slide = game.LEVELS[FERRY].slide
        assert low[2] < course.target.z - slide - course.target.half
        assert high[2] > course.target.z + slide + course.target.half
        assert high[1] > course.target.top

    @pytest.mark.parametrize('index', range(len(game.LEVELS)))
    def test_every_course_can_be_won(self, index):
        course = aimed_game(1, index)
        for ball, offset, elevation, power, wait in SOLUTIONS[index]:
            outcome = shoot(course, power, toward_target(course) + offset, ball, elevation, wait)
        assert outcome in ('cleared', 'finished'), (
            'no longer wins: find_shot() in this module finds new powers')


class TestThePlay:
    def test_a_cleared_course_leads_to_the_next(self):
        course = aimed_game()
        shoot(course, winning_power())
        course.fire()
        assert (course.index, course.state) == (1, 'aiming')
        assert course.score > 0

    def test_the_last_course_cleared_finishes_the_game(self):
        course = aimed_game(level=len(game.LEVELS) - 1)
        course.fire()
        put(course, (course.target.x, course.target.top + game.BALL_RADIUS, course.target.z))
        course.tick(1 / 60)
        assert course.state == 'finished'
        assert 'Every course' in course.message

    def test_a_finished_game_starts_again_from_nothing(self):
        course = aimed_game(level=len(game.LEVELS) - 1)
        course.score = 900
        course.state = 'finished'
        course.fire()
        assert (course.index, course.state, course.score) == (0, 'aiming', 0)

    def test_each_miss_uses_a_ball(self):
        course = aimed_game()
        assert course.shots_left == 6
        shoot(course, 8.0)
        assert course.shots_left == 5

    def test_the_last_miss_loses_the_course(self):
        heard = []
        course = aimed_game()
        course.on_event = lambda kind, detail=None: heard.append(kind)
        for _ in range(5):
            assert shoot(course, 8.0) == 'aiming'
        assert shoot(course, 8.0) == 'lost'
        assert heard.count('miss') == 5 and heard[-1] == 'lost'

    def test_a_lost_game_starts_again_from_the_first_course(self):
        course = aimed_game(level=WALL)
        course.score = 700
        for _ in range(course.shots_left):
            shoot(course, 8.0)
        assert course.state == 'lost'
        course.fire()
        assert (course.index, course.state, course.score) == (0, 'aiming', 0)

    def test_the_next_kind_is_loaded_when_the_chosen_one_runs_out(self):
        course = aimed_game(level=WALL)
        for _ in range(4):
            shoot(course, 8.0)
        assert course.stock['steel'] == 0
        assert course.chosen == 'rubber'

    def test_a_hit_on_the_last_ball_wins(self):
        course = aimed_game()
        for _ in range(5):
            shoot(course, 8.0)
        shoot(course, winning_power())
        assert course.state == 'cleared'

    def test_a_win_does_not_report_a_loss(self):
        heard = []
        course = aimed_game()
        course.on_event = lambda kind, detail=None: heard.append(kind)
        shoot(course, winning_power())
        assert 'lost' not in heard and 'miss' not in heard

    def test_the_status_names_the_course_the_score_and_the_balls(self):
        course = aimed_game(level=WALL)
        lines = course.status()
        assert lines[:2] == ['course 2/6 The Wall', 'score 0']
        assert lines[2:4] == ['>1 steel x4', ' 2 rubber x3']
        assert lines[4] == 'space fire  v views'
        assert ' '.join(lines[5:]) == game.LEVELS[WALL].hint

    def test_the_status_marks_the_ball_that_is_loaded(self):
        course = aimed_game(level=WALL)
        course.select('rubber')
        assert course.status()[2:4] == [' 1 steel x4', '>2 rubber x3']

    def test_the_status_gives_the_wind_only_where_there_is_some(self):
        assert not any('wind' in line for line in aimed_game(level=OPEN).status())
        windy = aimed_game(level=CROSSWIND)
        assert any(line.startswith('wind 3.0 N to the') for line in windy.status())


class TestTheMovers:
    def test_the_gate_is_closed_then_open_then_closed_again(self):
        period = game.GATE_PERIOD
        assert game.gate_open(0.0) == 0.0
        assert game.gate_open(period / 2.0) == 1.0
        assert game.gate_open(period) == pytest.approx(0.0)
        assert all(0.0 <= game.gate_open(t * period / 40.0) <= 1.0 for t in range(41))

    def test_the_gate_is_closed_a_third_of_the_time_and_open_a_third(self):
        samples = [game.gate_open(t * game.GATE_PERIOD / 300.0) for t in range(300)]
        assert sum(value == 0.0 for value in samples) / 300.0 == pytest.approx(1 / 3, abs=0.02)
        assert sum(value == 1.0 for value in samples) / 300.0 == pytest.approx(1 / 3, abs=0.02)

    def test_the_gate_sinks_below_the_ground_when_it_opens(self):
        course = aimed_game(level=PORTCULLIS)
        gate = course.course.kind('gate')[0].node
        height = game.LEVELS[PORTCULLIS].gate
        assert gate.translation[1] == pytest.approx(height / 2.0)
        for _ in range(int(game.GATE_PERIOD / 2.0 * 60)):
            course.tick(1 / 60)
        assert gate.translation[1] + height / 2.0 < 0.0

    def test_the_sliding_tower_and_its_mark_move_together(self):
        course = aimed_game(level=FERRY)
        tower = [piece.node for piece in course.course.kind('tower')][-1]
        mark = course.course.kind('pad')[0].node
        offset = tower.translation[2] - mark.translation[2]
        reach = 0.0
        for _ in range(int(game.SLIDE_PERIOD * 60)):
            course.tick(1 / 60)
            reach = max(reach, abs(tower.translation[2] - course.target.z))
            assert tower.translation[2] - mark.translation[2] == pytest.approx(offset, abs=0.1)
        assert reach == pytest.approx(game.LEVELS[FERRY].slide, abs=0.5)

    def test_a_ball_on_the_sliding_mark_is_a_hit(self):
        course = aimed_game(level=FERRY)
        for _ in range(int(game.SLIDE_PERIOD / 4.0 * 60)):
            course.tick(1 / 60)
        mark = course.course.kind('pad')[0].node.translation
        course.fire()
        put(course, (mark[0], course.target.top + game.BALL_RADIUS, mark[2]))
        course.tick(1 / 60)
        assert course.state == 'cleared'

    def test_the_pose_functions_start_at_home(self):
        home = (3.0, 4.0, 5.0)
        assert tuple(game.swing(home, 7.0)(0.0)) == home
        assert tuple(game.drop(home, 7.0)(0.0)) == home
        assert game.swing(home, 7.0)(game.SLIDE_PERIOD / 4.0)[2] == pytest.approx(12.0)


class TestTheSounds:
    RATE = 8000

    @pytest.fixture
    def engine(self):
        from omi_audio.device import NullDevice
        from omi_audio.engine import AudioEngine
        made = AudioEngine(device=NullDevice(sample_rate=self.RATE), voices=8)
        yield made
        made.close()

    def test_the_report_is_a_boom_that_dies_away(self):
        clip = game.Sounds(self.RATE).clips['report']
        assert clip.sample_rate == self.RATE
        assert len(clip.samples) / self.RATE > 0.9
        assert float(abs(clip.samples).max()) <= 1.0
        loud = float(abs(clip.samples[:self.RATE // 10]).max())
        late = float(abs(clip.samples[-self.RATE // 10:]).max())
        assert late < 0.3 * loud

    def test_the_fanfare_is_four_notes(self):
        clip = game.Sounds(self.RATE).clips['fanfare']
        assert clip.sample_rate == self.RATE
        assert len(clip.samples) / self.RATE == pytest.approx(0.64, abs=0.02)

    def test_the_report_grows_louder_with_the_power(self):
        low, high = game.POWER_LIMIT
        assert game.report_gain(low) == pytest.approx(game.REPORT_GAIN[0])
        assert game.report_gain(high) == pytest.approx(game.REPORT_GAIN[1])
        assert game.report_gain(low) < game.report_gain((low + high) / 2) < game.report_gain(high)
        # The step from the gentlest shot to the hardest is heard as a change,
        # not a nudge: a good few decibels, about a doubling of loudness
        quiet, loud = game.REPORT_GAIN
        assert 20.0 * math.log10(loud / quiet) >= 10.0
        # Beyond the limits it stays within them rather than running away
        assert game.report_gain(low - 100.0) == pytest.approx(game.REPORT_GAIN[0])
        assert game.report_gain(high + 100.0) == pytest.approx(game.REPORT_GAIN[1])

    @pytest.mark.parametrize('name', ['report', 'thud', 'crash', 'fanfare'])
    def test_playing_a_sound_starts_a_voice_in_the_engine(self, engine, name):
        sounds = game.Sounds(self.RATE)
        assert sounds.play(engine, name, (0.0, 3.0, 0.0)) is not None
        engine.mixer.mix(self.RATE // 10)
        assert engine.mixer.active_voices > 0

    def test_a_sound_with_no_engine_is_silence_and_no_error(self):
        sounds = game.Sounds(self.RATE)
        assert sounds.play(None, 'thud', (0.0, 0.0, 0.0)) is None
        assert sounds.fire(None, (0.0, 0.0, 0.0), game.POWER_LIMIT[1]) is None


class _NoWindowCannon(game.TestContext):
    """A cannon context with no window: it only answers for the camera's platform."""

    def getViewPlatform(self):
        return self.platform


class _Burst:
    """Stands in for the sparks emitter, and records where it was told to burst."""

    def __init__(self):
        self.at = []

    def burst_at(self, position, direction=None, **named):
        self.at.append((position, direction))


def heard_context(rate=8000):
    """The cannon's context, its ears at the camera, updated once.

    Built without a window: the scene nodes ``update`` writes to are stand-ins,
    and the engine is real over a silent device, so what it mixes is the mix.
    """
    from types import SimpleNamespace

    from omi_audio.device import NullDevice
    from omi_audio.engine import AudioEngine

    from OpenGLContext.move import viewplatform

    context = object.__new__(_NoWindowCannon)
    context.game = game.Game(random.Random(3), on_event=context.OnGame)
    context.platform = viewplatform.ViewPlatform()
    context.engine = AudioEngine(device=NullDevice(sample_rate=rate), voices=8)
    context.loaded = SimpleNamespace(translation=None, children=[])
    context.waiting = {ammo.name: object() for ammo in game.AMMO}
    context.trail = SimpleNamespace(point=[])
    context.line = SimpleNamespace(coordIndex=[])
    context.wheels = game.Wheels(context.game.set_aim)
    context.readout = SimpleNamespace(lines=[])
    context.sounds = game.Sounds(rate)
    context.sparks, context.fireworks = _Burst(), _Burst()
    context.ghost = SimpleNamespace(point=[])
    context.ghost_line = SimpleNamespace(coordIndex=[])
    context.shot = SimpleNamespace(children=[])
    context.wash = SimpleNamespace(colour=None, strength=0.0)
    context.update()
    return context


def peak_dbfs(context, power, blocks=12, frames=1024):
    """The loudest sample one shot mixes, in dBFS."""
    context.sounds.fire(context.engine, context.game.muzzle, power)
    peak = 0.0
    for _ in range(blocks):
        peak = max(peak, float(np.abs(context.engine.mixer.mix(frames)).max()))
    return 20.0 * math.log10(max(peak, 1e-9))


#: Floor for the shot on its own: below this it is lost on ordinary hardware.
AUDIBLE_DBFS = -30.0


class TestTheSoundsReachTheCamera:
    """The sounds are played straight into the engine, so the ears follow the camera.

    Nothing else moves the listener here, so a sound is only audible if the
    context puts the listener where the camera is each frame.
    """

    RATE = 8000

    @pytest.fixture
    def heard(self):
        made = []

        def build():
            context = heard_context(self.RATE)
            made.append(context)
            return context

        yield build
        for context in made:
            context.engine.close()

    def test_the_listener_moves_to_the_camera(self, heard):
        context = heard()
        camera = list(context.platform.position)[:3]
        assert list(context.engine.listener.position) == pytest.approx(camera)

    def test_the_least_power_is_audible(self, heard):
        assert peak_dbfs(heard(), game.POWER_LIMIT[0]) > AUDIBLE_DBFS

    def test_the_most_power_is_louder_than_the_least(self, heard):
        quiet = peak_dbfs(heard(), game.POWER_LIMIT[0])
        loud = peak_dbfs(heard(), game.POWER_LIMIT[1])
        # The two are told apart by ear: a span of about a doubling of loudness
        assert loud > quiet + 10.0
        assert quiet > AUDIBLE_DBFS

    def test_firing_plays_the_report(self, heard):
        context = heard()
        context.game.fire()
        context.engine.mixer.mix(self.RATE // 10)
        assert context.engine.mixer.active_voices > 0

    def impact(self, context, ammo, speed=9.0):
        from types import SimpleNamespace
        context.game.flying = game.AMMO_BY_NAME[ammo]
        context.OnGame('impact', SimpleNamespace(approach=speed, point=np.array([1.0, 0.0, 2.0]),
                                                 normal=np.array([0.0, 1.0, 0.0])))

    def test_a_hard_impact_of_steel_makes_a_sound_and_sparks(self, heard):
        context = heard()
        self.impact(context, 'steel')
        context.engine.mixer.mix(self.RATE // 10)
        assert context.engine.mixer.active_voices > 0
        assert context.sparks.at == [((1.0, 0.0, 2.0), (0.0, 1.0, 0.0))]

    def test_a_hard_impact_of_rubber_makes_a_sound_and_no_sparks(self, heard):
        context = heard()
        self.impact(context, 'rubber')
        context.engine.mixer.mix(self.RATE // 10)
        assert context.engine.mixer.active_voices > 0
        assert context.sparks.at == []

    def test_a_soft_touch_makes_neither(self, heard):
        context = heard()
        self.impact(context, 'steel', speed=game.IMPACT_SPEED / 2.0)
        context.engine.mixer.mix(self.RATE // 10)
        assert context.engine.mixer.active_voices == 0
        assert context.sparks.at == []

    def test_a_hit_throws_fireworks_and_turns_the_screen_green(self, heard):
        context = heard()
        context.OnGame('hit', 500)
        assert len(context.fireworks.at) == 1
        assert context.wash.colour == game.WIN_WASH
        assert context.wash.strength == game.WASH_STRENGTH

    def test_a_lost_course_turns_the_screen_red(self, heard):
        context = heard()
        context.OnGame('lost', None)
        assert context.wash.colour == game.LOSE_WASH

    def test_a_crate_crash_is_heard(self, heard):
        from types import SimpleNamespace
        context = heard()
        context.OnGame('crash', SimpleNamespace(approach=6.0, point=np.zeros(3)))
        context.engine.mixer.mix(self.RATE // 10)
        assert context.engine.mixer.active_voices > 0

    def test_space_in_flight_leaves_the_trail_and_the_last_path_alone(self, heard):
        context = heard()
        context.OnFire(None)
        context.game.tick(0.2)
        context.update()
        trail, ghost = list(context.trail.point), list(context.ghost.point)
        context.OnFire(None)
        # The trail carries on from where it was, and is not started again
        assert list(context.trail.point)[:len(trail)] == trail
        assert list(context.ghost.point) == ghost
        assert context.game.state == 'flying'

    def test_the_loaded_ball_follows_the_selection(self, heard):
        context = heard()
        context.game.start_level(WALL)
        context.game.select('rubber')
        context.update()
        assert context.loaded.children == [context.waiting['rubber']]
        context.game.fire()
        context.update()
        assert context.loaded.children == []


class TestTheCannonsFrames:
    """The barrel's direction, its mouth and the camera all come from the nodes."""

    ANGLES = [(0, 0), (25, 40), (-35, 70), (50, -10)]

    @staticmethod
    def gun():
        return game.build_course(game.LEVELS[OPEN], random.Random(2), game.looks()).gun

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_barrel_points_where_the_bearing_and_elevation_say(self, bearing, elevation):
        gun = self.gun()
        gun.aim(bearing, elevation)
        assert tuple(gun.along) == pytest.approx(along(bearing, elevation), abs=1e-6)

    def test_the_camera_is_30_cm_to_the_right_of_the_barrel(self):
        gun = self.gun()
        gun.aim(0, 0)                  # barrel along +x, so its right is +z
        eye = gun.to_world(game.EYE)
        pivot = gun.turn.translation
        assert eye[2] - pivot[2] == pytest.approx(0.3, abs=1e-6)

    def test_one_cannon_aimed_again_and_again_follows_each_aim(self):
        """The paths keep their matrices until a rotation above them changes."""
        gun = self.gun()
        for bearing, elevation in self.ANGLES + self.ANGLES[::-1]:
            gun.aim(bearing, elevation)
            assert tuple(gun.along) == pytest.approx(along(bearing, elevation), abs=1e-6)
            assert gun.eye_path.quaternion().XYZR() is not None

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_muzzle_is_a_barrel_length_from_the_pivot(self, bearing, elevation):
        gun = self.gun()
        gun.aim(bearing, elevation)
        pivot = gun.turn.translation
        expected = tuple(p + game.BARREL * d
                         for p, d in zip(pivot, along(bearing, elevation)))
        assert tuple(gun.muzzle) == pytest.approx(expected, abs=1e-5)

    @pytest.mark.parametrize('bearing, elevation', ANGLES)
    def test_the_camera_stands_behind_the_pivot_and_looks_along_the_barrel(
            self, bearing, elevation):
        gun = self.gun()
        gun.aim(bearing, elevation)

        class Platform:
            position = None
            orientation = None

            def setPosition(self, position):
                self.position = tuple(position)[:3]

            def setOrientation(self, orientation):
                self.orientation = tuple(orientation)

            def setFrustum(self, *arguments, **named):
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


def drag(wheel, pixels):
    """Press the wheel's drum and drag ``pixels`` up it."""
    from vrml.x3d import pointing  # noqa: PLC0415 kept with its use

    def ray(height):
        return pointing.Ray((0.0, height, 500.0), (0.0, 0.0, -1.0))

    wheel.sensor.pointerPress(pointing.Hit((0.0, 0.0, 0.0)), ray(0.0))
    wheel.sensor.pointerDrag(None, ray(pixels))


class TestTheScales:
    """A wheel's turn read as the value it sets, and the value as the turn."""

    def test_there_is_one_for_each_field_of_the_aim_over_its_limits(self):
        assert [(scale.name, scale.limits) for scale in game.SCALES] == [
            ('bearing', game.BEARING_LIMIT), ('elevation', game.ELEVATION_LIMIT),
            ('power', game.POWER_LIMIT)]

    def test_each_names_the_keys_that_step_its_field(self):
        for scale in game.SCALES:
            up, down = scale.keys
            assert game.AIM_KEYS[up][scale.name] > 0 > game.AIM_KEYS[down][scale.name]

    @pytest.mark.parametrize('scale', game.SCALES, ids=lambda scale: scale.name)
    def test_the_limits_are_one_whole_turn_and_the_whole_travel_apart(self, scale):
        low, high = scale.limits
        assert (scale.turn(low), scale.turn(high)) == (0.0, 1.0)
        assert scale.value(0.0) == low
        assert scale.value(game.TRAVEL) == pytest.approx(high)
        assert scale.value(game.TRAVEL / 2.0) == pytest.approx((low + high) / 2.0)

    def test_the_travel_is_most_of_the_windows_height(self):
        assert 0.7 * game.SIZE[1] <= game.TRAVEL <= 0.9 * game.SIZE[1]

    def test_a_drag_past_the_end_of_the_travel_reads_as_the_limit(self):
        bearing = game.SCALES[0]
        assert bearing.value(game.TRAVEL * 2.0) == game.BEARING_LIMIT[1]
        assert bearing.value(-5.0) == game.BEARING_LIMIT[0]


class TestTheWheels:
    """The three thumb-wheels: a drag on one sets the aim, and the aim sets all three."""

    @pytest.fixture
    def turned(self):
        return []

    @pytest.fixture
    def wheels(self, turned):
        return game.Wheels(lambda name, value: turned.append((name, value)))

    def test_there_is_a_wheel_for_each_scale(self, wheels):
        assert [wheel.scale for wheel in wheels.wheels] == list(game.SCALES)

    def test_each_sensor_is_dragged_up_and_down_the_travel_and_not_across(self, wheels):
        for wheel in wheels.wheels:
            assert tuple(wheel.sensor.minPosition) == (0.0, 0.0)
            assert tuple(wheel.sensor.maxPosition) == (0.0, game.TRAVEL)

    def test_a_pixel_of_drag_is_a_key_press_or_so(self, wheels, turned):
        wheels.show(game.Aim(bearing=0.0))
        drag(wheels.wheels[0], 1.0)
        assert 0.0 < turned[-1][1] <= 1.5 * game.TURN

    def test_dragging_a_wheel_up_raises_its_field(self, wheels, turned):
        wheels.show(game.Aim(bearing=0.0))
        drag(wheels.wheels[0], game.TRAVEL / 10.0)
        assert [name for name, _value in turned] == ['bearing']
        low, high = game.BEARING_LIMIT
        assert turned[-1][1] == pytest.approx((high - low) / 10.0, abs=1e-4)

    def test_a_drag_carries_on_from_the_value_shown(self, wheels, turned):
        wheels.show(game.Aim(elevation=40.0))
        low, high = game.ELEVATION_LIMIT
        drag(wheels.wheels[1], -game.TRAVEL / 10.0)
        assert turned[-1] == ('elevation', pytest.approx(40.0 - (high - low) / 10.0, abs=1e-4))

    def test_a_drag_stops_at_the_limit(self, wheels, turned):
        wheels.show(game.Aim(bearing=50.0))
        drag(wheels.wheels[0], game.TRAVEL)
        assert turned[-1] == ('bearing', pytest.approx(game.BEARING_LIMIT[1]))

    def test_a_drag_to_one_side_changes_nothing_more(self, wheels, turned):
        from vrml.x3d import pointing  # noqa: PLC0415 kept with its use
        wheels.show(game.Aim(power=20.0))
        sensor = wheels.wheels[2].sensor
        sensor.pointerPress(pointing.Hit((0, 0, 0)), pointing.Ray((0, 0, 500), (0, 0, -1)))
        sensor.pointerDrag(None, pointing.Ray((300.0, 0, 500), (0, 0, -1)))
        assert turned[-1] == ('power', pytest.approx(20.0))

    def test_the_aim_turns_each_drum_and_is_written_under_it(self, wheels):
        wheels.show(game.Aim(bearing=-12.5, elevation=33.0, power=21.0))
        for wheel, value in zip(wheels.wheels, (-12.5, 33.0, 21.0)):
            # The face of the drum goes up as the value does
            assert tuple(wheel.drum.rotation) == pytest.approx(
                (1, 0, 0, -2.0 * math.pi * wheel.scale.turn(value)))
        assert [list(wheel.label.string) for wheel in wheels.wheels] == [
            ['bearing  q a', '-12.5 deg'], ['elevation  w s', '33.0 deg'],
            ['power  e d', '21.0 m/s  46%']]

    def test_only_the_power_wheel_reads_its_share_of_the_scale(self, wheels):
        wheels.show(game.Aim(bearing=-12.5, elevation=33.0, power=21.0))
        assert '%' not in wheels.wheels[0].label.string[1]
        assert '%' not in wheels.wheels[1].label.string[1]
        assert wheels.wheels[2].label.string[1].endswith('46%')

    def test_the_power_wheel_reads_the_ends_of_its_scale(self, wheels):
        wheel = wheels.wheels[2]
        wheel.show(game.POWER_LIMIT[0])
        assert list(wheel.label.string) == ['power  e d', '5.0 m/s  0%']
        wheel.show(game.POWER_LIMIT[1])
        assert list(wheel.label.string) == ['power  e d', '40.0 m/s  100%']

    def test_a_whole_turn_of_the_drum_is_the_whole_scale(self, wheels):
        wheel = wheels.wheels[2]
        wheel.show(game.POWER_LIMIT[0])
        assert wheel.drum.rotation[3] == pytest.approx(0.0)
        wheel.show(game.POWER_LIMIT[1])
        assert abs(wheel.drum.rotation[3]) == pytest.approx(2.0 * math.pi)

    def test_a_value_shown_during_a_drag_leaves_the_drag_where_it_started(self, wheels):
        wheels.show(game.Aim(bearing=0.0))
        wheel = wheels.wheels[0]
        started = wheel.sensor.offset[1]
        drag(wheel, 30.0)
        wheels.show(game.Aim(bearing=10.0))
        assert wheel.sensor.offset[1] == pytest.approx(started)
        assert wheel.drum.rotation[3] == pytest.approx(-2.0 * math.pi * wheel.scale.turn(10.0))

    def test_the_layers_are_drawn_over_the_scene(self, wheels):
        assert list(wheels.layers.order) == [0, 1]
        assert len(wheels.layers.layers) == 1

    def test_the_panel_stands_at_the_left_of_its_view_half_way_up(self, wheels):
        layout = wheels.layer.layout
        assert list(layout.align) == ['LEFT', 'CENTER']
        assert tuple(layout.size) == pytest.approx(wheels.size)

    def test_a_wheel_turned_while_aiming_moves_the_cannon(self):
        course = game.Game(random.Random(3))
        wheels = game.Wheels(course.set_aim)
        wheels.show(course.aim)
        drag(wheels.wheels[0], game.TRAVEL / 8.0)
        assert course.aim.bearing == pytest.approx(15.0, abs=1e-4)
        assert tuple(course.course.gun.turn.rotation) == pytest.approx(
            (0, 1, 0, math.radians(15.0)), abs=1e-5)

    def test_a_wheel_turned_while_the_ball_is_in_the_air_sets_the_next_shot(self):
        course = game.Game(random.Random(3))
        wheels = game.Wheels(course.set_aim)
        wheels.show(course.aim)
        course.fire()
        drag(wheels.wheels[2], 100.0)
        assert course.aim.power > game.Aim().power


@pytest.mark.usefixtures('gl_context')
class TestTheWheelsOnTheScreen:
    """The panel in the cannon's view of the four, dragged with the pointer."""

    WIDTH, HEIGHT = game.SIZE

    @pytest.fixture
    def played(self):
        from OpenGLContext.context import MultiViewContext  # noqa: PLC0415 GL
        from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
        course = game.Game(random.Random(3))
        wheels = game.Wheels(course.set_aim)
        wheels.show(course.aim)
        setup = game.TestContext.setupViews

        class Quad(MultiViewContext):
            game = course
            setupViews = setup

        with scene_context([*course.course.nodes, wheels.layers], base=Quad,
                           size=game.SIZE) as context:
            context.OnDraw(force=1)
            yield context, course, wheels

    def panel(self, wheels):
        """The panel's left, bottom, width and height in the window, from the bottom left:
        it is in the bottom right view."""
        width, height = wheels.size
        return (self.WIDTH / 2 + game.INSET, self.HEIGHT / 4 - height / 2, width, height)

    def pointer(self, context, wheels, kind, rise, until, **record):
        """Send the pointer ``rise`` pixels above the middle of the bearing wheel's
        drum, and draw until ``until()``."""
        from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
        left, bottom, width, height = self.panel(wheels)
        x = round(left + width / 2 - game.PITCH)
        y = round(bottom + height / 2 + game.RISE + rise)
        synthetic.dispatch(context, {'type': kind, 'x': x, 'y': y, 'pick': True, **record})
        for _ in range(120):
            context.OnDraw(force=1)
            if until():
                return
        raise AssertionError('the %s %s pixels up was not sensed' % (kind, rise))

    def test_the_panel_is_in_the_cannons_view_alone(self, played):
        from OpenGLContext.testing.scenes import drawn_image  # noqa: PLC0415 GL
        context, _course, wheels = played
        image = drawn_image(context)
        left, bottom, _width, _height = self.panel(wheels)
        x, y = round(left + 5), round(bottom + 5)
        panel = image[self.HEIGHT - 1 - (y + 30):self.HEIGHT - 1 - y - 5,
                      x:x + 30].reshape(-1, 3).astype(int)
        metal = panel.mean(axis=0)
        # The panel is brushed metal: grey, so no channel leads, and mid-bright
        assert float(metal.max() - metal.min()) < 25.0
        assert 80.0 < float(metal.mean()) < 220.0
        for across, up in ((-self.WIDTH // 2, 0), (0, self.HEIGHT // 2),
                           (-self.WIDTH // 2, self.HEIGHT // 2)):
            elsewhere = image[self.HEIGHT - 1 - (y + up), x + across].astype(int)
            assert abs(elsewhere - metal).sum() > 30.0

    def test_the_reading_under_the_wheels_is_dark_on_the_panel(self, played):
        from OpenGLContext.testing.scenes import drawn_image  # noqa: PLC0415 GL
        context, _course, wheels = played
        image = drawn_image(context)
        left, bottom, width, _height = self.panel(wheels)
        # The reading is written under the wheels, low in the panel
        rows = slice(round(self.HEIGHT - 1 - (bottom + 55)),
                     round(self.HEIGHT - 1 - (bottom + 30)))
        band = image[rows, round(left):round(left + width)].reshape(-1, 3).astype(int)
        ink = band.mean(axis=1)
        assert float(np.median(ink)) > 150.0     # the panel behind is bright
        assert float(ink.min()) < 90.0           # the ink is dark against it
        assert float((ink < 90.0).mean()) > 0.02

    def test_dragging_the_bearing_wheel_up_turns_the_cannon(self, played):
        context, course, wheels = played
        sensor = wheels.wheels[0].sensor
        # A pick reads the frame before, so the first move only warms the id buffer
        self.pointer(context, wheels, 'mousemove', 0, lambda: True, buttons=[])
        self.pointer(context, wheels, 'mousemove', 0, sensor.over, buttons=[])
        self.pointer(context, wheels, 'mousebutton', 0, sensor.active, button=0, state=1)
        rise = round(game.TRAVEL / 10.0)
        self.pointer(context, wheels, 'mousemove', rise,
                     lambda: course.aim.bearing != 0.0, buttons=[0])
        self.pointer(context, wheels, 'mousebutton', rise, lambda: not sensor.active(),
                     button=0, state=0)
        low, high = game.BEARING_LIMIT
        assert course.aim.bearing == pytest.approx((high - low) / 10.0, abs=0.5)
        assert sensor.offset[1] == pytest.approx(
            game.SCALES[0].turn(course.aim.bearing) * game.TRAVEL, abs=1e-3)
