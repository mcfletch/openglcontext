"""Where reflections go in the atlas, and which are drawn each frame; no GL.

:class:`TilePacker` holds each reflection's rectangle in the one atlas, and
:class:`ReflectionSchedule` chooses which mirror views a frame draws and at
what size, within a budget of views, separate views and texels.
"""
import itertools

import pytest

from OpenGLContext.passes.reflectiontiles import (
    Budget, Candidate, ReflectionSchedule, TilePacker,
)

# --- the packer ---------------------------------------------------------------


def _overlap(a, b, gutter):
    return not (a.x + a.width + gutter <= b.x - gutter
                or b.x + b.width + gutter <= a.x - gutter
                or a.y + a.height + gutter <= b.y - gutter
                or b.y + b.height + gutter <= a.y - gutter)


def _assert_disjoint_and_inside(packer, tiles):
    for tile in tiles.values():
        assert tile.x >= packer.gutter and tile.y >= packer.gutter
        assert tile.x + tile.width + packer.gutter <= packer.width
        assert tile.y + tile.height + packer.gutter <= packer.height
    for a, b in itertools.combinations(tiles.values(), 2):
        assert not _overlap(a, b, packer.gutter)


def test_tiles_are_placed_apart_by_their_gutters():
    packer = TilePacker(512, 256)
    placed = packer.place({'a': (100, 60), 'b': (80, 60), 'c': (200, 30),
                           'd': (40, 120)})
    assert set(placed.tiles) == {'a', 'b', 'c', 'd'}
    assert placed.tiles['a'].width == 100 and placed.tiles['a'].height == 60
    _assert_disjoint_and_inside(packer, placed.tiles)
    assert not placed.moved and not placed.unplaced


def test_a_tile_that_keeps_its_size_keeps_its_place():
    packer = TilePacker(512, 256)
    first = packer.place({'a': (100, 60), 'b': (80, 60)})
    second = packer.place({'a': (100, 60), 'b': (120, 60), 'c': (64, 64)})
    assert second.tiles['a'] == first.tiles['a']
    assert 'a' not in second.moved


def test_a_tile_no_longer_asked_for_is_released():
    packer = TilePacker(256, 128)
    packer.place({'a': (200, 100)})
    placed = packer.place({'b': (200, 100)})
    assert set(placed.tiles) == {'b'} and not placed.unplaced


def test_when_nothing_fits_the_packer_repacks_and_says_what_moved():
    packer = TilePacker(256, 256)
    packer.place({'small': (20, 20), 'wide': (200, 100)})
    packer.place({'wide': (200, 100)})         # the small one is released...
    placed = packer.place({'wide': (200, 100), 'tall': (100, 120),
                           'other': (100, 120)})
    _assert_disjoint_and_inside(packer, placed.tiles)
    assert set(placed.tiles) == {'wide', 'tall', 'other'}
    assert placed.moved <= {'wide'}


def test_a_tile_larger_than_the_atlas_is_left_out():
    packer = TilePacker(128, 128)
    placed = packer.place({'huge': (400, 20), 'fits': (32, 32)})
    assert placed.unplaced == {'huge'}
    assert set(placed.tiles) == {'fits'}


def test_resizing_the_atlas_places_everything_again():
    packer = TilePacker(128, 128)
    packer.place({'a': (32, 32)})
    packer.resize(256, 256)
    placed = packer.place({'a': (32, 32)})
    assert set(placed.tiles) == {'a'} and not placed.moved


# --- the schedule -------------------------------------------------------------

def _candidate(key, area=10000.0, priority=1.0, interval=3, texels=4096,
               age=None, valid=None, drift=0.0, separate=False):
    return Candidate(key=key, area=area, priority=priority, interval=interval,
                     texels=texels, age=age,
                     valid=(age is not None) if valid is None else valid,
                     drift=drift, separate=separate)


BIG = Budget(views=16, separate_views=4, texels=10 ** 9)


def test_a_mirror_without_a_tile_is_drawn():
    chosen = ReflectionSchedule().choose([_candidate('a')], BIG)
    assert [(d.key, d.scale) for d in chosen] == [('a', 1.0)]


def test_a_fresh_tile_is_not_drawn_again_before_its_interval_when_the_budget_is_spent():
    budget = Budget(views=1, separate_views=1, texels=10 ** 9)
    chosen = ReflectionSchedule().choose(
        [_candidate('fresh', age=1, area=10 ** 6), _candidate('new')], budget)
    assert [d.key for d in chosen] == ['new']


def test_a_tile_at_its_interval_must_be_drawn():
    budget = Budget(views=1, separate_views=1, texels=10 ** 9)
    chosen = ReflectionSchedule().choose(
        [_candidate('due', age=3, area=1.0), _candidate('optional', age=1,
                                                        area=10 ** 6)], budget)
    assert [d.key for d in chosen] == ['due']


