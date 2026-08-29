"""Figures walking about on their own: where they go, and what they play.

Pure Python/numpy -- no GL, no window. :class:`Wander` holds no clips and
:class:`Gait` holds no scenegraph, which is the point of them being separate:
the decisions a crowd's individuality comes out of can be run frame by frame in
a test and read.
"""
import sys

import numpy as np
import pytest

pygltflib = pytest.importorskip("pygltflib")

from OpenGLContext.testing.paths import tests_root

HERE = str(tests_root(__file__))

from OpenGLContext import entropy
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.character.wander import (
    Gait, STAND, TURN, WALK, Wander, WanderingCrowd,
)
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf
from tests.unit._character_assets import character_glb

DT = 1 / 60.0


@pytest.fixture(autouse=True)
def seeded():
    """Every test walks the same walk, and leaves no seed behind it."""
    entropy.reseed(4242)
    yield
    entropy.forget()


#: Fraction of the body's speed the planted foot may drift at in the demo. The
#: clip's own footfall is not perfectly planted, so this is not zero; a figure
#: walking through its cycle backwards reads as 103% and an out-by-a-quarter
#: stride as 19%.
FOOT_DRIFT = 0.15


@pytest.fixture(scope='module')
def document():
    return parse_gltf(character_glb())


@pytest.fixture(scope='module')
def demo():
    """The crowd demo, imported for the constants it measured off its model."""
    sys.path.insert(0, HERE)
    import crowd_demo
    return crowd_demo


@pytest.fixture(scope='module')
def figure(demo):
    """The demo's own sample model, or a skip where it cannot be fetched."""
    from OpenGLContext.loaders.gltf import sample_model_url
    from OpenGLContext.loaders.resolver import fetch_to_cache
    try:
        return parse_gltf(fetch_to_cache(sample_model_url(demo.MODEL)))
    except Exception as err:
        pytest.skip('%s is not in the asset cache: %s' % (demo.MODEL, err))


@pytest.fixture
def model(document):
    return _figure(document)


def _figure(document):
    """A model whose whole pose reaches the scenegraph, so a test can read it."""
    model = CharacterModel(load_gltf(document=document))
    model.mixer.pose_write = 'all'
    return model


def _run(wander, seconds, dt=DT):
    """Step for ``seconds`` and answer every state that was passed through."""
    seen = set()
    for _ in range(int(seconds / dt)):
        wander.step(dt)
        seen.update(int(state) for state in wander.state)
    return seen


class TestWhereAFigureGoes:
    def test_heading_zero_walks_towards_plus_z(self):
        """The heading is a Transform's rotation angle about +Y and nothing
        else, so which way it carries a figure is part of the contract: that
        rotation turns +Z into where the figure goes."""
        wander = Wander((-50.0, 50.0, -50.0, 50.0))
        wander.add(position=(0.0, 0.0), heading=0.0)
        # The arrays are made at the first step, so the walk is dialled all the
        # way in after one rather than waiting for the fade.
        wander.step(DT)
        wander.moving[0] = 1.0

        wander.step(1.0)

        assert wander.position[0][0] == pytest.approx(0.0, abs=1e-9)
        assert wander.position[0][1] > 0.5

    def test_a_quarter_turn_walks_towards_plus_x(self):
        wander = Wander((-50.0, 50.0, -50.0, 50.0))
        wander.add(position=(0.0, 0.0), heading=np.pi / 2)
        wander.step(DT)
        wander.moving[0] = 1.0

        wander.step(1.0)

        assert wander.position[0][0] > 0.5
        assert wander.position[0][1] == pytest.approx(0.0, abs=1e-9)

    def test_a_figure_walks_the_way_its_node_is_turned(self):
        """The two have to be the same statement, or a crowd moonwalks: the
        rotation written on the node, applied to the model's forward, must be
        the direction the body actually travels."""
        for heading in (0.0, 0.9, 2.5, -1.8):
            wander = Wander((-50.0, 50.0, -50.0, 50.0))
            wander.add(position=(0.0, 0.0), heading=heading)
            wander.step(DT)
            wander.moving[0] = 1.0
            wander.step(1.0)

            # +Z through the rotation the node is given, which is heading
            # about +Y: (x, z) -> (x cos + z sin, -x sin + z cos).
            angle = float(wander.heading[0])
            forward = (np.sin(angle), np.cos(angle))
            walked = wander.position[0] / np.linalg.norm(wander.position[0])

            assert walked == pytest.approx(forward, abs=1e-9)

    def test_a_standing_figure_stays_where_it_is(self):
        wander = Wander((-50.0, 50.0, -50.0, 50.0), stand=(60.0, 60.0),
                        walk=(0.0, 0.0), fade=0.0)
        wander.add(position=(2.0, -3.0), heading=0.4)

        wander.step(DT)
        wander.step(DT)
        wander.step(DT)

        assert wander.state[0] == STAND
        assert wander.position[0].tolist() == [2.0, -3.0]


