"""Ground cover drawn from several kinds of plant, at every rung (no GL).

A forest floor is not one plant repeated. `GroundCover` takes a set of them,
each with its own density and its own size, and draws each through the whole
distance chain: real geometry near the camera in two levels of detail, a card
field beyond that, and a coarse one out to the haze.

The properties that matter are that no two species stand in the same places,
that each keeps the world-anchored placement on its own, that the drawn geometry
tracks the live camera without re-scattering, and that the heavy half of the
work can be handed to a thread that must not touch GL.
"""
import json

import numpy as np
import pytest
from vrml import node
from vrml.protofunctions import getFields

from OpenGLContext.scenegraph.terrain import HeightField
from OpenGLContext.scenegraph.vegetation.cover import (
    CLUMP_LOD_FRAC,
    CoverSpecies,
    GroundCover,
)

EXTENT = 4096.0


def _field(res=65):
    return HeightField(np.zeros((res, res)), EXTENT, 10.0)


def _species(name='grass', **named):
    named.setdefault('card', '%s.png' % (name,))
    return CoverSpecies(name=name, **named)


def _cover(species=None, **named):
    named.setdefault('field', _field())
    named['species'] = species if species is not None else _species()
    return GroundCover(**named)


class TestASpeciesIsANode:
    def test_a_species_is_a_scenegraph_node(self) -> None:
        one = _species()
        assert isinstance(one, node.Node)
        assert {'name', 'card', 'clump', 'clumpMesh', 'clumpFarMesh', 'density',
                'height', 'cardWidth', 'sunLevel', 'patchiness', 'patchMetres',
                'canopy'} <= {entry.name for entry in getFields(one)}

    def test_a_species_writes_itself_out(self) -> None:
        written = _species('fern', density=0.4).toString()
        assert 'CoverSpecies' in written and 'fern' in written

    def test_the_cover_holds_its_species_in_a_field(self) -> None:
        cover = _cover([_species('grass'), _species('fern')])
        assert 'species' in {entry.name for entry in getFields(cover)}
        assert [one.name for one in cover.species] == ['grass', 'fern']

    def test_with_no_canopy_band_it_grows_anywhere(self) -> None:
        assert not len(_species().canopy)

    def test_a_variation_leaves_the_species_it_came_from_alone(self) -> None:
        one = _species()
        wider = one.varied(cardWidth=2.0)
        assert wider.cardWidth == 2.0 and one.cardWidth != 2.0


class TestASetOfPlantsRatherThanOne:
    def test_one_species_may_be_given_on_its_own(self) -> None:
        """The single-species call a baked world makes still means one plant."""
        assert len(_cover(_species()).rungs) == 1

    def test_a_sequence_builds_a_rung_for_each(self) -> None:
        cover = _cover([_species('grass'), _species('fern'), _species('nettle')])
        assert [rung.species.name for rung in cover.rungs] \
            == ['grass', 'fern', 'nettle']

    def test_it_needs_at_least_one_species(self) -> None:
        with pytest.raises(ValueError):
            _cover([])

    def test_every_species_needs_a_card_to_draw(self) -> None:
        with pytest.raises(ValueError):
            _cover([_species('grass'), CoverSpecies(name='fern', card='')])

    def test_a_rung_can_be_found_by_name(self) -> None:
        cover = _cover([_species('grass'), _species('fern')])
        assert cover.rung('fern').species.name == 'fern'

    def test_a_name_it_does_not_have_says_what_it_does(self) -> None:
        cover = _cover([_species('grass')])
        with pytest.raises(KeyError) as raised:
            cover.rung('fern')
        assert 'grass' in str(raised.value)


