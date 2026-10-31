"""A character's state into clips: which play, at what weight and rate.

The table tests run :class:`Locomotion` with no model, so they read the clips,
weights and rates it settles on with no skeleton and no window. The bound tests
give it a model and read the mixer.
"""
import pytest

import pygltflib

from OpenGLContext.character import CharacterModel
from OpenGLContext.character.locomotion import (
    ROLES, ClipMap, ClipSpec, Locomotion, LocomotionInput,
)

from ._locomotion_assets import striding, walker_glb, waving

#: The clips hill-runner plays, by the names the Universal Animation Library
#: gives them.
HILL_RUNNER_CLIPS = ('Jog_Fwd_Loop', 'Sprint_Loop', 'Jump_Start', 'Jump_Loop',
                     'Slide', 'Death01', 'Roll')

#: The library's own clip names, as `runner.glb` carries them.
UAL_NAMES = (
    'A_TPose', 'Crouch_Fwd_Loop', 'Crouch_Idle_Loop', 'Dance_Loop', 'Death01',
    'Driving_Loop', 'Fixing_Kneeling', 'Hit_Chest', 'Hit_Head', 'Idle_Loop',
    'Idle_Talking_Loop', 'Idle_Torch_Loop', 'Interact', 'Jog_Fwd_Loop',
    'Jump_Land', 'Jump_Loop', 'Jump_Start', 'PickUp_Table', 'Pistol_Aim_Down',
    'Pistol_Aim_Neutral', 'Pistol_Aim_Up', 'Pistol_Idle_Loop', 'Pistol_Reload',
    'Pistol_Shoot', 'Punch_Cross', 'Punch_Jab', 'Push_Loop', 'Roll',
    'Sitting_Enter', 'Sitting_Exit', 'Sitting_Idle_Loop', 'Sitting_Talking_Loop',
    'Spell_Simple_Enter', 'Spell_Simple_Exit', 'Spell_Simple_Idle_Loop',
    'Spell_Simple_Shoot', 'Sprint_Loop', 'Swim_Fwd_Loop', 'Swim_Idle_Loop',
    'Sword_Attack', 'Sword_Idle', 'Walk_Formal_Loop', 'Walk_Loop', 'Slide')


def simple_map(**more):
    roles = dict(
        idle='idle', walk=('walk', 1.4), run=('run', 3.8), sprint=('sprint', 6.0),
        crouch_idle='crouch_idle', crouch_walk=('crouch_walk', 0.9),
        jump_up='jump_up', jump_down='jump_down', fall='fall', land='land',
        slide='slide', swim=('swim', 1.5), down='down', get_up='get_up',
        death='death')
    roles.update(more)
    return ClipMap(**{k: v for k, v in roles.items() if v is not None})


def settle(clip_map=None, dt=1 / 60, **fields):
    return Locomotion(clip_map or simple_map()).update(
        LocomotionInput(**fields), dt)


class TestClipMap:
    def test_a_role_is_a_clip_name_or_a_name_and_an_authored_speed(self):
        clip_map = ClipMap(idle='Idle', walk=('Walk', 1.4),
                           run=ClipSpec('Run', speed=3.8, cycle=0.7))
        assert clip_map.spec('idle') == ClipSpec('Idle')
        assert clip_map.spec('walk') == ClipSpec('Walk', speed=1.4)
        assert clip_map.spec('run').cycle == 0.7
        assert clip_map.spec('sprint') is None

    def test_a_role_that_does_not_exist_is_refused_with_the_list(self):
        with pytest.raises(TypeError, match='sprint'):
            ClipMap(sprinting='Run')

    def test_every_role_is_named(self):
        assert ROLES == (
            'idle', 'walk', 'run', 'sprint', 'crouch_idle', 'crouch_walk',
            'jump_up', 'jump_down', 'land', 'slide', 'fall', 'swim', 'down',
            'get_up', 'death')

    def test_a_map_reads_as_its_roles(self):
        assert repr(ClipMap(idle='Idle', walk=('Walk', 1.4))) == \
            "ClipMap(idle='Idle', walk='Walk')"

    def test_the_clips_are_listed_once_each(self):
        clip_map = ClipMap(jump_down='Loop', fall='Loop', idle='Idle')
        assert clip_map.clips() == ('Idle', 'Loop')

    def test_the_roles_a_model_lacks_the_clip_for_are_named(self):
        model = CharacterModel.load(walker_glb({'idle': waving(1.0)}))
        assert ClipMap(idle='idle', walk='walk').missing(model) == ('walk',)