class TestWhatAFigureDoes:
    def test_it_walks_stops_turns_and_walks_again(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0),
                        walk=(0.5, 1.0), stand=(0.4, 0.8))
        wander.add(position=(0.0, 0.0), heading=0.0)

        assert _run(wander, 20.0) == {STAND, TURN, WALK}

    def test_a_turn_takes_the_figure_somewhere_else(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0),
                        walk=(0.3, 0.3), stand=(0.3, 0.3))
        wander.add(position=(0.0, 0.0), heading=0.0)
        _run(wander, 0.7)
        before = float(wander.heading[0])
        _run(wander, 6.0)

        # A turn is a turn, not a nudge: the smallest one asked for is 0.7 rad.
        assert abs(float(wander.heading[0]) - before) > 0.5

    def test_the_walk_eases_in_rather_than_switching_on(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0), fade=0.5,
                        walk=(10.0, 10.0), stand=(10.0, 10.0))
        wander.add(position=(0.0, 0.0), heading=0.0)

        wander.step(0.1)
        part = float(wander.moving[0])
        wander.step(0.1)

        assert 0.0 < part < 1.0
        assert float(wander.moving[0]) > part

    def test_a_figure_easing_off_covers_less_ground_than_one_at_full_walk(self):
        """The weight the walk carries is also how fast the body travels, so a
        figure comes to a halt instead of stopping dead under a moving clip."""
        wander = Wander((-30.0, 30.0, -30.0, 30.0), speed=(1.0, 1.0), fade=0.5)
        wander.add(position=(0.0, 0.0), heading=0.0)
        wander.add(position=(4.0, 0.0), heading=0.0)
        wander.step(DT)
        wander.moving[:] = (1.0, 0.25)
        before = wander.position.copy()

        wander._advance(0.5)

        walked = np.abs(wander.position - before)[:, 1]
        assert walked[0] == pytest.approx(0.5, abs=1e-9)
        assert walked[1] == pytest.approx(0.125, abs=1e-9)


class TestWhoActuallyMoved:
    """What a caller writes out of a field, and what it can leave alone."""

    def test_a_figure_walking_straight_ahead_does_not_turn(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0), fade=0.0,
                        walk=(60.0, 60.0))
        wander.add(position=(0.0, 0.0), heading=0.0)
        wander.step(DT)             # taken in, so it counts as having moved

        wander.step(DT)

        assert wander.state[0] == WALK
        assert bool(wander.walked[0])
        assert not bool(wander.turned[0])

    def test_a_figure_standing_still_does_not_move(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0), fade=0.0,
                        walk=(0.0, 0.0), stand=(60.0, 60.0))
        wander.add(position=(0.0, 0.0), heading=0.0)
        wander.step(DT)
        wander.step(DT)

        wander.step(DT)

        assert wander.state[0] == STAND
        assert not bool(wander.walked[0])
        assert not bool(wander.turned[0])

    def test_a_figure_just_taken_in_counts_as_both(self):
        """Nothing has been told where it is, so its first step has to say so
        however still it is."""
        wander = Wander((-30.0, 30.0, -30.0, 30.0), fade=10.0)
        wander.add(position=(3.0, 4.0), heading=1.0)

        wander.step(DT)

        assert bool(wander.walked[0]) and bool(wander.turned[0])

    def test_a_turning_figure_says_so(self):
        wander = Wander((-30.0, 30.0, -30.0, 30.0),
                        walk=(0.2, 0.2), stand=(0.2, 0.2))
        wander.add(position=(0.0, 0.0), heading=0.0)
        turned = False
        for _ in range(240):
            wander.step(DT)
            turned = turned or (wander.state[0] == TURN
                                and bool(wander.turned[0]))

        assert turned

    def test_a_field_that_is_told_only_of_what_moved_still_ends_up_right(self):
        """Skipping the still ones is an optimisation, so it has to be one:
        following only what each step reports has to leave every figure where
        following all of them would."""
        traces = []
        for report_only in (False, True):
            entropy.reseed(5)
            wander = Wander((-9.0, 9.0, -9.0, 9.0))
            for index in range(8):
                wander.add(position=(index - 3.5, 0.0))
            shown = np.zeros((8, 3))
            for _ in range(900):
                wander.step(DT)
                rows = (np.flatnonzero(wander.walked | wander.turned)
                        if report_only else np.arange(8))
                shown[rows, :2] = wander.position[rows]
                shown[rows, 2] = wander.heading[rows]
            traces.append(shown)

        assert np.array_equal(traces[0], traces[1])