class TestEachPlantHasItsOwnGround:
    def test_two_species_do_not_stand_in_the_same_places(self) -> None:
        """Salted per species: one grid each, so they interleave rather than
        piling every plant onto the same cells."""
        cover = _cover([_species('grass'), _species('fern')], card_radius=80.0)
        cover.update((0.0, 0.0, 0.0))
        here, there = (
            {(round(float(x), 4), round(float(z), 4))
             for x, z in zip(rung.cards.pos[:, 0], rung.cards.pos[:, 2])}
            for rung in cover.rungs)
        assert here and there and len(here & there) < 0.02 * len(here)

    def test_a_denser_species_puts_down_more_of_itself(self) -> None:
        cover = _cover([_species('sparse', density=0.4),
                        _species('thick', density=4.0)], card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rung('thick').cards.pos) \
            > 4 * len(cover.rung('sparse').cards.pos)

    def test_each_species_keeps_its_place_as_the_disc_moves(self) -> None:
        cover = _cover([_species('grass'), _species('fern')], card_radius=150.0)
        cover.update((0.0, 0.0, 0.0))
        watched = [{tuple(np.round(one, 3)) for one in rung.cards.pos
                    if abs(one[0]) < 20.0 and abs(one[2]) < 20.0}
                   for rung in cover.rungs]
        cover.update((60.0, 0.0, 0.0))
        for seen, rung in zip(watched, cover.rungs):
            after = {tuple(np.round(one, 3)) for one in rung.cards.pos}
            assert seen and seen <= after

    def test_a_species_is_as_tall_as_it_says(self) -> None:
        cover = _cover([_species('low', height=0.3), _species('high', height=1.8)],
                       card_radius=60.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rung('high').cards.scales.mean()) \
            > 4 * float(cover.rung('low').cards.scales.mean())

    def test_a_species_averages_the_height_it_states(self) -> None:
        """Not most of it. A scan measured 0.4 m, so a field of them is 0.4 m
        of plant on average -- a spread that ran from half to full would make
        every plant in the world quietly smaller than what was scanned."""
        cover = _cover([_species('fern', height=0.4)], card_radius=120.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.scales.mean()) \
            == pytest.approx(0.4, abs=0.02)

    def test_plants_of_one_species_are_not_all_the_same_size(self) -> None:
        cover = _cover([_species('fern', height=0.4)], card_radius=120.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.scales.std()) > 0.02


