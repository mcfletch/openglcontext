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
            ['power  e d', '21.0 m/s']]

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

    def test_a_wheel_turned_while_the_ball_is_in_the_air_moves_nothing(self):
        course = game.Game(random.Random(3))
        wheels = game.Wheels(course.set_aim)
        wheels.show(course.aim)
        course.fire()
        drag(wheels.wheels[2], 100.0)
        assert course.aim.power == game.Aim().power


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
        wood = image[self.HEIGHT - 1 - y, x].astype(int)
        # The panel is wood: redder than it is blue, which no sky is
        assert wood[0] > wood[2] + 20
        for across, up in ((-self.WIDTH // 2, 0), (0, self.HEIGHT // 2),
                           (-self.WIDTH // 2, self.HEIGHT // 2)):
            elsewhere = image[self.HEIGHT - 1 - (y + up), x + across].astype(int)
            assert abs(elsewhere - wood).sum() > 30

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