class TestTheLibraryVocabulary:
    def test_every_clip_hill_runner_plays_has_a_role(self):
        assert set(HILL_RUNNER_CLIPS) <= set(ClipMap.ual().clips())

    def test_every_role_it_names_is_a_clip_of_the_library(self):
        assert set(ClipMap.ual().clips()) <= set(UAL_NAMES)

    def test_the_locomotion_clips_carry_the_speeds_they_were_measured_at(self):
        ual = ClipMap.ual()
        speeds = [ual.spec(role).speed for role in ('walk', 'run', 'sprint')]
        assert speeds == sorted(speeds)
        assert all(speed > 0 for speed in speeds)

    def test_the_run_and_the_sprint_say_when_their_feet_land(self):
        for role in ('walk', 'run', 'sprint'):
            contacts = ClipMap.ual().spec(role).contacts
            assert sorted(foot for foot, _ in contacts) == ['left', 'right']

    def test_the_library_fits_a_model_that_carries_it(self):
        model = CharacterModel.load(walker_glb(
            {name: waving(1.0) for name in UAL_NAMES}))
        assert ClipMap.ual().missing(model) == ()


class TestGuessing:
    def test_clips_named_for_their_roles_resolve(self):
        model = CharacterModel.load(walker_glb(
            {'walk': waving(1.0), 'run': waving(1.0), 'idle': waving(1.0)}))
        found = ClipMap.guess(model)
        assert [found.spec(r).clip for r in ('idle', 'walk', 'run')] == [
            'idle', 'walk', 'run']
        assert found.leftover == ()
        assert 'sprint' in found.unmatched
        assert 'idle' not in found.unmatched

    def test_unrecognised_clips_are_reported_as_left_over(self):
        model = CharacterModel.load(walker_glb(
            {'walk': waving(1.0), 'dance': waving(1.0), 'wave': waving(1.0)}))
        assert ClipMap.guess(model).leftover == ('dance', 'wave')

    def test_the_library_is_found_by_name_alone(self):
        model = CharacterModel.load(walker_glb(
            {name: waving(1.0) for name in UAL_NAMES}))
        found = ClipMap.guess(model)
        expected = {
            'idle': 'Idle_Loop', 'walk': 'Walk_Loop', 'run': 'Jog_Fwd_Loop',
            'sprint': 'Sprint_Loop', 'crouch_idle': 'Crouch_Idle_Loop',
            'crouch_walk': 'Crouch_Fwd_Loop', 'jump_up': 'Jump_Start',
            'jump_down': 'Jump_Loop', 'fall': 'Jump_Loop', 'land': 'Jump_Land',
            'slide': 'Slide', 'swim': 'Swim_Fwd_Loop', 'death': 'Death01'}
        assert {r: found.spec(r).clip for r in ROLES if found.spec(r)} == expected
        assert found.unmatched == ('down', 'get_up')
        assert 'Dance_Loop' in found.leftover
        assert 'Idle_Loop' not in found.leftover

    def test_camel_case_names_are_split_into_words(self):
        model = CharacterModel.load(walker_glb(
            {'JumpStart': waving(1.0), 'JumpLand': waving(1.0),
             'CrouchIdle': waving(1.0)}))
        found = ClipMap.guess(model)
        assert found.spec('jump_up').clip == 'JumpStart'
        assert found.spec('land').clip == 'JumpLand'
        assert found.spec('crouch_idle').clip == 'CrouchIdle'

    def test_the_plainest_name_wins_among_several(self):
        model = CharacterModel.load(walker_glb(
            {'Walk_Formal_Loop': waving(1.0), 'Walk_Loop': waving(1.0)}))
        assert ClipMap.guess(model).spec('walk').clip == 'Walk_Loop'

    def test_roles_given_by_hand_fill_the_gaps_and_win_over_a_guess(self):
        model = CharacterModel.load(walker_glb(
            {'Walk': waving(1.0), 'Stroll': waving(1.0), 'Survey': waving(1.0)}))
        found = ClipMap.guess(model, idle='Survey', walk=('Stroll', 1.1))
        assert found.spec('idle').clip == 'Survey'
        assert (found.spec('walk').clip, found.spec('walk').speed) == ('Stroll', 1.1)
        assert 'idle' not in found.unmatched
        assert 'walk' not in found.unmatched
        assert found.leftover == ('Walk',)

    def test_a_model_with_no_clips_matches_nothing(self):
        model = CharacterModel.load(walker_glb({}))
        found = ClipMap.guess(model)
        assert found.unmatched == ROLES
        assert found.leftover == ()


