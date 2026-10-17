"""What grows on the ground between the trees.

A wood with bare ground under it is trees standing on a lawn. What makes the
floor of one read as a floor is *cover*: clumps of grass you can see the blades
of within a few tens of metres, and cards beyond that out to where the haze
takes over. Neither is baked -- the ground is the same everywhere and there is
far too much of it -- so the set is scattered on a world-anchored grid around
the camera and re-chosen as it moves. A cell's fate never changes as the disc
recentres, so nothing pops.

Where it grows is decided by the ground itself: the splat control map already
says where the grass and the leaf litter are, and it already has the road's
corridor painted out of them.
"""
import gc
import json
import weakref

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.scenegraph.terrain import HeightField, LayerRule, control_map
from OpenGLContext.scenegraph.vegetation.cover import (
    CoverSpecies,
    GroundCover,
    control_weight,
)

EXTENT = 1024.0


def _field(res=65):
    grid = np.zeros((res, res))
    return HeightField(grid, EXTENT, 10.0)


def _species(**named):
    named.setdefault('name', 'grass')
    named.setdefault('card', 'grass.png')
    return CoverSpecies(**named)


def _cover(**named):
    named.setdefault('field', _field())
    named.setdefault('species', _species())
    return GroundCover(**named)


class TestWhatItHolds:
    def test_a_card_layer_is_always_built(self) -> None:
        assert _cover().rungs[0].cards is not None

    def test_clumps_are_built_only_when_there_is_a_clump(self) -> None:
        assert _cover().rungs[0].clumps_near is None

    def test_the_rungs_are_its_children(self) -> None:
        assert len(_cover().children) >= 1

    def test_it_needs_a_card_to_draw(self) -> None:
        with pytest.raises(ValueError):
            GroundCover(_field(), CoverSpecies(name='g', card=''))

    def test_a_species_reads_as_its_name(self) -> None:
        assert 'grass' in repr(_species())

    def test_it_survives_a_round_trip_through_json(self) -> None:
        entry = _species(clump='c.glb', density=2.5)
        back = CoverSpecies.from_json(json.loads(json.dumps(entry.to_json())))
        assert back.to_json() == entry.to_json()

    def test_its_files_resolve_against_a_directory(self) -> None:
        found = _species(clump='c.glb').beside('/worlds/one')
        assert found.card == '/worlds/one/grass.png'
        assert found.clump == '/worlds/one/c.glb'

    def test_a_species_with_no_clump_resolves_anyway(self) -> None:
        assert not _species().beside('/worlds/one').clump


