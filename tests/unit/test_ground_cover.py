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
import numpy as np
import pytest

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
        assert _cover().cards is not None

    def test_clumps_are_built_only_when_there_is_a_clump(self) -> None:
        assert _cover().clumps is None

    def test_the_rungs_are_its_children(self) -> None:
        assert len(_cover().children) >= 1

    def test_it_needs_a_card_to_draw(self) -> None:
        with pytest.raises(ValueError):
            GroundCover(_field(), CoverSpecies(name='g', card=''))

    def test_a_species_reads_as_its_name(self) -> None:
        assert 'grass' in repr(_species())

    def test_it_survives_a_round_trip_through_json(self) -> None:
        import json
        entry = _species(clump='c.glb', density=2.5)
        assert CoverSpecies.from_json(json.loads(json.dumps(entry.to_json()))) \
            == entry

    def test_its_files_resolve_against_a_directory(self) -> None:
        found = _species(clump='c.glb').beside('/worlds/one')
        assert found.card == '/worlds/one/grass.png'
        assert found.clump == '/worlds/one/c.glb'

    def test_a_species_with_no_clump_resolves_anyway(self) -> None:
        assert _species().beside('/worlds/one').clump is None


class TestWhereItGrows:
    def test_it_follows_the_camera(self) -> None:
        cover = _cover(card_radius=120.0)
        cover.update((0.0, 0.0, 0.0))
        here = cover.cards.pos.copy()
        cover.update((400.0, 0.0, 0.0))
        assert float(cover.cards.pos[:, 0].mean()) \
            > float(here[:, 0].mean()) + 100.0

    def test_it_reaches_as_far_as_it_is_told(self) -> None:
        cover = _cover(card_radius=90.0)
        cover.update((0.0, 0.0, 0.0))
        assert float(np.hypot(cover.cards.pos[:, 0],
                              cover.cards.pos[:, 2]).max()) <= 91.0

    def test_it_sits_on_the_ground(self) -> None:
        def sloping(x, z):
            return np.asarray(x, 'd') * 0.0 + 7.0
        field = HeightField(np.ones((33, 33)), EXTENT, 7.0)
        cover = GroundCover(field, _species(), card_radius=80.0)
        cover.update((0.0, 0.0, 0.0))
        assert np.allclose(cover.cards.pos[:, 1], 7.0, atol=0.01)

    def test_denser_means_more_of_it(self) -> None:
        thin = _cover(species=_species(density=0.5), card_radius=100.0)
        thick = _cover(species=_species(density=4.0), card_radius=100.0)
        thin.update((0.0, 0.0, 0.0))
        thick.update((0.0, 0.0, 0.0))
        assert len(thick.cards.pos) > len(thin.cards.pos) * 4

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

    def test_a_cell_keeps_its_place_as_the_disc_moves(self) -> None:
        """World-anchored, so nothing appears or shifts as you drive past."""
        cover = _cover(card_radius=150.0)
        cover.update((0.0, 0.0, 0.0))
        watched = {tuple(np.round(one, 3)) for one in cover.cards.pos
                   if abs(one[0]) < 30.0 and abs(one[2]) < 30.0}
        cover.update((60.0, 0.0, 0.0))
        after = {tuple(np.round(one, 3)) for one in cover.cards.pos}
        assert watched and watched <= after


class TestWhereItDoesNot:
    def _control(self, layers=('grass', 'rock')):
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
        assert float(cover.cards.pos[:, 0].min()) > -60.0

    def test_it_still_grows_where_the_mask_allows(self) -> None:
        mask = control_weight(self._control(), ['grass'], ['grass', 'rock'],
                              EXTENT)
        cover = _cover(card_radius=400.0, mask=mask)
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.cards.pos) > 100

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
        assert float(cover.cards.pos[:, 0].min()) < -150.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestItStandsInTheSameLightAsTheGroundDoes:
    """Grass lit like an open field, on ground the canopy has darkened to a
    fifth, reads as a row of lamps on the forest floor."""

    def _shade(self):
        def at(x, z):
            return np.where(np.asarray(x, 'd') < 0.0, 0.2, 1.0)
        return at

    def test_without_a_shade_it_is_all_in_full_sun(self) -> None:
        cover = _cover(card_radius=100.0)
        cover.update((0.0, 0.0, 0.0))
        assert cover.cards.shades is None

    def test_with_one_each_card_carries_its_own(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.update((0.0, 0.0, 0.0))
        assert len(cover.cards.shades) == len(cover.cards.pos)

    def test_the_shaded_side_is_darker(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.update((0.0, 0.0, 0.0))
        west = cover.cards.shades[cover.cards.pos[:, 0] < -10.0]
        east = cover.cards.shades[cover.cards.pos[:, 0] > 10.0]
        assert float(west.mean()) < 0.3 < float(east.mean())

    def test_the_clumps_are_shaded_too(self) -> None:
        cover = _cover(card_radius=100.0, shade=self._shade())
        cover.clumps = _Recording()
        cover.update((0.0, 0.0, 0.0))
        assert cover.clumps.shades is not None


class _Recording:
    """A stand-in for the clump layer, which needs a .glb and a GL context."""

    def __init__(self):
        self.shades = None

    def update_instances(self, positions, yaws, scales, shades=None):
        self.pos, self.shades = positions, shades


class TestItDoesNotGrowInRows:
    """A jittered grid is still a grid if nothing may leave its own cell: from
    thirty metres the tufts line up into diagonals and the ground reads as a
    planted field. Letting a cell's instance land in its neighbour's ground
    breaks the lattice, and clumps and gaps are what real cover looks like."""

    def _spacing(self, cover):
        """How far each tuft is from its nearest neighbour."""
        points = cover.cards.pos[:, [0, 2]]
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
        assert len(cover.cards.pos) > 2500