class TestStanding:
    """The idle, walk, run and sprint blend by speed."""

    def test_standing_still_plays_the_idle(self):
        found = settle(speed=0.0)
        assert (found.role, found.clips) == ('idle', {'idle': 1.0})

    def test_a_creep_below_the_threshold_is_standing(self):
        assert settle(speed=0.02).role == 'idle'

    def test_walking_at_the_authored_speed_plays_the_walk_at_rate_one(self):
        found = settle(speed=1.4)
        assert found.role == 'walk'
        assert found.clips == {'walk': pytest.approx(1.0)}
        assert found.rates['walk'] == pytest.approx(1.0)

    def test_the_rate_is_speed_over_the_authored_speed(self):
        found = settle(speed=1.05)
        assert found.rates['walk'] == pytest.approx(0.75)

    def test_below_the_slowest_rate_the_idle_shows_through(self):
        found = settle(speed=0.4)
        assert found.rates['walk'] == pytest.approx(0.55)
        assert 0 < found.clips['idle'] < 0.5
        assert sum(found.clips.values()) == pytest.approx(1.0)

    def test_between_the_walk_and_the_run_both_play(self):
        found = settle(speed=2.6)
        assert found.clips == {'walk': pytest.approx(0.5), 'run': pytest.approx(0.5)}
        assert found.rates['walk'] == pytest.approx(2.6 / 1.4)
        assert found.rates['run'] == pytest.approx(2.6 / 3.8)

    def test_running_at_the_authored_speed(self):
        found = settle(speed=3.8)
        assert (found.role, found.clips) == ('run', {'run': pytest.approx(1.0)})

    def test_between_the_run_and_the_sprint_both_play(self):
        found = settle(speed=4.9)
        assert found.clips == {'run': pytest.approx(0.5), 'sprint': pytest.approx(0.5)}

    def test_sprinting_flat_out_is_at_the_top_of_the_rate_range(self):
        found = settle(speed=60.0)
        assert found.role == 'sprint'
        assert found.rates['sprint'] == pytest.approx(2.1)

    def test_a_map_with_no_sprint_runs_instead(self):
        found = settle(simple_map(sprint=None), speed=9.0)
        assert found.role == 'run'
        assert found.rates['run'] == pytest.approx(2.1)

    def test_a_map_with_no_run_walks_up_to_the_sprint(self):
        found = settle(simple_map(run=None), speed=4.0)
        share = (4.0 - 1.4) / (6.0 - 1.4)
        assert found.clips == {'walk': pytest.approx(1 - share),
                               'sprint': pytest.approx(share)}

    def test_a_map_with_only_an_idle_stands_whatever_the_speed(self):
        found = settle(ClipMap(idle='idle'), speed=5.0)
        assert (found.role, found.clips, found.rates) == ('idle', {'idle': 1.0}, {})

    def test_a_map_with_nothing_plays_nothing(self):
        found = settle(ClipMap(), speed=5.0)
        assert (found.role, found.clips) == ('idle', {})

    def test_a_rate_range_the_map_declares_is_used(self):
        clip_map = simple_map()
        wide = ClipMap(idle='idle', walk=('walk', 1.0), rate_range=(0.25, 4.0))
        assert settle(wide, speed=3.5).rates['walk'] == pytest.approx(3.5)
        assert settle(clip_map, speed=5.0).rates['run'] == pytest.approx(5.0 / 3.8)

    def test_a_walk_with_no_authored_speed_has_one_to_go_by(self):
        found = settle(ClipMap(idle='idle', walk='walk'), speed=1.4)
        assert found.clips == {'walk': pytest.approx(1.0)}
        assert found.rates['walk'] == pytest.approx(1.0)


