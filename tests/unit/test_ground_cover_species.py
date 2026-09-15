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
                           clump_mesh='near', clump_far_mesh='far', density=2.0)
        return _cover([species], **named)

    def test_a_species_with_no_clump_is_cards_all_the_way_in(self) -> None:
        assert _cover().rungs[0].clumps_near is None

    def test_a_species_with_one_gets_both_rungs(self, tmp_path) -> None:
        rung = self._clumped(tmp_path).rungs[0]
        assert rung.clumps_near is not None and rung.clumps_far is not None

    def test_the_far_rung_is_the_cheaper_mesh(self, tmp_path) -> None:
        rung = self._clumped(tmp_path).rungs[0]
        assert len(rung.clumps_far.idx) < len(rung.clumps_near.idx)

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
        entry = _species('fern', clump='fern.glb', clump_mesh='fern_a_near',
                         clump_far_mesh='fern_a_far', density=0.4, height=0.45,
                         card_width=1.6)
        assert CoverSpecies.from_json(
            json.loads(json.dumps(entry.to_json()))) == entry

    def test_a_whole_set_resolves_against_one_directory(self) -> None:
        found = [one.beside('/worlds/one')
                 for one in (_species('grass', clump='g.glb'), _species('fern'))]
        assert found[0].clump == '/worlds/one/g.glb'
        assert found[1].card == '/worlds/one/fern.png'
        assert found[1].clump is None


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
