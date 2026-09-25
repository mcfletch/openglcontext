"""``oglc-cover``: the meadow's cover and its well, with no window.

The scene the demo and its tutorial draw is :class:`Meadow`, so what grows
where and what the keys do are tested here; ``tests/cover_meadow.py`` is the
rendered form, in the visual suite.
"""
import os

import numpy as np
import pytest

pytest.importorskip('pygltflib')

from OpenGLContext.bin import cover_demo
from OpenGLContext.bin.cover_demo import (
    DENSITIES, LAYERS, WELL, WELL_RADIUS, Meadow,
)


@pytest.fixture(scope='module')
def art(tmp_path_factory):
    return str(tmp_path_factory.mktemp('art'))


@pytest.fixture
def meadow(art):
    return Meadow(art=art, background=False)


def _all_cards(meadow):
    return np.concatenate([rung.cards.pos for rung in meadow.cover.rungs]
                          + [rung.far_cards.pos for rung in meadow.cover.rungs])


class TestTheArt:
    def test_it_is_written_where_it_was_asked_for(self, meadow, art):
        for species in meadow.species:
            assert os.path.dirname(species.card) == art
            assert os.path.isfile(species.card)
        assert os.path.isfile(meadow.species[0].clump)

    def test_the_grass_is_geometry_near_the_camera_in_two_levels(self, meadow):
        grass = meadow.cover.rung('grass')
        assert grass.clumps_near is not None and grass.clumps_far is not None
        assert len(grass.clumps_far.idx) < len(grass.clumps_near.idx)

    def test_the_ferns_and_flowers_are_cards(self, meadow):
        for name in ('fern', 'flowers'):
            assert meadow.cover.rung(name).clumps_far is None

    def test_the_terrain_is_given_a_colour_and_a_normal_map_per_layer(self):
        from PIL import Image
        grounds = cover_demo.Grounds()
        for name in LAYERS:
            maps = grounds(name, '1K')
            assert Image.open(maps['color']).size == Image.open(maps['normal']).size


class TestWhatGrowsWhere:
    def test_the_meadow_grows_cover_of_every_kind(self, meadow):
        meadow.update(meadow.standing(0.0, 12.0))
        assert all(len(rung.cards.pos) for rung in meadow.cover.rungs)

    def test_nothing_grows_on_the_rock(self, meadow):
        from OpenGLContext.scenegraph.vegetation import control_weight
        meadow.update(meadow.standing(0.0, -60.0))
        cards = _all_cards(meadow)
        rock = control_weight(meadow.control, ['rock'], LAYERS, cover_demo.EXTENT)
        assert len(cards) and rock(cards[:, 0], cards[:, 2]).max() < 0.99

    def test_nothing_grows_over_the_well(self, meadow):
        meadow.update(meadow.standing(WELL[0], WELL[1] + 10.0))
        cards = _all_cards(meadow)
        away = np.hypot(cards[:, 0] - WELL[0], cards[:, 2] - WELL[1])
        assert away.min() >= WELL_RADIUS

    def test_the_terrain_is_cut_over_the_well(self, meadow):
        patch = meadow.terrain.patch
        corners = patch.vertices[patch.indices.reshape(-1, 3), :3].mean(axis=1)
        assert not meadow.opening(corners[:, 0], corners[:, 2]).any()


class TestTheKeys:
    def test_o_closes_the_well_and_opens_it(self, meadow):
        assert meadow.press('o') == 'the well closed over'
        assert meadow.terrain.holes is None and meadow.cover.holes is None
        assert meadow.press('o') == 'the well open'
        assert meadow.terrain.holes is not None
        assert meadow.cover.holes == meadow.terrain.holes

    def test_d_steps_the_density_down_and_round(self, meadow):
        said = [meadow.press('d') for _density in DENSITIES]
        assert said == ['cover at 50%', 'cover at 0%', 'cover at 100%']
        assert meadow.cover.density_scale == 1.0

    def test_no_cover_is_no_cover(self, meadow):
        meadow.press('d')
        meadow.press('d')
        meadow.update(meadow.standing(0.0, 12.0))
        assert not any(len(rung.cards.pos) for rung in meadow.cover.rungs)

    def test_any_other_key_changes_nothing(self, meadow):
        assert meadow.press('q') == ''


class TestTheCommand:
    def test_it_starts_looking_at_the_well(self, meadow):
        (x, _y, z), (_ax, _ay, _az, turn) = meadow.viewpoint()
        forward = np.array([-np.sin(turn), -np.cos(turn)])
        towards = np.array([WELL[0] - x, WELL[1] - z])
        assert np.dot(forward, towards / np.linalg.norm(towards)) > 0.99

    def test_help_prints_the_keys_and_opens_no_window(self, capsys):
        with pytest.raises(SystemExit) as stopped:
            cover_demo.main(['--help'])
        assert stopped.value.code == 0
        said = capsys.readouterr().out
        assert 'usage: oglc-cover' in said
        for key in Meadow.KEYS:
            assert '  %s -- ' % (key,) in said