class TestStances:
    def test_crouching_still_plays_the_crouch_idle(self):
        found = settle(state='crouching', crouching=True)
        assert (found.role, found.clips) == ('crouch_idle', {'crouch_idle': 1.0})

    def test_crouching_while_moving_plays_the_crouch_walk(self):
        found = settle(state='crouching', crouching=True, speed=0.9)
        assert (found.role, found.clips) == (
            'crouch_walk', {'crouch_walk': pytest.approx(1.0)})
        assert found.rates['crouch_walk'] == pytest.approx(1.0)

    def test_standing_up_eases_the_crouch_out(self):
        locomotion = Locomotion(simple_map())
        locomotion.update(LocomotionInput(crouching=True), 1 / 60)
        halfway = locomotion.update(LocomotionInput(), 0.075)
        assert halfway.clips == {'crouch_idle': pytest.approx(0.5),
                                 'idle': pytest.approx(0.5)}
        done = locomotion.update(LocomotionInput(), 0.2)
        assert done.clips == {'idle': 1.0}

    def test_crouching_while_moving_keeps_the_weights_proportional(self):
        locomotion = Locomotion(simple_map())
        locomotion.update(LocomotionInput(speed=0.9), 1 / 60)
        mid = locomotion.update(LocomotionInput(speed=0.9, crouching=True), 0.075)
        assert sum(mid.clips.values()) == pytest.approx(1.0)
        assert mid.clips['crouch_walk'] == pytest.approx(0.5)
        assert mid.clips['walk'] == pytest.approx(0.5)

    def test_a_map_with_no_crouch_clips_keeps_standing(self):
        found = settle(simple_map(crouch_idle=None, crouch_walk=None),
                       state='crouching', crouching=True)
        assert found.role == 'idle'

    def test_a_crouch_with_no_crouch_walk_stays_in_the_idle(self):
        found = settle(simple_map(crouch_walk=None), crouching=True, speed=1.0)
        assert found.clips == {'crouch_idle': 1.0}

    def test_a_crouch_walk_with_no_crouch_idle_shows_only_while_moving(self):
        found = settle(simple_map(crouch_idle=None), crouching=True, speed=0.9)
        assert found.clips['crouch_walk'] == pytest.approx(1.0)


class TestOffTheGround:
    def test_rising_plays_the_jump(self):
        found = settle(state='airborne', grounded=False, vertical_speed=4.0)
        assert (found.role, found.clips) == ('jump_up', {'jump_up': 1.0})

    def test_falling_plays_the_descent(self):
        found = settle(state='airborne', grounded=False, vertical_speed=-2.0)
        assert (found.role, found.clips) == ('jump_down', {'jump_down': 1.0})

    def test_a_long_fall_plays_the_fall(self):
        found = settle(state='airborne', grounded=False, vertical_speed=-12.0)
        assert found.role == 'fall'

    def test_a_map_with_no_fall_uses_the_descent(self):
        found = settle(simple_map(fall=None), state='airborne',
                       grounded=False, vertical_speed=-12.0)
        assert found.role == 'jump_down'

    def test_not_standing_on_anything_is_airborne_whatever_the_state_says(self):
        assert settle(grounded=False, vertical_speed=3.0).role == 'jump_up'

    def test_flying_plays_the_fall_or_carries_on_walking(self):
        assert settle(state='flying', grounded=False).role == 'fall'
        assert settle(simple_map(fall=None), state='flying', grounded=False,
                      speed=1.4).role == 'walk'

    def test_swimming_plays_the_stroke_at_the_speed_it_covers(self):
        found = settle(state='swimming', grounded=False, speed=0.75)
        assert (found.role, found.clips) == ('swim', {'swim': 1.0})
        assert found.rates['swim'] == pytest.approx(0.55)

    def test_a_map_with_only_a_fall_uses_it_for_every_descent(self):
        found = settle(simple_map(jump_down=None), state='airborne',
                       grounded=False, vertical_speed=-1.0)
        assert found.role == 'fall'

    def test_a_map_with_no_airborne_clips_keeps_the_ground_pose(self):
        found = settle(ClipMap(idle='idle'), state='airborne', grounded=False,
                       vertical_speed=4.0)
        assert found.role == 'idle'


