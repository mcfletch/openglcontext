"""The character tutorials: each script's context, run in a hidden window, does what its page says.

The scripts are loaded and drawn on the fixed clock of
:mod:`tests.unit.test_physics_tutorials`, so a run is the same on every machine.
"""
import numpy as np
import pytest

from .test_physics_tutorials import running


def loaded(run, attribute='model', seconds=30.0):
    """Draw frames until the context's model has arrived from the loader."""
    assert run.until(lambda: getattr(run.context, attribute) is not None, seconds=seconds)


# -- using_clips: playing a canned animation -------------------------------------------


def test_the_clip_plays_on_the_engine_clock_with_no_idle_loop(gl_context):
    with running('core_context', 'using_clips') as run:
        loaded(run)
        track = run.context.model.mixer.layer().current
        before = track.time
        run.seconds(0.5)
        assert track.name == 'Survey'
        assert track.time - before == pytest.approx(0.5, abs=0.05)
        assert 'OnIdle' not in vars(run.module.TestContext)


def test_a_key_fades_into_the_next_clip(gl_context):
    with running('core_context', 'using_clips') as run:
        loaded(run)
        run.context.OnNext(None)
        run.seconds(0.5)
        assert run.context.model.mixer.layer().current.name == 'Walk'


# -- using_npc: walking an NPC along a route ---------------------------------------------


def test_the_fox_walks_round_the_wall_to_each_goal_in_turn(gl_context):
    with running('core_context', 'using_npc') as run:
        hero = run.context.hero
        goals = run.module.GOALS
        reached = [goals[-1]]                                # where it starts

        def at_goal():
            here = np.asarray(hero.position)[[0, 2]]
            for goal in goals:
                if np.linalg.norm(here - np.asarray(goal)[[0, 2]]) < 0.5 and reached[-1] != goal:
                    reached.append(goal)
            return len(reached) >= 3

        wall_half_length, _, wall_half_thickness = run.module.WALL
        for _ in range(60 * 20):
            run.frame()
            x, _, z = hero.position
            assert not (abs(x) < wall_half_length and abs(z) < wall_half_thickness)
            if at_goal():
                break
        assert reached[1:3] == goals[:2]
        assert 'OnIdle' not in vars(run.module.TestContext)


def test_the_fox_plays_its_walk_while_it_goes(gl_context):
    with running('core_context', 'using_npc') as run:
        run.seconds(1.5)
        settled = run.context.hero.settled
        assert settled.clips.get('Walk', 0.0) + settled.clips.get('Run', 0.0) > 0.5
        assert np.hypot(*run.context.hero.velocity[[0, 2]]) > 1.0


# -- navmesh_demo: a route pulled taut, and a fox that walks it -----------------------------


def test_the_fox_walks_the_pulled_route_rests_and_sets_off_again(gl_context):
    with running('core_context', 'navmesh_demo') as run:
        hero = run.context.hero
        goal = np.asarray(run.module.GOALS[0])[[0, 2]]
        assert run.until(lambda: hero.arrived, seconds=30.0)
        assert np.linalg.norm(np.asarray(hero.position)[[0, 2]] - goal) < 0.5
        run.seconds(run.module.REST - 1.0)
        assert hero.arrived                                     # still resting
        run.seconds(2.0)
        assert not hero.arrived                                 # off to a random point
        assert 'OnIdle' not in vars(run.module.TestContext)


# -- crowd_demo: a crowd of rigged figures --------------------------------------------------


def test_the_crowd_wanders_and_is_posed_on_the_engine_clock(gl_context):
    with running('core_context', 'crowd_demo') as run:
        crowd = run.context.crowd
        assert run.until(lambda: len(crowd) == run.module.FIGURES, seconds=30.0)
        run.frame()
        start = crowd.wander.position.copy()
        run.seconds(2.0)
        moved = np.hypot(*(crowd.wander.position - start).T)
        assert np.count_nonzero(moved > 0.2) > run.module.FIGURES // 3
        assert run.context._posed                          # poses counted each frame
        assert not {'OnIdle', 'OnDraw'} & set(vars(run.module.TestContext))
        assert crowd.gaits[0].walk_stride == pytest.approx(run.module.WALK_STRIDE)


# -- character_animations: a different model and a different animation set --------------


def test_the_guess_fills_the_fox_and_the_man_walks_at_his_measured_pace(gl_context):
    with running('character', 'character_animations') as run:
        fox, man = run.context.fox, run.context.man
        clips = run.context.fox_clips
        assert [clips.spec(role).clip for role in ('idle', 'walk', 'run')] == [
            'Survey', 'Walk', 'Run']
        assert 'idle' not in clips.unmatched and clips.leftover == ()
        measured = man.locomotion.speeds['walk']
        assert measured == pytest.approx(0.9 * 1.8 / 1.5, rel=0.05)    # fitted to the capsule
        run.seconds(3.0)
        for walker, radius in ((fox, 4.0), (man, 7.0)):
            assert np.hypot(walker.position[0], walker.position[2]) == pytest.approx(radius, abs=0.6)
        rate = man.settled.rates['animation0']
        assert rate == pytest.approx(run.module.MAN_SPEED / measured, rel=0.15)


# -- character_camera: a camera that stays out of walls -----------------------------------


def test_the_camera_stays_in_the_room_and_closes_in_at_the_corners(gl_context):
    with running('character', 'character_camera') as run:
        module, context = run.module, run.context
        camera = context.follower.platform.camera
        inside = module.HALF - module.THICK / 2
        arms = []
        run.frame()
        assert run.physics.wait_cooked()                   # the walls are bodies
        for _ in range(60 * 24):
            run.frame()
            eye, look = np.asarray(camera.eye), np.asarray(camera.look)
            assert abs(eye[0]) < inside and abs(eye[2]) < inside
            assert max(abs(eye[0]), abs(eye[2])) > module.PILLAR / 2
            assert eye[1] <= module.HEIGHT - 0.4 + 1e-6
            assert context.physics.line_of_sight(look, eye, skip=context.hero.body)
            arms.append(float(np.linalg.norm(eye - look)))
        assert min(arms) < 0.6 * module.DISTANCE
        assert max(arms) > 0.85 * module.DISTANCE


# -- character_trail: running along a trail ---------------------------------------------------


def test_the_fox_runs_the_trail_and_hops_to_the_lane_asked_for(gl_context):
    with running('character', 'character_trail') as run:
        hero = run.context.hero
        run.seconds(2.0)
        first = hero._path.update(hero.position, 0.0)
        run.seconds(2.0)
        second = hero._path.update(hero.position, 0.0)
        assert second.station - first.station == pytest.approx(2.0 * run.module.SPEED, rel=0.1)
        assert abs(second.lateral_error) < 0.15
        run.context.OnLane(type('Key', (), {'name': '3'})())
        run.seconds(1.0)
        assert hero._path.update(hero.position, 0.0).lateral_error == pytest.approx(1.5, abs=0.2)
        heading = np.arctan2(hero.velocity[0], -hero.velocity[2])
        yaw = run.context._follower.platform.yaw
        assert abs(np.remainder(yaw - heading + np.pi, 2 * np.pi) - np.pi) < 0.35


def test_at_the_end_of_the_trail_the_fox_turns_and_runs_it_back(gl_context):
    with running('character', 'character_trail') as run:
        hero = run.context.hero
        end = run.context.points[-1]
        run.context.OnArrived(hero)
        assert np.allclose(hero._path.course.centreline[0], end)