class TestThinningTheWholeFieldAtOnce:
    """What a quality setting moves. Each species says how much of itself there
    should be; a machine that cannot draw that much wants less of all of them,
    in proportion, rather than a different set of plants."""

    def test_it_grows_what_the_species_say_by_default(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        assert cover.density_scale == 1.0
        assert len(cover.rungs[0].cards.pos)

    def test_thinning_it_leaves_less_of_it(self) -> None:
        full = _cover(card_radius=100.0)
        full.update((0.0, 0.0, 0.0))
        thin = _cover(card_radius=100.0)
        thin.density_scale = 0.25
        thin.update((0.0, 0.0, 0.0))
        assert len(thin.rungs[0].cards.pos) \
            < 0.4 * len(full.rungs[0].cards.pos)

    def test_a_setting_changed_while_standing_still_is_drawn_at_once(self) -> None:
        """A quality screen is used standing still; its change cannot wait for
        the camera to walk far enough to scatter again."""
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        full = len(cover.rungs[0].cards.pos)
        cover.density_scale = 0.25
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos) < 0.4 * full

    def test_a_radius_retuned_while_standing_still_is_drawn_at_once(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        cover.card_radius = 50.0
        cover.retune()
        cover.update((0.0, 0.0, 0.0))
        cards = cover.rungs[0].cards.pos
        assert float(np.hypot(cards[:, 0], cards[:, 2]).max()) <= 50.0

    def test_every_species_is_thinned_together(self) -> None:
        """A field that dropped one plant entirely would change what the
        ground is made of, not how much of it there is."""
        cover = _cover([_species('grass', density=3.0),
                        _species('fern', density=0.5)], card_radius=100.0)
        cover.density_scale = 0.3
        cover.update((0.0, 0.0, 0.0))
        assert all(len(rung.cards.pos) for rung in cover.rungs)


class TestPlantsThatGrowInPatches:
    """Undergrowth is not evenly spread. Ferns stand in beds and shrubs in
    thickets, with grass through and between them; a wood where every plant is
    equally likely everywhere reads as a seeded lawn. Each species says how
    much it clumps and how big a clump is, and the answer is a world-anchored
    field, so a bed of nettles is in the same place every time you walk past."""

    def _density_map(self, cover, name, reach=110.0, cells=11):
        """How much of one species stands in each square of a coarse grid."""
        cover.update((0.0, 0.0, 0.0))
        points = cover.rung(name).cards.pos
        edges = np.linspace(-reach, reach, cells + 1)
        counted, _x, _z = np.histogram2d(points[:, 0], points[:, 2],
                                         bins=[edges, edges])
        return counted

    def test_an_even_species_is_much_the_same_everywhere(self) -> None:
        cover = _cover([_species('grass', density=3.0, patchiness=0.0)],
                       card_radius=120.0)
        counted = self._density_map(cover, 'grass')
        assert counted.std() < 0.35 * counted.mean()

    def test_a_patchy_species_is_thick_in_places_and_absent_in_others(self) -> None:
        cover = _cover([_species('fern', density=3.0, patchiness=1.0,
                                 patchMetres=40.0)], card_radius=120.0)
        counted = self._density_map(cover, 'fern')
        assert counted.std() > 0.9 * counted.mean()
        assert counted.min() < 0.25 * counted.max()

    def test_a_patchy_species_still_grows_about_as_much_of_itself(self) -> None:
        """Density is plants per square metre, and it has to keep meaning that
        or every patchy plant quietly thins the whole world out.

        Counted over a stretch of country rather than one disc: beds are tens of
        metres across, so a single disc holds few enough of them that whether it
        happens to contain one is most of the answer. Over a walk it evens out,
        and that is the scale the figure is a figure for.
        """
        def grown(patchiness):
            cover = _cover([_species('fern', density=2.0,
                                     patchiness=patchiness,
                                     patchMetres=24.0)], card_radius=150.0)
            total = 0
            for step in range(9):              # nine discs, a kilometre apart
                cover.update((step * 1000.0, 0.0, step * 700.0))
                total += len(cover.rungs[0].cards.pos)
            return total
        assert grown(1.0) == pytest.approx(grown(0.0), rel=0.15)

    def test_a_bed_is_in_the_same_place_every_time_you_pass(self) -> None:
        cover = _cover([_species('fern', density=3.0, patchiness=1.0,
                                 patchMetres=30.0)], card_radius=140.0)
        cover.update((0.0, 0.0, 0.0))
        watched = {tuple(np.round(one, 3)) for one in cover.rungs[0].cards.pos
                   if abs(one[0]) < 25.0 and abs(one[2]) < 25.0}
        cover.update((70.0, 0.0, 0.0))
        after = {tuple(np.round(one, 3)) for one in cover.rungs[0].cards.pos}
        assert watched and watched <= after

    def test_two_species_do_not_cluster_in_the_same_places(self) -> None:
        """Or the wood would have bare ground and one heap of everything."""
        cover = _cover([_species('fern', density=3.0, patchiness=1.0,
                                 patchMetres=40.0),
                        _species('nettle', density=3.0, patchiness=1.0,
                                 patchMetres=40.0)], card_radius=120.0)
        fern = self._density_map(cover, 'fern').ravel()
        nettle = self._density_map(cover, 'nettle').ravel()
        agreement = np.corrcoef(fern, nettle)[0, 1]
        assert abs(agreement) < 0.5

    def test_a_bigger_patch_size_makes_bigger_beds(self) -> None:
        small = _cover([_species('fern', density=3.0, patchiness=1.0,
                                 patchMetres=12.0)], card_radius=120.0)
        large = _cover([_species('fern', density=3.0, patchiness=1.0,
                                 patchMetres=60.0)], card_radius=120.0)
        # Over a coarse grid, small beds average out within a square and large
        # ones do not, so the coarse map of the large one varies more.
        assert self._density_map(large, 'fern').std() \
            > self._density_map(small, 'fern').std()

    def test_patchiness_still_stops_where_the_ground_says_no(self) -> None:
        """A bed of ferns does not grow through the mask that keeps cover off
        the rock and out of the road."""
        def nothing_west(x, z):
            return np.where(np.asarray(x, 'd') < 0.0, 0.0, 1.0)
        cover = _cover([_species('fern', density=3.0, patchiness=1.0)],
                       card_radius=120.0, mask=nothing_west)
        cover.update((0.0, 0.0, 0.0))
        assert float(cover.rungs[0].cards.pos[:, 0].min()) > -2.0


class TestWhatGrowsUnderTheTreesAndWhatDoesNot:
    """A wood is not equally green all through. Under a closed canopy there is
    almost nothing on the floor; where the trees stand apart, and along the
    edges of clearings, scrub and shrubs take over. The terrain works out how
    much tree cover stands over each patch of ground, so a species says what
    band of that it grows under and the wood arranges itself."""

    def _stand(self, west=1.2, east=0.15):
        """Closed canopy on the west side, a thin scatter on the east."""
        def at(x, z):
            return np.where(np.asarray(x, 'd') < 0.0, west, east)
        return at

    def _edges(self):
        """Closed canopy fading out to open ground, west to east."""
        def at(x, z):
            return np.clip((100.0 - np.asarray(x, 'd')) / 200.0, 0.0, 1.0)
        return at

    def test_a_shade_plant_keeps_out_of_the_open(self) -> None:
        cover = _cover([_species('fern', density=3.0, canopy=(0.6, 1.6))],
                       card_radius=120.0, canopy=self._stand())
        cover.update((0.0, 0.0, 0.0))
        points = cover.rungs[0].cards.pos
        assert len(points)
        assert float((points[:, 0] > 5.0).mean()) < 0.05

    def test_a_shrub_keeps_out_of_a_closed_stand(self) -> None:
        """Where the trees are dense the shrubs will not grow."""
        cover = _cover([_species('shrub', density=3.0, canopy=(0.05, 0.6))],
                       card_radius=120.0, canopy=self._stand())
        cover.update((0.0, 0.0, 0.0))
        points = cover.rungs[0].cards.pos
        assert len(points)
        assert float((points[:, 0] < -5.0).mean()) < 0.05

    def test_a_shrub_is_thickest_where_the_trees_thin_out(self) -> None:
        """The transition, which is where scrub actually grows: a band that
        stops short of bare ground peaks at the edge rather than in the open."""
        cover = _cover([_species('shrub', density=4.0, canopy=(0.15, 0.7))],
                       card_radius=140.0, canopy=self._edges())
        cover.update((0.0, 0.0, 0.0))
        across = cover.rungs[0].cards.pos[:, 0]
        under = int((across < -70.0).sum())          # closed canopy
        margin = int((np.abs(across) < 30.0).sum())  # the thinning edge
        open_ground = int((across > 70.0).sum())
        assert margin > 3 * under
        assert margin > open_ground

    def test_a_straggler_at_the_edge_of_its_cover_is_a_small_one(self) -> None:
        """Rather than a full-sized shrub that happens to be standing there."""
        cover = _cover([_species('shrub', density=6.0, height=1.0,
                                 canopy=(0.15, 0.7))],
                       card_radius=140.0, canopy=self._edges())
        cover.update((0.0, 0.0, 0.0))
        points = cover.rungs[0].cards.pos
        scales = cover.rungs[0].cards.scales
        # cover runs (100 - x) / 200, so the middle of the (0.15, 0.7) band is
        # around x = 15 and its lower edge around x = 60.
        best = scales[np.abs(points[:, 0] - 15.0) < 15.0]
        edge = scales[(points[:, 0] > 48.0) & (points[:, 0] < 64.0)]
        assert len(best) and len(edge)
        assert float(best.mean()) > float(edge.mean())

    def test_a_plant_with_no_preference_grows_anywhere(self) -> None:
        cover = _cover([_species('grass', density=3.0)], card_radius=120.0,
                       canopy=self._stand())
        cover.update((0.0, 0.0, 0.0))
        across = cover.rungs[0].cards.pos[:, 0]
        assert (across < -20.0).any() and (across > 20.0).any()

    def test_a_preference_needs_ground_that_knows_about_its_trees(self) -> None:
        """With no closure to read, a band cannot be honoured, and a wood with
        no cover at all is worse than one that ignores the preference."""
        cover = _cover([_species('shrub', density=3.0, canopy=(0.05, 0.6))],
                       card_radius=120.0)
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.rungs[0].cards.pos)