class TestSliding:
    def test_the_slide_is_held_at_the_point_its_progress_names(self):
        found = settle(state='sliding', slide_progress=0.25)
        assert (found.role, found.clips) == ('slide', {'slide': 1.0})
        assert found.progress == pytest.approx(0.25)

    def test_progress_is_kept_within_the_clip(self):
        assert settle(state='sliding', slide_progress=3.0).progress == 1.0
        assert settle(state='sliding', slide_progress=-1.0).progress == 0.0

    def test_other_roles_have_no_progress(self):
        assert settle(speed=2.0).progress is None


class TestLanding:
    def test_landing_plays_for_a_while_and_then_goes_back_to_moving(self):
        locomotion = Locomotion(simple_map(land=ClipSpec('land', cycle=0.3)))
        first = locomotion.update(LocomotionInput(landing_speed=8.0), 1 / 60)
        assert first.role == 'land'
        assert first.clips['land'] == pytest.approx(1.0)
        later = locomotion.update(LocomotionInput(), 0.2)
        assert later.role == 'land'
        done = locomotion.update(LocomotionInput(), 0.2)
        assert done.role == 'idle'

    def test_a_soft_landing_shows_only_part_of_the_clip(self):
        found = settle(simple_map(land=ClipSpec('land', cycle=0.3)),
                       speed=1.4, landing_speed=3.0)
        assert found.clips['land'] == pytest.approx(0.5)
        assert found.clips['walk'] == pytest.approx(0.5)

    def test_the_landing_clip_has_a_default_length_when_none_is_known(self):
        locomotion = Locomotion(simple_map())
        locomotion.update(LocomotionInput(landing_speed=8.0), 1 / 60)
        assert locomotion.update(LocomotionInput(), 0.3).role == 'land'
        assert locomotion.update(LocomotionInput(), 0.2).role == 'idle'

    def test_jumping_again_before_the_landing_ends_takes_over(self):
        locomotion = Locomotion(simple_map())
        locomotion.update(LocomotionInput(landing_speed=8.0), 1 / 60)
        found = locomotion.update(LocomotionInput(
            state='airborne', grounded=False, vertical_speed=5.0), 1 / 60)
        assert found.role == 'jump_up'


class TestDownAndDead:
    def test_knocked_down_plays_the_fall_over(self):
        found = settle(state='down')
        assert (found.role, found.clips) == ('down', {'down': 1.0})

    def test_getting_up_plays_the_get_up_and_then_moves_again(self):
        locomotion = Locomotion(simple_map(get_up=ClipSpec('get_up', cycle=0.5)))
        locomotion.update(LocomotionInput(state='down'), 1 / 60)
        rising = locomotion.update(LocomotionInput(), 1 / 60)
        assert rising.role == 'get_up'
        assert locomotion.update(LocomotionInput(), 0.3).role == 'get_up'
        assert locomotion.update(LocomotionInput(), 0.3).role == 'idle'

    def test_a_get_up_of_unknown_length_is_skipped(self):
        locomotion = Locomotion(simple_map())
        locomotion.update(LocomotionInput(state='down'), 1 / 60)
        assert locomotion.update(LocomotionInput(), 1 / 60).role == 'idle'

    def test_a_map_with_no_get_up_goes_straight_back_to_moving(self):
        locomotion = Locomotion(simple_map(get_up=None))
        locomotion.update(LocomotionInput(state='down'), 1 / 60)
        assert locomotion.update(LocomotionInput(), 1 / 60).role == 'idle'

    def test_a_dead_character_plays_the_death_over_everything(self):
        found = settle(state='airborne', grounded=False, dead=True)
        assert (found.role, found.clips) == ('death', {'death': 1.0})

    def test_a_map_with_no_down_clip_keeps_moving(self):
        assert settle(simple_map(down=None), state='down').role == 'idle'