def test_a_camera_that_moved_too_far_forces_a_draw():
    budget = Budget(views=1, separate_views=1, texels=10 ** 9)
    chosen = ReflectionSchedule().choose(
        [_candidate('moved', age=1, drift=3.0, area=1.0),
         _candidate('optional', age=1, area=10 ** 6)], budget)
    assert [d.key for d in chosen] == ['moved']


def test_with_room_to_spare_optional_tiles_are_drawn_too():
    chosen = ReflectionSchedule().choose(
        [_candidate('a', age=1), _candidate('b', age=2)], BIG)
    assert {d.key for d in chosen} == {'a', 'b'}


def test_the_view_budget_is_never_exceeded():
    candidates = [_candidate(n) for n in range(30)]
    chosen = ReflectionSchedule().choose(
        candidates, Budget(views=16, separate_views=16, texels=10 ** 9))
    assert len(chosen) == 16


def test_the_separate_view_budget_is_never_exceeded():
    candidates = ([_candidate(('s', n), separate=True) for n in range(6)]
                  + [_candidate(('p', n)) for n in range(6)])
    chosen = ReflectionSchedule().choose(
        candidates, Budget(views=16, separate_views=4, texels=10 ** 9))
    assert sum(1 for d in chosen if d.key[0] == 's') == 4
    assert sum(1 for d in chosen if d.key[0] == 'p') == 6


def test_the_texel_budget_is_never_exceeded():
    candidates = [_candidate(n, texels=1000, age=5) for n in range(20)]
    chosen = ReflectionSchedule().choose(
        candidates, Budget(views=16, separate_views=16, texels=5000))
    assert sum(1000 * d.scale ** 2 for d in chosen) <= 5000


def test_a_short_budget_halves_scale_before_leaving_a_tile_stale():
    candidates = [_candidate('large', texels=4000, area=4.0),
                  _candidate('small', texels=4000, area=1.0)]
    chosen = ReflectionSchedule().choose(
        candidates, Budget(views=16, separate_views=16, texels=5000))
    assert {(d.key, d.scale) for d in chosen} == {('large', 1.0), ('small', 0.5)}


def test_a_candidate_passed_over_rises_until_it_is_drawn():
    """Six mirrors, a budget of two a frame, and intervals none of them force."""
    schedule = ReflectionSchedule()
    budget = Budget(views=2, separate_views=2, texels=10 ** 9)
    ages = {n: 1 for n in range(6)}
    drawn_at = {n: [] for n in ages}
    for frame in range(30):
        chosen = schedule.choose(
            [_candidate(n, area=100.0 * (n + 1), interval=1000, age=age)
             for n, age in ages.items()], budget)
        for n in ages:
            ages[n] += 1
        for decision in chosen:
            ages[decision.key] = 1
            drawn_at[decision.key].append(frame)
    assert all(drawn_at[n] for n in ages)
    assert len(drawn_at[5]) > len(drawn_at[0])


def test_every_mirror_is_drawn_within_its_interval_while_the_budget_allows():
    schedule = ReflectionSchedule()
    budget = Budget(views=4, separate_views=4, texels=10 ** 9)
    intervals = {n: 2 + n % 3 for n in range(8)}   # three views a frame
    ages = {n: None for n in intervals}
    fitted = 0
    for _frame in range(40):
        due = {n for n in intervals
               if ages[n] is None or ages[n] >= intervals[n]}
        chosen = schedule.choose(
            [_candidate(n, interval=intervals[n], age=ages[n]) for n in intervals],
            budget)
        drawn = {d.key for d in chosen}
        if len(due) <= budget.views:
            fitted += 1
            assert due <= drawn
        for n in intervals:
            ages[n] = 1 if n in drawn else (None if ages[n] is None else ages[n] + 1)
    assert fitted > 30


def test_the_time_target_scales_the_texels_between_a_quarter_and_all():
    schedule = ReflectionSchedule()
    for _ in range(100):
        schedule.measured(milliseconds=20.0, target=1.0)
    assert schedule.time_scale == pytest.approx(0.25)
    for _ in range(100):
        schedule.measured(milliseconds=0.1, target=1.0)
    assert schedule.time_scale == pytest.approx(1.0)


def test_the_time_scale_shrinks_the_texels_a_frame_draws():
    schedule = ReflectionSchedule()
    for _ in range(100):
        schedule.measured(milliseconds=20.0, target=1.0)
    candidates = [_candidate(n, texels=1000, age=5) for n in range(8)]
    chosen = schedule.choose(candidates, Budget(views=16, separate_views=16,
                                                texels=8000))
    assert sum(1000 * d.scale ** 2 for d in chosen) <= 2000