class TestStayingOnTheField:
    def test_nobody_walks_off_it(self):
        wander = Wander((-4.0, 4.0, -4.0, 4.0), walk=(20.0, 20.0),
                        stand=(0.2, 0.4), speed=(2.0, 2.5))
        for index in range(12):
            wander.add(position=(index * 0.5 - 3.0, 0.0))

        _run(wander, 60.0)

        assert np.all(wander.position >= -4.0)
        assert np.all(wander.position <= 4.0)

    def test_a_figure_at_the_edge_stops_and_turns_back_inwards(self):
        wander = Wander((-4.0, 4.0, -4.0, 4.0), margin=1.0,
                        walk=(100.0, 100.0), stand=(0.1, 0.1), fade=0.0)
        # Facing +Z at the +Z edge, so walking on is walking off.
        wander.add(position=(0.0, 3.5), heading=0.0)

        wander.step(DT)
        assert wander.state[0] == STAND, 'the edge did not stop it'
        _run(wander, 8.0)

        # Heading is measured from +Z, so facing back inwards is near pi.
        assert abs(abs(float(wander.heading[0])) - np.pi) < 1.2
        assert float(wander.position[0][1]) < 3.5


class TestTheSeedDecidesIt:
    def test_the_same_seed_walks_the_same_walk(self):
        traces = []
        for _ in range(2):
            entropy.reseed(99)
            wander = Wander((-8.0, 8.0, -8.0, 8.0))
            for index in range(5):
                wander.add(position=(index - 2.0, 0.0), heading=0.0)
            _run(wander, 12.0)
            traces.append(wander.position.copy())

        assert np.array_equal(traces[0], traces[1])

    def test_another_seed_walks_another_walk(self):
        traces = []
        for seed in (99, 100):
            entropy.reseed(seed)
            wander = Wander((-8.0, 8.0, -8.0, 8.0))
            for index in range(5):
                wander.add(position=(index - 2.0, 0.0), heading=0.0)
            _run(wander, 12.0)
            traces.append(wander.position.copy())

        assert not np.allclose(traces[0], traces[1])

    def test_figures_added_later_join_the_field(self):
        wander = Wander((-8.0, 8.0, -8.0, 8.0))
        wander.add(position=(0.0, 0.0))
        wander.step(DT)
        assert len(wander.state) == 1

        wander.add(position=(1.0, 1.0))
        assert len(wander) == 2
        wander.step(DT)

        assert len(wander.state) == 2
        assert wander.position[0].tolist() != wander.position[1].tolist()