class TestFootsteps:
    """Two a cycle, at the times the map names or the half cycle."""

    CYCLE = 0.933

    def _run(self, clip_map, seconds=2.0, speed=10.0, dt=1 / 240):
        locomotion = Locomotion(clip_map)
        heard = []
        locomotion.on_footstep(lambda foot, phase: heard.append((foot, phase)))
        events = []
        for step in range(int(seconds / dt)):
            found = locomotion.update(LocomotionInput(speed=speed), dt)
            events.extend(((step + 1) * dt, foot, phase)
                          for foot, phase in found.footsteps)
        return events, heard

    def _map(self, **spec):
        return ClipMap(idle='idle', run=ClipSpec(
            'run', speed=10.0, cycle=self.CYCLE, **spec))

    def test_a_foot_lands_twice_a_cycle_at_the_times_the_map_names(self):
        events, _ = self._run(self._map(
            contacts=(('right', 0.2), ('left', 0.7))))
        wanted = [(0.2, 'right'), (0.7, 'left'),
                  (0.2 + self.CYCLE, 'right'), (0.7 + self.CYCLE, 'left')]
        found = [(t, foot) for t, foot, _ in events]
        assert [foot for _, foot in found] == [foot for _, foot in wanted]
        for (at, _), (expected, _) in zip(found, wanted, strict=True):
            assert at == pytest.approx(expected, abs=1 / 120)

    def test_the_events_are_evenly_spaced_when_the_contacts_are(self):
        events, _ = self._run(self._map())
        times = [t for t, _, _ in events]
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        assert len(times) == 4
        assert all(g == pytest.approx(self.CYCLE / 2, abs=1 / 120) for g in gaps)

    def test_without_contacts_they_fall_at_the_half_cycle(self):
        events, _ = self._run(self._map())
        assert [foot for _, foot, _ in events] == ['right', 'left', 'right', 'left']
        assert events[0][0] == pytest.approx(self.CYCLE / 2, abs=1 / 120)

    def test_the_phase_is_the_cycle_fraction_of_the_contact(self):
        events, _ = self._run(self._map(contacts=(('right', 0.2), ('left', 0.7))))
        assert events[0][2] == pytest.approx(0.2 / self.CYCLE, abs=0.02)

    def test_callbacks_hear_every_step_once(self):
        events, heard = self._run(self._map())
        assert [foot for foot, _ in heard] == [foot for _, foot, _ in events]

    def test_a_faster_body_steps_faster(self):
        slow, _ = self._run(self._map(), speed=10.0)
        fast, _ = self._run(self._map(), speed=20.0)
        assert len(fast) > len(slow)

    def test_standing_still_makes_no_footsteps(self):
        events, _ = self._run(self._map(), speed=0.0)
        assert events == []

    def test_a_large_step_reports_each_foot_that_landed_in_it(self):
        locomotion = Locomotion(self._map())
        found = locomotion.update(LocomotionInput(speed=10.0), 2.0)
        assert [foot for foot, _ in found.footsteps] == [
            'right', 'left', 'right', 'left']

    def test_a_clip_with_no_known_cycle_makes_no_footsteps(self):
        clip_map = ClipMap(idle='idle', run=('run', 10.0))
        locomotion = Locomotion(clip_map)
        found = locomotion.update(LocomotionInput(speed=10.0), 2.0)
        assert found.footsteps == ()

    def test_in_the_air_the_cycle_waits(self):
        locomotion = Locomotion(self._map())
        locomotion.update(LocomotionInput(speed=10.0), 0.3)
        found = locomotion.update(LocomotionInput(
            speed=10.0, state='airborne', grounded=False, vertical_speed=3.0), 5.0)
        assert found.footsteps == ()

    def test_a_slide_makes_no_footsteps(self):
        locomotion = Locomotion(ClipMap(
            run=ClipSpec('run', speed=10.0, cycle=self.CYCLE), slide='slide'))
        found = locomotion.update(LocomotionInput(
            speed=10.0, state='sliding', slide_progress=0.5), 5.0)
        assert found.footsteps == ()


@pytest.fixture
def walker():
    return CharacterModel.load(walker_glb({
        'idle': waving(2.0), 'walk': striding(1.0), 'run': striding(0.5),
        'sprint': striding(0.4), 'crouch_idle': waving(2.0),
        'crouch_walk': striding(1.5), 'jump_up': waving(0.5),
        'jump_down': waving(0.5), 'land': waving(0.3), 'slide': waving(0.8),
        'fall': waving(0.5), 'swim': waving(1.0), 'down': waving(1.0),
        'get_up': waving(0.8), 'death': waving(1.5), 'fire': waving(0.4)}))


def bound(model, **more):
    return Locomotion(simple_map(**more), model, measure_missing=False)


