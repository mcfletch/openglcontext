"""What a baked world is, written down beside the tiles that draw it.

A directory of tiles says how to draw a world and nothing about what it *is*:
what it is called, how long its road is, how much of that is carried on
structures, or which picture shows it. A game offering a player a choice of
worlds needs all of that before it loads any of them, and a manifest is where
it lives -- one small JSON file beside the tileset, written by the bake that
knows the answers.
"""
import json
import os

import pytest

from OpenGLContext.loaders.tiles3d.manifest import (
    MANIFEST,
    carried,
    WorldManifest,
    read_manifest,
    write_manifest,
)


class TestWhatAManifestSays:
    def test_a_world_has_a_name(self):
        assert WorldManifest(name='Ashdown').name == 'Ashdown'

    def test_it_names_the_tileset_that_draws_it(self):
        assert WorldManifest(name='Ashdown').tileset == 'tileset.json'

    def test_a_world_with_no_picture_says_so_rather_than_guessing(self):
        assert WorldManifest(name='Ashdown').picture is None

    def test_how_long_the_road_is(self):
        found = WorldManifest(name='Ashdown', road_length=8306.9)
        assert found.road_length == pytest.approx(8306.9)

    def test_and_how_much_of_it_is_carried(self):
        found = WorldManifest(name='Ashdown',
                              structures={'bridge': 1529.5, 'tunnel': 795.2})
        assert found.structures['tunnel'] == pytest.approx(795.2)

    def test_a_lap_is_a_closed_road(self):
        assert WorldManifest(name='Ashdown').closed

    def test_a_road_that_ends_is_not(self):
        assert not WorldManifest(name='Stage', closed=False).closed


class TestSayingItInAWayaGameCanRead:
    def _round_trip(self, **named):
        one = WorldManifest(name='Ashdown', **named)
        return WorldManifest.from_json(json.loads(json.dumps(one.to_json())))

    def test_a_manifest_survives_being_written_and_read(self):
        found = self._round_trip(seed=11, extent=4096.0, road_length=8306.9,
                                 structures={'bridge': 1529.5}, closed=True,
                                 picture='track.png')
        assert (found.name, found.seed, found.picture) == \
            ('Ashdown', 11, 'track.png')

    def test_the_numbers_come_back_as_numbers(self):
        found = self._round_trip(road_length=8306.9, extent=4096.0)
        assert found.road_length == pytest.approx(8306.9)
        assert found.extent == pytest.approx(4096.0)

    def test_the_structures_come_back_whole(self):
        found = self._round_trip(structures={'bridge': 1529.5, 'tunnel': 795.2})
        assert found.structures == pytest.approx(
            {'bridge': 1529.5, 'tunnel': 795.2})

    def test_a_document_missing_everything_but_a_name_still_reads(self):
        """A manifest written by an older bake is not an error."""
        assert WorldManifest.from_json({'name': 'Ashdown'}).name == 'Ashdown'

    def test_a_document_with_no_name_at_all_is_refused(self):
        with pytest.raises(ValueError):
            WorldManifest.from_json({'seed': 11})


class TestWhereItLives:
    def test_it_is_written_beside_the_tileset(self, tmp_path):
        written = write_manifest(str(tmp_path), WorldManifest(name='Ashdown'))
        assert written == os.path.join(str(tmp_path), MANIFEST)
        assert os.path.exists(written)

    def test_and_read_back_from_the_directory(self, tmp_path):
        write_manifest(str(tmp_path), WorldManifest(name='Ashdown', seed=11))
        assert read_manifest(str(tmp_path)).seed == 11

    def test_or_from_the_tileset_a_game_was_given(self, tmp_path):
        """A game is handed a tileset.json, not a directory."""
        write_manifest(str(tmp_path), WorldManifest(name='Ashdown'))
        assert read_manifest(str(tmp_path / 'tileset.json')).name == 'Ashdown'

    def test_or_from_the_manifest_itself(self, tmp_path):
        written = write_manifest(str(tmp_path), WorldManifest(name='Ashdown'))
        assert read_manifest(written).name == 'Ashdown'

    def test_a_directory_with_no_manifest_reads_as_nothing(self, tmp_path):
        assert read_manifest(str(tmp_path)) is None

    def test_a_manifest_that_will_not_parse_reads_as_nothing(self, tmp_path):
        (tmp_path / MANIFEST).write_text('{not json', encoding='utf-8')
        assert read_manifest(str(tmp_path)) is None

    def test_a_manifest_with_no_name_reads_as_nothing(self, tmp_path):
        (tmp_path / MANIFEST).write_text('{"seed": 11}', encoding='utf-8')
        assert read_manifest(str(tmp_path)) is None

    def test_what_is_written_is_readable_by_a_person(self, tmp_path):
        write_manifest(str(tmp_path), WorldManifest(name='Ashdown', seed=11))
        text = (tmp_path / MANIFEST).read_text(encoding='utf-8')
        assert '\n' in text and '"name"' in text


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class _Path:
    """A road that has been through some hills."""

    def __init__(self, runs):
        self.runs = runs

    def structure_runs(self):
        return iter(self.runs)


class TestHowMuchOfARoadIsCarried:
    def test_a_road_on_the_ground_carries_nothing(self):
        assert carried(_Path([])) == {}

    def test_one_structure_is_its_own_length(self):
        assert carried(_Path([('bridge', 100.0, 350.0)])) == \
            pytest.approx({'bridge': 250.0})

    def test_two_of_a_kind_add_up(self):
        found = carried(_Path([('bridge', 100.0, 350.0),
                               ('bridge', 900.0, 1000.0)]))
        assert found == pytest.approx({'bridge': 350.0})

    def test_each_kind_is_counted_apart(self):
        found = carried(_Path([('bridge', 0.0, 200.0), ('tunnel', 400.0, 900.0)]))
        assert found == pytest.approx({'bridge': 200.0, 'tunnel': 500.0})

    def test_a_kind_that_is_an_enum_is_named_by_its_value(self):
        import enum

        class Op(enum.Enum):
            TUNNEL = 'tunnel'

        assert carried(_Path([(Op.TUNNEL, 0.0, 50.0)])) == \
            pytest.approx({'tunnel': 50.0})


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class _Path:
    """A road that has been through some hills."""

    def __init__(self, runs):
        self.runs = runs

    def structure_runs(self):
        return iter(self.runs)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