class TestGait:
    """The clips a figure shows, dialled between standing and travelling.

    The test model carries two clips, so one stands in for the walk and the
    other for the idle -- what matters here is the arithmetic of the blend, not
    which clip is which.
    """

    def test_it_stands_still_until_it_is_asked_to_move(self, model):
        gait = Gait(model, walk='kick', idle='raise')

        assert gait.idle.weight == 1.0
        assert gait.walk.weight == 0.0
        assert gait.idle.tracks[0].name == 'raise'

    def test_asking_for_a_walk_puts_the_walk_in_the_pose(self, model):
        gait = Gait(model, walk='kick', idle='raise')
        model.update(0.3)
        standing = _pose_of(model)

        gait.apply(1.0)
        model.update(0.0)

        assert not np.allclose(standing, _pose_of(model))

    def test_half_a_walk_is_half_way_between_the_two(self, document):
        """Which is what makes a figure setting off read as setting off.

        Measured on the angle the walk turns its joint through: the pose is
        blended as rotations, so half of it is half the angle rather than the
        mean of the axis-and-angle the scenegraph stores it as.
        """
        angles = []
        for moving in (0.0, 0.5, 1.0):
            one = _figure(document)
            Gait(one, walk='kick', idle='raise').apply(moving, speed=1.0)
            one.update(0.25)
            # translation 0-2, rotation axis 3-5, rotation angle 6, scale 7-9
            angles.append(_pose_of(one)[:, 6])

        standing, half, walking = (np.asarray(a) for a in angles)
        moved = np.flatnonzero(np.abs(walking - standing) > 1e-6)
        assert len(moved), 'the walk changed nothing to measure'
        assert np.allclose(half[moved], (standing[moved] + walking[moved]) / 2.0,
                           atol=1e-3)

    def test_the_cycle_runs_at_the_speed_the_body_travels(self, model):
        gait = Gait(model, walk='kick', idle='raise', walk_stride=2.0)

        gait.apply(1.0, 3.0)

        assert gait.walk.tracks[0].speed == pytest.approx(1.5)

    def test_a_clip_that_carries_the_body_nowhere_runs_at_its_own_rate(
            self, model):
        """An in-place cycle has no ground speed to keep up with, so scaling
        its clock by one is the only thing that means anything."""
        gait = Gait(model, walk='kick', idle='raise', walk_stride=0.0)

        gait.apply(1.0, 3.0)

        assert gait.walk.tracks[0].speed == pytest.approx(1.0)

    def test_a_body_below_the_walk_stride_is_not_running_at_all(self, model):
        gait = Gait(model, walk='kick', run='raise', idle='raise',
                    walk_stride=1.0, run_stride=2.0)

        gait.apply(1.0, 0.8)

        assert gait.walk.weight == 1.0
        assert gait.run.weight == 0.0

    def test_a_body_above_the_run_stride_is_running_outright(self, model):
        gait = Gait(model, walk='kick', run='raise', idle='raise',
                    walk_stride=1.0, run_stride=2.0)

        gait.apply(1.0, 2.6)

        assert gait.run.weight == pytest.approx(1.0)

    def test_between_the_two_strides_the_clips_are_mixed(self, model):
        """A body picking up speed is part walk and part run, which is what
        gives a field of them a spread rather than two camps."""
        gait = Gait(model, walk='kick', run='raise', idle='raise',
                    walk_stride=1.0, run_stride=2.0)

        gait.apply(1.0, 1.5)

        assert gait.walk.weight == 1.0
        assert gait.run.weight == pytest.approx(0.5)

    def test_a_body_half_way_out_of_its_idle_carries_half_its_run(self, model):
        """The locomotion layers sit over the idle, so both have to come down
        together or a figure coming to a halt keeps galloping."""
        gait = Gait(model, walk='kick', run='raise', idle='raise',
                    walk_stride=1.0, run_stride=2.0)

        gait.apply(0.5, 2.6)

        assert gait.walk.weight == pytest.approx(0.5)
        assert gait.run.weight == pytest.approx(0.5)

    def test_a_new_action_cross_fades_the_idle_rather_than_cutting_to_it(
            self, model):
        gait = Gait(model, walk='kick', idle=['raise', 'kick'], fade=0.4)

        gait.apply(0.0, 0.0, action=1)

        assert [t.name for t in gait.idle.tracks] == ['raise', 'kick']
        assert gait.idle.tracks[0].target == 0.0
        assert gait.idle.tracks[1].target == 1.0

    def test_asking_for_the_idle_it_is_already_doing_costs_nothing(self, model):
        """A state machine says what a figure is doing every frame, so saying
        the same thing again must not restart the fade."""
        gait = Gait(model, walk='kick', idle=['raise', 'kick'], fade=0.4)
        gait.apply(0.0, 0.0, action=1)
        for _ in range(40):
            model.update(DT)
        settled = [t.name for t in gait.idle.tracks]

        gait.apply(0.0, 0.0, action=1)

        assert settled == ['kick']
        assert [t.name for t in gait.idle.tracks] == ['kick']

    def test_an_action_past_the_end_of_the_list_wraps(self, model):
        gait = Gait(model, walk='kick', idle=['raise', 'kick'])

        gait.apply(0.0, 0.0, action=3)

        assert gait.idle.tracks[-1].name == 'kick'