def effective(model, names):
    """What each clip contributes to the pose, from the layers' weights."""
    result = {}
    carried = 1.0
    for layer in reversed(model.mixer.layers):
        track = layer.current
        if track is None or layer.weight <= 0:
            continue
        if layer.name in names:
            share = layer.weight * track.target
            result[track.name] = result.get(track.name, 0.0) + carried * share
            carried *= 1.0 - share
    return {name: weight for name, weight in result.items() if weight > 1e-9}


LOCOMOTION_LAYERS = {'idle', 'walk', 'run', 'sprint', 'crouch_walk',
                     'crouch_idle', 'action'}


class TestBoundToAModel:
    def test_the_mixer_is_left_playing_what_was_settled(self, walker):
        locomotion = bound(walker)
        found = locomotion.update(LocomotionInput(speed=2.6), 1 / 60)
        assert effective(walker, LOCOMOTION_LAYERS) == pytest.approx(found.clips)

    @pytest.mark.parametrize('speed', [0.0, 0.4, 1.4, 2.6, 3.8, 4.9, 6.0, 30.0])
    def test_the_layers_blend_to_the_weights_it_reports(self, walker, speed):
        found = bound(walker).update(LocomotionInput(speed=speed), 1 / 60)
        assert effective(walker, LOCOMOTION_LAYERS) == pytest.approx(found.clips)

    @pytest.mark.parametrize('moving', [0.0, 0.9])
    def test_a_crouch_blends_to_the_weights_it_reports(self, walker, moving):
        locomotion = bound(walker)
        locomotion.update(LocomotionInput(speed=moving), 1 / 60)
        found = locomotion.update(
            LocomotionInput(speed=moving, crouching=True), 0.075)
        assert effective(walker, LOCOMOTION_LAYERS) == pytest.approx(found.clips)

    def test_a_slow_crouch_walk_blends_the_idle_and_the_walk(self, walker):
        found = bound(walker).update(
            LocomotionInput(speed=0.3, crouching=True), 1 / 60)
        assert set(found.clips) == {'crouch_idle', 'crouch_walk'}
        assert effective(walker, LOCOMOTION_LAYERS) == pytest.approx(found.clips)

    def test_each_looping_clip_plays_at_the_rate_reported(self, walker):
        found = bound(walker).update(LocomotionInput(speed=2.6), 1 / 60)
        speeds = {layer.name: layer.current.speed for layer in walker.mixer.layers
                  if layer.name in found.rates and layer.current}
        assert speeds == pytest.approx(found.rates)

    def test_rising_plays_the_jump_on_the_action_layer(self, walker):
        locomotion = bound(walker)
        locomotion.update(LocomotionInput(
            state='airborne', grounded=False, vertical_speed=4.0), 1 / 60)
        assert walker.mixer.layer('action').current.name == 'jump_up'

    def test_the_action_layer_fades_out_when_the_action_ends(self, walker):
        locomotion = bound(walker)
        locomotion.update(LocomotionInput(
            state='airborne', grounded=False, vertical_speed=4.0), 1 / 60)
        locomotion.update(LocomotionInput(), 1 / 60)
        assert walker.mixer.layer('action').current is None

    def test_each_new_action_starts_from_its_beginning(self, walker):
        locomotion = bound(walker)
        rising = LocomotionInput(state='airborne', grounded=False, vertical_speed=4.0)
        locomotion.update(rising, 1 / 60)
        walker.update(0.3)
        locomotion.update(LocomotionInput(), 1 / 60)
        locomotion.update(rising, 1 / 60)
        assert walker.mixer.layer('action').current.time == 0.0

    def test_a_slide_is_held_at_its_progress(self, walker):
        locomotion = bound(walker)
        locomotion.update(LocomotionInput(state='sliding', slide_progress=0.5), 1 / 60)
        track = walker.mixer.layer('action').current
        assert (track.time, track.speed) == (pytest.approx(0.4), 0.0)

    def test_a_soft_landing_weights_the_action_layer(self, walker):
        locomotion = bound(walker)
        found = locomotion.update(LocomotionInput(speed=1.4, landing_speed=3.0), 1 / 60)
        assert walker.mixer.layer('action').weight == pytest.approx(0.5)
        assert effective(walker, LOCOMOTION_LAYERS) == pytest.approx(found.clips)

    def test_the_landing_lasts_as_long_as_its_clip(self, walker):
        locomotion = bound(walker)
        locomotion.update(LocomotionInput(landing_speed=8.0), 1 / 60)
        assert locomotion.update(LocomotionInput(), 0.25).role == 'land'
        assert locomotion.update(LocomotionInput(), 0.1).role == 'idle'

    def test_the_cycles_of_the_blended_clips_share_one_phase(self, walker):
        locomotion = bound(walker)
        for _ in range(50):
            locomotion.update(LocomotionInput(speed=2.6), 1 / 60)
            walker.update(1 / 60)
        walk = walker.mixer.layer('walk').current
        run = walker.mixer.layer('run').current
        assert walk.time / walk.duration == pytest.approx(
            run.time / run.duration, abs=0.05)

    def test_footsteps_follow_the_clip_lengths_when_the_map_gives_no_cycle(self, walker):
        locomotion = bound(walker)
        found = locomotion.update(LocomotionInput(speed=3.8), 1.0)
        assert [foot for foot, _ in found.footsteps] == ['right', 'left'] * 2

    def test_clips_the_model_lacks_are_left_out_and_named(self, walker):
        model = CharacterModel.load(walker_glb({'idle': waving(1.0)}))
        locomotion = Locomotion(simple_map(), model, measure_missing=False)
        assert 'walk' in locomotion.missing
        found = locomotion.update(LocomotionInput(speed=5.0), 1 / 60)
        assert found.clips == {'idle': 1.0}

    def test_a_clip_with_no_authored_speed_is_measured(self, walker):
        locomotion = Locomotion(ClipMap(idle='idle', walk='walk'), walker)
        assert locomotion.speeds['walk'] == pytest.approx(1.0 / 0.6, rel=0.03)

    def test_a_measured_speed_is_in_the_units_the_model_is_drawn_at(self, walker):
        walker.group.scale = (2.0, 2.0, 2.0)                  # as add_character fits it
        locomotion = Locomotion(ClipMap(idle='idle', walk='walk'), walker)
        assert locomotion.speeds['walk'] == pytest.approx(2.0 / 0.6, rel=0.03)

    def test_a_declared_speed_wins_over_the_measurement(self, walker):
        locomotion = Locomotion(ClipMap(idle='idle', walk=('walk', 2.0)), walker)
        assert locomotion.speeds['walk'] == 2.0

    def test_a_clip_that_plants_no_foot_keeps_the_default_speed(self, walker):
        locomotion = Locomotion(ClipMap(idle='idle', walk='idle'), walker)
        assert locomotion.speeds['walk'] == 1.4

    def test_a_skeleton_without_feet_keeps_the_default_speed(self, walker):
        del walker.humanoid.bones['leftFoot']
        locomotion = Locomotion(ClipMap(idle='idle', walk='walk'), walker)
        assert locomotion.speeds['walk'] == 1.4

    def test_a_model_without_a_skeleton_keeps_the_default_speed(self, walker):
        walker.humanoid = None
        locomotion = Locomotion(ClipMap(idle='idle', walk='walk'), walker)
        assert locomotion.speeds['walk'] == 1.4