class TestTheCardsBeyondTheGeometry:
    def test_the_far_field_reaches_further_than_the_near_one(self) -> None:
        cover = _cover(card_radius=120.0, far_radius=600.0)
        cover.update((0.0, 0.0, 0.0))
        rung = cover.rungs[0]
        assert float(np.hypot(rung.far_cards.pos[:, 0],
                              rung.far_cards.pos[:, 2]).max()) > 400.0
        assert float(np.hypot(rung.cards.pos[:, 0],
                              rung.cards.pos[:, 2]).max()) <= 121.0

    def test_the_far_field_is_the_sparser_one(self) -> None:
        """Out where a card is a few pixels, a dense field is spent for nothing."""
        cover = _cover(card_radius=120.0, far_radius=300.0)
        cover.update((0.0, 0.0, 0.0))
        rung = cover.rungs[0]
        near_area = np.pi * 120.0 ** 2
        far_area = np.pi * 300.0 ** 2
        assert len(rung.far_cards.pos) / far_area \
            < 0.2 * len(rung.cards.pos) / near_area

    def test_the_cards_fade_in_where_the_geometry_stops(self, tmp_path) -> None:
        cover = _cover([_species('fern', clump=_plant_file(tmp_path))],
                       clump_radius=30.0, card_radius=100.0)
        assert cover.rungs[0].cards.near_cut == pytest.approx(30.0)

    def test_without_geometry_the_cards_run_all_the_way_in(self) -> None:
        """Nothing hands off to them, so there is no inner edge to cut at."""
        cover = _cover(clump_radius=30.0, card_radius=100.0)
        assert cover.rungs[0].cards.near_cut == 0.0

    def test_the_far_cards_fade_in_where_the_near_ones_stop(self) -> None:
        cover = _cover(card_radius=100.0, far_radius=500.0)
        rung = cover.rungs[0]
        assert rung.far_cards.near_cut < 100.0
        assert rung.far_cards.far_fade == pytest.approx(500.0)