class TestWanderingCrowd:
    def test_a_figure_taken_in_comes_back_as_a_node_to_mount(self, model):
        crowd = WanderingCrowd((-6.0, 6.0, -6.0, 6.0))

        transform = crowd.add(model, position=(1.0, 2.0), heading=0.0)

        assert transform.children == [model.group]
        assert len(crowd) == 1
        assert len(crowd.crowd) == 1

    def test_a_model_facing_the_other_way_is_turned_to_match(self, document):
        """A model authored facing -Z has to be turned round once, not have
        the arithmetic bent around it."""
        crowd = WanderingCrowd((-20.0, 20.0, -20.0, 20.0), facing=np.pi)
        crowd.add(CharacterModel(load_gltf(document=document)),
                  position=(0.0, 0.0), heading=0.4)

        crowd.update(DT)

        assert crowd.transforms[0].rotation[3] == pytest.approx(0.4 + np.pi)
        assert crowd.wander.heading[0] == pytest.approx(0.4)

    def test_a_frame_walks_the_figures_and_poses_them(self, document):
        crowd = WanderingCrowd((-20.0, 20.0, -20.0, 20.0), elevation=0.25)
        models = []
        for index in range(6):
            one = CharacterModel(load_gltf(document=document))
            models.append(one)
            crowd.add(one, position=(index - 2.5, 0.0), heading=0.0)
        before = [_pose_of(one) for one in models]

        for _ in range(90):
            posed = crowd.update(DT)

        assert posed == 6
        placed = [tuple(t.translation) for t in crowd.transforms]
        assert len({place[0] for place in placed}) == 6, 'they piled up'
        assert all(place[1] == 0.25 for place in placed)
        assert any(not np.allclose(was, _pose_of(one))
                   for was, one in zip(before, models, strict=True))

    def test_the_near_figures_are_posed_more_often_than_the_far_ones(
            self, document):
        crowd = WanderingCrowd((-40.0, 40.0, -40.0, 40.0), fade=0.0,
                               stand=(60.0, 60.0), walk=(60.0, 60.0))
        for distance in (1.0, 12.0, 30.0):
            crowd.add(CharacterModel(load_gltf(document=document)),
                      position=(0.0, -distance), heading=0.0)

        crowd.schedule((0.0, 1.7, 0.0), ((5.0, 0.0), (20.0, 12.0),
                                        (float('inf'), 4.0)))

        assert [member.rate for member in crowd.members] == [0.0, 12.0, 4.0]

    def test_a_figure_that_walks_out_of_the_near_band_asks_for_less(
            self, document):
        """Which figures are near changes every frame once they walk."""
        crowd = WanderingCrowd((-40.0, 40.0, -40.0, 40.0), fade=0.0,
                               speed=(3.0, 3.0), walk=(60.0, 60.0))
        crowd.add(CharacterModel(load_gltf(document=document)),
                  position=(0.0, 0.0), heading=0.0)
        bands = ((5.0, 0.0), (float('inf'), 4.0))

        crowd.schedule((0.0, 0.0, 0.0), bands)
        near = crowd.members[0].rate
        for _ in range(120):
            crowd.update(DT)
        crowd.schedule((0.0, 0.0, 0.0), bands)

        assert near == 0.0
        assert crowd.members[0].rate == 4.0

    def test_a_field_all_walking_is_posed_in_one_run(self, document):
        crowd = WanderingCrowd((-12.0, 12.0, -12.0, 12.0),
                               walk=(60.0, 60.0), fade=0.0)
        for index in range(10):
            crowd.add(CharacterModel(load_gltf(document=document)),
                      position=(index - 4.5, 0.0), heading=0.0)

        crowd.update(DT)

        assert crowd.crowd.groups == 1

    def test_a_field_where_some_have_stopped_takes_a_run_for_each_kind(
            self, document):
        """A standing figure has the walk out of its pose altogether, which is
        a different run of arithmetic from a figure that is walking."""
        crowd = WanderingCrowd((-12.0, 12.0, -12.0, 12.0),
                               walk=(60.0, 60.0), fade=0.0)
        for index in range(10):
            crowd.add(CharacterModel(load_gltf(document=document)),
                      position=(index - 4.5, 0.0), heading=0.0)
        crowd.update(DT)
        crowd.wander.state[:5] = STAND
        crowd.wander.timer[:5] = 60.0

        crowd.update(DT)

        assert crowd.crowd.groups == 2

    def test_the_figures_are_not_all_doing_the_same_thing(self, document):
        """The whole point: a crowd of individuals rather than one figure
        drawn a hundred times."""
        crowd = WanderingCrowd((-12.0, 12.0, -12.0, 12.0))
        for index in range(24):
            crowd.add(CharacterModel(load_gltf(document=document)),
                      position=(index % 6 - 2.5, index // 6 - 1.5))

        for _ in range(600):
            crowd.update(DT)

        assert len(set(np.round(crowd.wander.moving, 3).tolist())) > 1
        assert len(set(int(state) for state in crowd.wander.state)) > 1


class TestTheDemoDoesNotMoonwalk:
    """The crowd demo's figures travel the way their clips carry them.

    Two numbers decide that, and neither can be guessed from the mesh: which
    way the model's forward points, and how far each locomotion clip carries it
    in a second. Get the first wrong and the bodies travel backwards through
    their own cycle; get the second wrong and the legs run at the wrong rate
    for the speed. Both show up in one measurement -- **the parts touching the
    ground should stay on the ground** -- and neither shows up in a still
    frame, because a stride looks the same forwards and backwards until
    something moves.

    Read off the posed mesh rather than a foot bone, so it holds for a
    quadruped as readily as for a figure with a humanoid skeleton. No GL: the
    pose reaches the scenegraph either way.
    """

    # Each clip over the speeds the demo actually plays it at: a gallop dialled
    # down to a stroll has a suspension phase and nothing on the ground to
    # measure, and the demo never asks for one.
    @pytest.mark.parametrize('clip,stride,speed', [
        ('WALK', 'WALK_STRIDE', 0.55), ('WALK', 'WALK_STRIDE', 0.8),
        ('WALK', 'WALK_STRIDE', 1.1),
        ('RUN', 'RUN_STRIDE', 1.2), ('RUN', 'RUN_STRIDE', 1.4),
        ('RUN', 'RUN_STRIDE', 1.65),
    ])
    def test_what_touches_the_ground_stays_on_it(self, demo, figure,
                                                 clip, stride, speed):
        name, carries = getattr(demo, clip), getattr(demo, stride)
        model = _figure(figure)
        track = model.play(name)
        mesh = next(_skinned(model.group))
        place = _world(model, mesh)

        step, travelled, seen = 1 / 120.0, 0.0, []
        for _ in range(int(round(track.duration / step))):
            track.speed = speed / carries
            model.update(step)
            # Heading 0 with no `facing` correction, so the body goes +Z.
            travelled += speed * step
            posed = np.asarray(mesh.posed_positions(), 'd') * demo.SCALE
            here = posed @ place[:3, :3] + place[3, :3]
            here[:, 2] += travelled
            seen.append(here)
        seen = np.asarray(seen)

        velocity = np.diff(seen, axis=0) / step
        height = seen[:-1, :, 1]
        floor = np.percentile(height, 3)
        contact = height < floor
        # The median of the signed velocity, not of its size: among the
        # vertices nearest the ground are a swinging paw and the tip of a tail,
        # and only the median of the actual direction is the ground's own.
        residual = np.asarray(
            [np.median(velocity[t][contact[t]][:, [0, 2]], axis=0)
             for t in range(len(velocity)) if contact[t].any()])
        drift = float(np.hypot(*np.median(residual, axis=0)))

        assert drift < speed * FOOT_DRIFT, (
            '%s: what is on the ground travels %.3f m/s over it at a body '
            'speed of %.2f -- the figure is going through its cycle backwards, '
            'or %s is not what the clip carries it'
            % (name, drift, speed, stride))


def _skinned(node, seen=None):
    """Every mesh under ``node`` that a skeleton poses."""
    seen = seen if seen is not None else set()
    if id(node) in seen:
        return
    seen.add(id(node))
    if getattr(node, 'skin_joints', None) is not None:
        yield node
    for name in ('children', 'geometry'):
        value = getattr(node, name, None)
        for child in (value if isinstance(value, (list, tuple))
                      else [value] if value is not None else []):
            yield from _skinned(child, seen)


def _world(model, node):
    """The transform from ``node``'s own space into the model group's."""
    def path_to(target, node, above=()):
        if node is target:
            return above
        for child in (getattr(node, 'children', None) or []):
            found = path_to(target, child, above + (node,))
            if found is not None:
                return found
        return None

    matrix = np.eye(4)
    for step in (path_to(node, model.group) or ()) + (node,):
        local = getattr(step, 'localMatrices', None)
        if local is None:
            continue
        forward = local().data[0]
        if forward is not None:
            matrix = np.asarray(forward, 'd') @ matrix
    return matrix


def _pose_of(model):
    """Where every joint of a figure has ended up."""
    return np.concatenate([
        np.asarray([list(x.translation) for x in model.mixer.rig.transforms]),
        np.asarray([list(x.rotation) for x in model.mixer.rig.transforms]),
        np.asarray([list(x.scale) for x in model.mixer.rig.transforms]),
    ], axis=1)