class TestWhereItGrows:
    def test_it_follows_the_camera(self) -> None:
        cover = _cover(card_radius=120.0)
        cover.update((0.0, 0.0, 0.0))
        here = cover.rungs[0].cards.pos.copy()
        cover.update((400.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.pos[:, 0].mean()) \
            > float(here[:, 0].mean()) + 100.0

    def test_it_reaches_as_far_as_it_is_told(self) -> None:
        cover = _cover(card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(np.hypot(cover.rungs[0].cards.pos[:, 0],
                              cover.rungs[0].cards.pos[:, 2]).max()) <= 91.0

    def test_it_sits_on_the_ground(self) -> None:
        def sloping(x, _z):
            return np.asarray(x, 'd') * 0.0 + 7.0
        field = HeightField(np.ones((33, 33)), EXTENT, 7.0)
        cover = GroundCover(field, _species(), card_radius=80.0)
        cover.update((0.0, 0.0, 0.0))
        assert np.allclose(cover.rungs[0].cards.pos[:, 1], 7.0, atol=0.01)

    def test_denser_means_more_of_it(self) -> None:
        thin = _cover(species=_species(density=0.5), card_radius=100.0)
        thick = _cover(species=_species(density=4.0), card_radius=100.0)
        thin.update((0.0, 0.0, 0.0))
        thick.update((0.0, 0.0, 0.0))
        assert len(thick.rungs[0].cards.pos) > len(thin.rungs[0].cards.pos) * 4

    def test_standing_still_costs_nothing(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        before = cover.selections
        cover.update((0.4, 0.0, 0.4))
        assert cover.selections == before

    def test_moving_costs_one(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        before = cover.selections
        cover.update((40.0, 0.0, 0.0))
        assert cover.selections == before + 1

    def test_ground_driven_back_over_is_not_scattered_again(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        cover.update((40.0, 0.0, 0.0))
        scattered = cover.scattered
        for _lap in range(3):
            cover.update((0.0, 0.0, 0.0))
            cover.update((40.0, 0.0, 0.0))
        assert cover.scattered == scattered

    def test_moving_on_scatters_only_the_ground_newly_reached(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        first = cover.scattered
        cover.update((40.0, 0.0, 0.0))
        assert 0 < cover.scattered - first < first / 2

    def test_a_cell_keeps_its_place_as_the_disc_moves(self) -> None:
        """World-anchored, so nothing appears or shifts as you drive past."""
        cover = _cover(card_radius=150.0)
        cover.update((0.0, 0.0, 0.0))
        watched = {tuple(np.round(one, 3)) for one in cover.rungs[0].cards.pos
                   if abs(one[0]) < 30.0 and abs(one[2]) < 30.0}
        cover.update((60.0, 0.0, 0.0))
        after = {tuple(np.round(one, 3)) for one in cover.rungs[0].cards.pos}
        assert watched and watched <= after


class TestWhereItDoesNot:
    def _control(self):
        field = _field()
        rules = [LayerRule(slope=(0.0, 1e9)), LayerRule(slope=(1e8, 1e9))]
        painted = np.zeros((64, 64))
        painted[:, :32] = 1.0                    # the west half is rock
        return control_map(field, rules, size=64, painted=[(1, painted)])

    def test_a_mask_keeps_it_off_the_ground_it_names(self) -> None:
        mask = control_weight(self._control(), ['grass'], ['grass', 'rock'],
                              EXTENT)
        cover = _cover(card_radius=400.0, mask=mask)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.pos[:, 0].min()) > -60.0

    def test_it_still_grows_where_the_mask_allows(self) -> None:
        mask = control_weight(self._control(), ['grass'], ['grass', 'rock'],
                              EXTENT)
        cover = _cover(card_radius=400.0, mask=mask)
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) > 100

    def test_a_weight_is_read_by_world_position(self) -> None:
        mask = control_weight(self._control(), ['grass'], ['grass', 'rock'],
                              EXTENT)
        west = float(mask(np.array([-400.0]), np.array([0.0]))[0])
        east = float(mask(np.array([400.0]), np.array([0.0]))[0])
        assert west < 0.1 < east

    def test_a_layer_the_map_does_not_have_weighs_nothing(self) -> None:
        mask = control_weight(self._control(), ['moss'], ['grass', 'rock'],
                              EXTENT)
        assert float(mask(np.array([400.0]), np.array([0.0]))[0]) == 0.0

    def test_without_a_mask_it_grows_everywhere(self) -> None:
        cover = _cover(card_radius=200.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.pos[:, 0].min()) < -150.0


def _round_hole(radius=60.0):
    """A hole field: an opening of ``radius`` metres around the origin."""
    def holes(x, z):
        return np.hypot(np.asarray(x, 'd'),
                        np.asarray(z, 'd')) < radius
    return holes


class TestWhereTheGroundIsNotThere:
    """A bore's mouth is a hole cut in the ground, and the height field under
    it still answers with a height. What is seated on that answer without
    asking whether the ground is there stands in the opening, in mid-air, in
    plain view through the portal."""

    def test_nothing_grows_in_the_opening(self) -> None:
        cover = _cover(card_radius=300.0, holes=_round_hole())
        cover.update((0.0, 0.0, 0.0))
        away = np.hypot(cover.rungs[0].cards.pos[:, 0],
                        cover.rungs[0].cards.pos[:, 2])
        assert float(away.min()) >= 60.0

    def test_and_it_grows_everywhere_else(self) -> None:
        cover = _cover(card_radius=300.0, holes=_round_hole())
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) > 100

    def test_a_hole_told_to_it_afterwards_is_in_time(self) -> None:
        """A game stands the ground up from a tileset and finds out where the
        bores are from the roads, which it reads second."""
        cover = _cover(card_radius=300.0)
        cover.holes = _round_hole()
        cover.update((0.0, 0.0, 0.0))
        away = np.hypot(cover.rungs[0].cards.pos[:, 0],
                        cover.rungs[0].cards.pos[:, 2])
        assert float(away.min()) >= 60.0

    def test_a_hole_told_to_it_after_it_has_grown_clears_the_opening(self) -> None:
        cover = _cover(card_radius=300.0)
        cover.update((0.0, 0.0, 0.0))
        cover.holes = _round_hole()
        cover.update((0.0, 0.0, 0.0))
        away = np.hypot(cover.rungs[0].cards.pos[:, 0],
                        cover.rungs[0].cards.pos[:, 2])
        assert float(away.min()) >= 60.0

    def test_it_is_the_mask_and_the_hole_together(self) -> None:
        """Neither answers the other's question: the mask says what ground
        this plant grows on, the hole says whether there is ground at all."""
        grew = _cover(card_radius=300.0, mask=lambda x, _z: np.where(
            np.asarray(x, 'd') > 0.0, 1.0, 0.0))
        grew.holes = _round_hole()
        grew.update((0.0, 0.0, 0.0))
        placed = grew.rungs[0].cards.pos
        assert float(placed[:, 0].min()) > 0.0
        assert float(np.hypot(placed[:, 0], placed[:, 2]).min()) >= 60.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestItStandsInTheSameLightAsTheGroundDoes:
    """Grass lit like an open field, on ground the canopy has darkened to a
    fifth, reads as a row of lamps on the forest floor."""

    def _shade(self):
        def at(x, _z):
            return np.where(np.asarray(x, 'd') < 0.0, 0.2, 1.0)
        return at

    def test_without_a_shade_it_is_all_in_full_sun(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        assert cover.rungs[0].cards.shades is None

    def test_with_one_each_card_carries_its_own(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.shades) == len(cover.rungs[0].cards.pos)

    def test_the_shaded_side_is_darker(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.update((0.0, 0.0, 0.0))
        west = cover.rungs[0].cards.shades[cover.rungs[0].cards.pos[:, 0] < -10.0]
        east = cover.rungs[0].cards.shades[cover.rungs[0].cards.pos[:, 0] > 10.0]
        assert float(west.mean()) < 0.3 < float(east.mean())

    def test_the_clumps_are_shaded_too(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.rungs[0].clumps_near = _Recording()
        cover.rungs[0].clumps_far = _Recording()
        cover.update((0.0, 0.0, 0.0))
        assert cover.rungs[0].clumps_near.shades is not None


class _Recording:
    """A stand-in for the clump layer, which needs a .glb and a GL context."""

    def __init__(self):
        self.shades = None

    def update_instances(self, positions, _yaws, _scales, shades=None):
        self.pos, self.shades = positions, shades


class TestItDoesNotGrowInRows:
    """A jittered grid is still a grid if nothing may leave its own cell: from
    thirty metres the tufts line up into diagonals and the ground reads as a
    planted field. Letting a cell's instance land in its neighbour's ground
    breaks the lattice, and clumps and gaps are what real cover looks like."""

    def _spacing(self, cover):
        """How far each tuft is from its nearest neighbour."""
        points = cover.rungs[0].cards.pos[:, [0, 2]]
        near = points[np.hypot(points[:, 0], points[:, 1]) < 25.0]
        gaps = np.hypot(near[:, None, 0] - near[None, :, 0],
                        near[:, None, 1] - near[None, :, 1])
        np.fill_diagonal(gaps, 1e9)
        return gaps.min(axis=1)

    def test_the_gaps_between_tufts_vary(self) -> None:
        cover = _cover(card_radius=60.0, species=_species(density=1.0))
        cover.update((0.0, 0.0, 0.0))
        gaps = self._spacing(cover)
        assert float(gaps.std()) > 0.40 * float(gaps.mean())

    def test_it_still_covers_the_ground(self) -> None:
        cover = _cover(card_radius=60.0, species=_species(density=1.0))
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) > 2500


class TestNothingToGrow:
    """No density is no cover: a quality setting of 0, or a species with none."""

    def test_a_density_scale_of_nothing_grows_nothing(self) -> None:
        cover = _cover()
        cover.density_scale = 0.0
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) == 0

    def test_a_species_of_no_density_grows_nothing(self) -> None:
        cover = _cover(species=_species(density=0.0))
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) == 0


class TestAControlMapThatIsNotSquare:
    def test_each_axis_is_read_across_its_own_width(self) -> None:
        pixels = np.zeros((16, 64, 4), 'u1')
        pixels[:, 56:64, 0] = 255                  # the eastern eighth is grass
        weigh = control_weight(Image.fromarray(pixels), ['grass'],
                               ['grass', 'rock', 'dirt', 'snow'], 200.0)
        assert weigh(np.array([90.0]), np.array([0.0]))[0] == 1.0
        assert weigh(np.array([0.0]), np.array([0.0]))[0] == 0.0

    def test_a_map_taller_than_it_is_wide_is_read_too(self) -> None:
        pixels = np.zeros((64, 16, 4), 'u1')
        pixels[56:64, :, 0] = 255                  # the southern eighth
        weigh = control_weight(Image.fromarray(pixels), ['grass'],
                               ['grass'], 200.0)
        assert weigh(np.array([0.0]), np.array([90.0]))[0] == 1.0
        assert weigh(np.array([0.0]), np.array([0.0]))[0] == 0.0


class TestToldWhileScattering:
    def test_a_hole_told_during_a_scatter_is_not_undone_by_it(self) -> None:
        """A scatter on a worker can be told a new hole by the render thread
        at any point. What it made from the old ground must not be kept for
        the new."""
        cover = _cover(card_radius=60.0)
        opening = _round_hole()
        finisher = cover._finisher  # noqa: SLF001 the step a background scatter ends with, wrapped to change the holes mid-scatter

        def told_meanwhile(rung):
            if cover.holes is None:
                cover.holes = opening        # as the render thread would
            return finisher(rung)
        cover._finisher = told_meanwhile  # noqa: SLF001 the step a background scatter ends with, wrapped to change the holes mid-scatter
        cover.compute_near(0.0, 0.0)
        cards = cover.compute_near(0.0, 0.0)[0][0][0]
        assert not opening(cards[:, 0], cards[:, 2]).any()

class TestScatteredInTheBackground:
    """A cover told ``background=True`` scatters on a worker thread, so the
    frame that crosses a threshold pays nothing for it."""

    @staticmethod
    def _rows(cover):
        return sorted(map(tuple, np.round(cover.rungs[0].cards.pos, 4)))

    def test_it_grows_the_same_cover(self) -> None:
        aside = _cover(card_radius=100.0, background=True)
        inline = _cover(card_radius=100.0)
        try:
            aside.update((0.0, 0.0, 0.0))
            assert aside.wait(5.0)
            aside.update((0.0, 0.0, 0.0))
            inline.update((0.0, 0.0, 0.0))
            assert len(inline.rungs[0].cards.pos) > 100
            assert self._rows(aside) == self._rows(inline)
        finally:
            aside.shutdown()

    def test_the_frame_that_asks_does_not_wait(self) -> None:
        aside = _cover(card_radius=100.0, background=True)
        try:
            aside.update((0.0, 0.0, 0.0))
            assert aside.selections == 1
            assert aside.wait(5.0)
        finally:
            aside.shutdown()

    def test_waiting_on_an_inline_cover_is_immediate(self) -> None:
        assert _cover().wait(0.0)

    def test_an_inline_cover_still_grows_after_a_shutdown(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.shutdown()
        cover.update((0.0, 0.0, 0.0))
        assert cover.wait(0.0)
        assert len(cover.rungs[0].cards.pos) > 100


class TestTheWorkerIsLetGo:
    def test_a_failed_scatter_is_asked_for_again(self) -> None:
        cover = _cover(card_radius=100.0, background=True)
        failures = []

        def mask(x, _z):
            if not failures:
                failures.append(True)
                raise RuntimeError('a mask that fails once')
            return np.ones(np.shape(x))
        cover.mask = mask
        try:
            for _frame in range(4):          # at one place: no step to re-ask
                cover.update((0.0, 0.0, 0.0))
                assert cover.wait(5.0)
            assert len(cover.rungs[0].cards.pos) > 100
        finally:
            cover.shutdown()

    def test_a_cover_dropped_without_shutdown_stops_its_thread(self) -> None:
        cover = _cover(card_radius=100.0, background=True)
        cover.update((0.0, 0.0, 0.0))
        assert cover.wait(5.0)
        thread = cover._worker._thread  # noqa: SLF001 the cover's scatter thread, to see it end with the cover
        gone = weakref.ref(cover)
        del cover
        gc.collect()
        assert gone() is None
        thread.join(5.0)
        assert not thread.is_alive()


class TestFollowingAFastCamera:
    """A scatter that takes a second to arrive is for where the camera will be then.

    A vehicle covers tens of metres in the time a scatter takes, so a disc centred on
    the camera at the moment of asking is behind it by the time it is drawn.
    """

    SPEED = 24.0

    @pytest.fixture
    def clock(self, monkeypatch):
        from OpenGLContext.events import systemtime
        now = [0.0]
        monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
        return now

    def drive(self, cover, clock, seconds, speed=None, start=0.0):
        """Update at 30 Hz along -z at ``speed``; returns the camera's last z."""
        speed = self.SPEED if speed is None else speed
        z = start
        for _frame in range(int(seconds * 30)):
            clock[0] += 1.0 / 30.0
            z -= speed / 30.0
            cover.update((0.0, 0.0, z))
        return z

    @staticmethod
    def centre(cover):
        return float(cover.rungs[0].cards.pos[:, 2].mean())

    def test_the_disc_is_centred_where_the_camera_will_be_when_it_arrives(self, clock) -> None:
        cover = _cover(card_radius=100.0)
        cover.latency = 1.0
        z = self.drive(cover, clock, 3.0)
        # The disc is scattered every SETTLED_METRES: it is for where the camera is
        # about to be, a lead of up to a second's travel past the camera.
        assert z - 2 * self.SPEED < self.centre(cover) < z - 0.5 * self.SPEED

    def test_a_camera_standing_still_has_its_disc_about_it(self, clock) -> None:
        cover = _cover(card_radius=100.0)
        cover.latency = 1.0
        z = self.drive(cover, clock, 2.0, speed=0.0)
        assert abs(self.centre(cover) - z) < 3.0

    def test_a_cover_that_has_never_been_slow_leads_nothing(self, clock) -> None:
        cover = _cover(card_radius=100.0)
        z = self.drive(cover, clock, 3.0)
        assert cover.latency == 0.0
        assert abs(self.centre(cover) - z) < 12.0

    def test_a_jump_in_position_is_not_a_speed(self, clock) -> None:
        cover = _cover(card_radius=100.0)
        cover.latency = 1.0
        cover.update((0.0, 0.0, 0.0))
        clock[0] += 0.001
        cover.update((0.0, 0.0, -400.0))
        assert abs(self.centre(cover) + 400.0) < 5.0

    def test_the_cards_reach_further_ahead_of_a_fast_camera_than_their_radius(self, clock) -> None:
        cover = _cover(card_radius=100.0)
        cover.latency = 1.0
        z = self.drive(cover, clock, 3.0)
        reach = float(z - cover.rungs[0].cards.pos[:, 2].min())
        assert reach > 100.0 + 0.5 * self.SPEED

    def test_how_long_a_scatter_takes_to_arrive_is_measured_after_the_first(self) -> None:
        cover = _cover(card_radius=100.0, background=True)
        try:
            cover.update((0.0, 0.0, 0.0))
            assert cover.wait(5.0)
            cover.update((0.0, 0.0, 0.0))          # the first scatter makes everything: not counted
            assert cover.latency == 0.0
            cover.update((40.0, 0.0, 0.0))
            assert cover.wait(5.0)
            cover.update((40.0, 0.0, 0.0))
            assert cover.latency > 0.0
        finally:
            cover.shutdown()

    def test_the_near_cover_does_not_wait_for_the_far(self) -> None:
        import threading
        import time
        release = threading.Event()
        cover = _cover(card_radius=100.0, background=True)
        original = cover.compute_far

        def slow_far(x, z):
            release.wait(10.0)
            return original(x, z)
        cover.compute_far = slow_far
        try:
            cover.update((0.0, 0.0, 0.0))
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline and len(cover.rungs[0].cards.pos) < 100:
                cover.update((0.0, 0.0, 0.0))
                time.sleep(0.01)
            assert len(cover.rungs[0].cards.pos) > 100
            assert len(cover.rungs[0].far_cards.pos) == 0
        finally:
            release.set()
            cover.shutdown()


class TestNoFarField:
    def test_a_cover_has_a_far_field_where_it_is_told_to_run_past_the_cards(self) -> None:
        assert _cover(card_radius=100.0, far_radius=400.0).has_far
        assert not _cover(card_radius=100.0, far_radius=100.0).has_far

    def test_with_none_it_is_neither_scattered_nor_staged(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        assert cover.compute_far(0.0, 0.0) == []
        assert len(cover.rungs[0].far_cards.pos) == 0
        assert len(cover.rungs[0].cards.pos) > 100

    def test_with_one_it_is_staged(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=400.0)
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].far_cards.pos) > 0


class TestHowSoonItFades:
    def test_the_cards_dissolve_across_the_fraction_of_their_radius_it_is_told(self) -> None:
        wide = _cover(card_radius=100.0, far_radius=300.0, fade=0.5)
        default = _cover(card_radius=100.0, far_radius=300.0)
        assert wide.rungs[0].far_cards.near_cut == pytest.approx(50.0)
        assert default.rungs[0].far_cards.near_cut == pytest.approx(80.0)

    def test_it_can_be_changed_and_the_windows_follow(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=300.0)
        cover.fade = 0.6
        cover.retune()
        assert cover.rungs[0].far_cards.near_cut == pytest.approx(60.0)


class TestPreparedAhead:
    """The ground a camera is about to cross is scattered before it gets there, so the disc
    that reaches it is only put together."""

    def test_blocks_are_built_ahead_and_the_disc_that_reaches_them_builds_none(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        cover.prepare([(0.0, -60.0), (0.0, -120.0)])
        built = cover.scattered
        cover.update((0.0, 0.0, -60.0))
        assert cover.scattered == built

    def test_without_it_the_same_move_builds_blocks(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        built = cover.scattered
        cover.update((0.0, 0.0, -60.0))
        assert cover.scattered > built

    def test_preparing_ground_already_scattered_costs_nothing(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        built = cover.scattered
        cover.prepare([(0.0, -10.0)])
        cover.prepare([(0.0, -10.0)])
        assert cover.scattered <= built + 12

    def test_it_stages_nothing_itself(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        before = cover.rungs[0].cards.pos.copy()
        cover.prepare([(0.0, -90.0)])
        assert np.array_equal(cover.rungs[0].cards.pos, before)

    def test_in_the_background_it_is_done_by_a_worker_and_waited_for(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0, background=True)
        try:
            cover.update((0.0, 0.0, 0.0))
            assert cover.wait(5.0)
            built = cover.scattered
            cover.prepare([(0.0, -80.0)])
            assert cover.wait(5.0)
            assert cover.scattered > built
        finally:
            cover.shutdown()

    def test_ground_prepared_beyond_what_is_kept_is_let_go_by_the_next_disc(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        cover.prepare([(0.0, -900.0)])
        cover.update((0.0, 0.0, -20.0))
        far = cover.rungs[0]
        blocks = cover._blocks[(far, 'cards')][1]  # noqa: SLF001 the cache this checks is bounded
        assert all(abs((bj + 0.5) * blocks.span + 20.0) < 2.0 * 100.0 + 2 * blocks.span
                   for _bi, bj in blocks._blocks)  # noqa: SLF001 the cache this checks is bounded