class TestTheGeometryNearTheCamera:
    """Two levels of detail, because the outer ring of the disc is most of the
    plants: full geometry close in, a decimated mesh over the rest of it."""

    def _clumped(self, tmp_path, **named):
        named.setdefault('clump_radius', 30.0)
        species = _species('fern', clump=_plant_file(tmp_path),
                           clumpMesh='near', clumpFarMesh='far', density=2.0)
        return _cover([species], **named)

    def test_a_species_with_no_clump_is_cards_all_the_way_in(self) -> None:
        assert _cover().rungs[0].clumps_near is None

    def test_a_species_with_one_gets_both_rungs(self, tmp_path) -> None:
        rung = self._clumped(tmp_path).rungs[0]
        assert rung.clumps_near is not None and rung.clumps_far is not None

    def test_the_far_rung_is_the_cheaper_mesh(self, tmp_path) -> None:
        rung = self._clumped(tmp_path).rungs[0]
        assert len(rung.clumps_far.idx) < len(rung.clumps_near.idx)

    def test_a_mesh_may_be_named_by_its_position(self, tmp_path) -> None:
        """'1' is the second mesh in the file, since none is named '1'."""
        by_name = self._clumped(tmp_path).rungs[0]
        species = _species('fern', clump=_plant_file(tmp_path),
                           clumpMesh='0', clumpFarMesh='1')
        by_place = _cover([species]).rungs[0]
        assert len(by_place.clumps_far.idx) == len(by_name.clumps_far.idx)
        assert len(by_place.clumps_near.idx) == len(by_name.clumps_near.idx)

    def test_the_full_detail_rung_covers_only_the_inner_disc(self, tmp_path) -> None:
        cover = self._clumped(tmp_path, card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        rung = cover.rungs[0]
        drawn = rung.clumps_near._instance_rows()
        assert len(drawn)
        reach = np.hypot(drawn[:, 0], drawn[:, 2]).max()
        assert reach <= 30.0 * CLUMP_LOD_FRAC + 1.0

    def test_the_coarse_rung_covers_the_whole_disc(self, tmp_path) -> None:
        cover = self._clumped(tmp_path, card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        drawn = cover.rungs[0].clumps_far._instance_rows()
        assert float(np.hypot(drawn[:, 0], drawn[:, 2]).max()) > 30.0 * 0.8

    def test_the_geometry_tracks_the_camera_without_rescattering(
            self, tmp_path) -> None:
        """The scatter is cached over a disc wider than the drawn one, so a step
        that does not trigger a re-scatter still re-centres what is drawn."""
        cover = self._clumped(tmp_path, card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        scattered = cover.selections
        cover.update((5.0, 0.0, 0.0))
        assert cover.selections == scattered          # too small a step to re-scatter
        drawn = cover.rungs[0].clumps_near._instance_rows()
        assert float(np.hypot(drawn[:, 0] - 5.0, drawn[:, 2]).max()) \
            <= 30.0 * CLUMP_LOD_FRAC + 1.0            # ...yet centred on the camera

    def test_walking_does_not_make_the_field_pulse(self, tmp_path) -> None:
        """The property the cache and the per-frame re-centring exist for.

        A disc re-scattered only every so often, and drawn where it was
        scattered, thins out ahead of the walker and fills back in at each
        re-scatter -- which reads as the mid-distance cover pulsing in density
        as you walk. Re-centring what is *drawn* on the live camera every frame
        is what removes it, so the count in a band ahead holds steady across
        several re-scatter boundaries."""
        cover = self._clumped(tmp_path, card_radius=90.0)
        counted = []
        for step in np.arange(0.0, 36.0, 1.0):    # across three re-scatters
            cover.update((0.0, 0.0, float(step)))
            drawn = cover.rungs[0].clumps_far._instance_rows()
            ahead = drawn[:, 2] - step
            counted.append(int(((ahead > 18.0) & (ahead < 28.0)).sum()))
        counted = np.asarray(counted)
        assert counted.mean() > 0
        assert np.abs(np.diff(counted)).max() < 0.35 * counted.mean()

    def test_one_mesh_for_both_rungs_is_uploaded_and_drawn_once(
            self, tmp_path) -> None:
        species = _species('fern', clump=_plant_file(tmp_path),
                           clumpMesh='near', density=2.0)
        cover = _cover([species], clump_radius=30.0)
        rung = cover.rungs[0]
        clumps = [node for node in rung.nodes
                  if type(node).__name__ == 'InstancedClumps']
        assert len(clumps) == 1
        cover.update((0.0, 0.0, 0.0))
        drawn = clumps[0]._instance_rows()
        assert float(np.hypot(drawn[:, 0], drawn[:, 2]).max()) > 30.0 * 0.8

    def test_a_small_step_draws_from_what_is_already_up(self, tmp_path) -> None:
        """Re-choosing the drawn plants copies and uploads them; a step the
        shader's own fade covers does not need it."""
        cover = self._clumped(tmp_path, card_radius=90.0)
        rung = cover.rungs[0]
        uploads = []
        original = rung.clumps_far.update_instances

        def counting(*arrays):
            uploads.append(len(arrays[0]))
            return original(*arrays)
        rung.clumps_far.update_instances = counting
        cover.update((0.0, 0.0, 0.0))
        for step in (0.2, 0.4, 0.6):
            cover.update((step, 0.0, 0.0))
        assert len(uploads) == 1
        cover.update((3.0, 0.0, 0.0))
        assert len(uploads) == 2

    def test_what_is_up_covers_the_disc_around_the_live_camera(
            self, tmp_path) -> None:
        cover = self._clumped(tmp_path, card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        cover.update((0.6, 0.0, 0.0))
        points = cover.rungs[0].cache[0]
        wanted = np.hypot(points[:, 0] - 0.6, points[:, 2]) < 30.0
        drawn = {tuple(row) for row in
                 np.round(cover.rungs[0].clumps_far._instance_rows()[:, :3], 4)}
        assert {tuple(row) for row in np.round(points[wanted], 4)} <= drawn

    def test_retuning_moves_the_fade_windows_with_the_radius(self, tmp_path) -> None:
        cover = self._clumped(tmp_path)
        cover.clump_radius = 12.0
        cover.retune()
        rung = cover.rungs[0]
        assert rung.clumps_far.fade_end == pytest.approx(12.0)
        assert rung.clumps_near.fade_end == pytest.approx(12.0 * CLUMP_LOD_FRAC)


class TestTheHeavyHalfCanRunOffTheRenderThread:
    """The scatter is tens of milliseconds and lands whole on one frame as a
    hitch. It is pure numpy, so a worker can run it -- provided the compute half
    stages nothing and the apply half does no scattering."""

    def test_computing_a_disc_changes_nothing(self) -> None:
        cover = _cover(card_radius=100.0)
        before = cover.selections
        cover.compute_near(30.0, 40.0)
        assert cover.selections == before
        assert not len(cover.rungs[0].cards.pos)

    def test_applying_what_was_computed_puts_it_up(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.apply_near(cover.compute_near(30.0, 40.0))
        assert len(cover.rungs[0].cards.pos)

    def test_the_two_halves_agree_with_the_single_call(self) -> None:
        one = _cover(card_radius=100.0)
        one.update((30.0, 0.0, 40.0))
        other = _cover(card_radius=100.0)
        other.apply_near(other.compute_near(30.0, 40.0))
        other.apply_far(other.compute_far(30.0, 40.0))
        other.select(30.0, 40.0)
        np.testing.assert_array_equal(one.rungs[0].cards.pos,
                                      other.rungs[0].cards.pos)
        np.testing.assert_array_equal(one.rungs[0].far_cards.pos,
                                      other.rungs[0].far_cards.pos)

    def test_the_far_disc_is_left_alone_by_a_short_walk(self) -> None:
        """Seven hundred metres of cards is not re-scattered every ten paces."""
        cover = _cover(card_radius=100.0, far_radius=600.0)
        cover.update((0.0, 0.0, 0.0))
        first = cover.rungs[0].far_cards.pos.copy()
        cover.update((15.0, 0.0, 0.0))
        np.testing.assert_array_equal(cover.rungs[0].far_cards.pos, first)


class TestWhatABakedWorldCarries:
    def test_a_species_survives_a_round_trip(self) -> None:
        entry = _species('fern', clump='fern.glb', clumpMesh='fern_a_near',
                         clumpFarMesh='fern_a_far', density=0.4, height=0.45,
                         cardWidth=1.6, canopy=(0.2, 0.7))
        back = CoverSpecies.from_json(json.loads(json.dumps(entry.to_json())))
        assert back.to_json() == entry.to_json()

    def test_a_world_baked_with_a_mesh_index_still_reads(self) -> None:
        """A baked world may name its clump mesh by position, as a number."""
        back = CoverSpecies.from_json({'name': 'grass', 'card': 'g.png',
                                       'clump': 'g.glb', 'clumpMesh': 2,
                                       'clumpFarMesh': None, 'canopy': None})
        assert back.clumpMesh == '2'
        assert not back.clumpFarMesh
        assert not len(back.canopy)

    def test_a_whole_set_resolves_against_one_directory(self) -> None:
        found = [one.beside('/worlds/one')
                 for one in (_species('grass', clump='g.glb'), _species('fern'))]
        assert found[0].clump == '/worlds/one/g.glb'
        assert found[1].card == '/worlds/one/fern.png'
        assert not found[1].clump


def _plant_file(tmp_path):
    """A two-rung plant: a fuller mesh named 'near' and a coarse one named 'far'.

    What a baked plant is -- every rung against the one texture they share.
    """
    from tests.unit.test_clump_glb import _many_glb_bytes, _ribbon, _two_blades
    path = tmp_path / "fern.glb"
    path.write_bytes(_many_glb_bytes([("near", *_two_blades()),
                                      ("far", *_ribbon(n_rings=2))]))
    return str(path)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