class TestActions:
    def test_an_action_plays_once_on_the_upper_body(self, walker):
        locomotion = bound(walker)
        track = locomotion.play_action('fire')
        layer = walker.mixer.layer('upper')
        assert layer.current is track
        assert track.name == 'fire'
        assert not track.loop
        assert layer.mask == walker.mask('spine')

    def test_the_layer_is_given_back_when_the_clip_ends(self, walker):
        locomotion = bound(walker)
        locomotion.play_action('fire')
        walker.update(1.0)
        locomotion.update(LocomotionInput(), 1 / 60)
        assert walker.mixer.layer('upper').current is None

    def test_an_action_still_playing_is_left_alone(self, walker):
        locomotion = bound(walker)
        track = locomotion.play_action('fire')
        walker.update(0.1)
        locomotion.update(LocomotionInput(), 1 / 60)
        assert walker.mixer.layer('upper').current is track

    def test_a_named_layer_is_made_on_first_use(self, walker):
        track = bound(walker).play_action('fire', layer='taunt')
        assert walker.mixer.layer('taunt').current is track

    def test_an_action_the_model_lacks_is_none(self, walker):
        assert bound(walker).play_action('reload') is None

    def test_without_a_model_there_is_nothing_to_play(self):
        assert Locomotion(simple_map()).play_action('fire') is None

