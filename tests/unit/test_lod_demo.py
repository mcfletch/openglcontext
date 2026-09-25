"""``oglc-lod``: the hall's levels of detail, with no window.

The scene the demo and its tutorial draw is :class:`LODHall`, so what each
chain holds and what the keys do are tested here; ``tests/lod_hall.py`` is
the rendered form, in the visual suite.
"""
import pytest

pytest.importorskip('pygltflib')

from OpenGLContext.bin import lod_demo  # noqa: E402
from OpenGLContext.bin.lod_demo import COVERAGE, ROWS, SIDES, LODHall  # noqa: E402
from OpenGLContext.loaders.assets import shapes  # noqa: E402
from OpenGLContext.scenegraph.lod import LOD, ScreenCoverageLOD  # noqa: E402


@pytest.fixture(scope='module')
def finishes():
    return lod_demo.Finishes()


@pytest.fixture
def hall(finishes):
    return LODHall(finishes)


def _triangles(level):
    return sum(len(shape.geometry.indices) // 3 for shape in shapes(level))


class TestTheChains:
    def test_both_rows_are_screen_coverage_chains(self, hall):
        assert len(hall.chains) == 2 * ROWS
        assert all(isinstance(chain, ScreenCoverageLOD) for chain in hall.chains)

    def test_each_level_is_coarser_than_the_one_before(self, hall):
        for chain in hall.chains:
            counts = [_triangles(level) for level in chain.level]
            assert len(counts) == len(SIDES)
            assert counts == sorted(counts, reverse=True) and counts[0] > counts[-1]

    def test_the_file_s_chains_keep_the_coverage_they_were_written_with(self, hall):
        for chain in hall.chains:
            assert list(chain.screenCoverage) == pytest.approx(list(COVERAGE))

    def test_the_file_s_row_stands_across_from_the_built_one(self, hall):
        built, read = hall.chains[:ROWS], hall.chains[ROWS:]
        assert not set(map(id, built)) & set(map(id, read))

    def test_the_columns_are_chosen_by_distance(self, hall):
        assert hall.columns
        for column in hall.columns:
            assert type(column) is LOD
            assert list(column.range) == pytest.approx(list(lod_demo.COLUMN_RANGE))


class TestTheKeys:
    def test_t_tints_each_level_its_own_metal_and_back(self, hall, finishes):
        before = [[shape.appearance.material for shape in shapes(level)]
                  for level in hall.chains[0].level]
        assert 'tinted' in hall.press('t')
        for index, level in enumerate(hall.chains[0].level):
            assert all(shape.appearance.material is finishes.tints[index]
                       for shape in shapes(level))
        for level in hall.chains[-1].level:        # read from the file too
            assert all(shape.appearance.material in finishes.tints
                       for shape in shapes(level))
        hall.press('t')
        after = [[shape.appearance.material for shape in shapes(level)]
                 for level in hall.chains[0].level]
        assert after == before

    def test_h_turns_hysteresis_off_and_back(self, hall):
        assert hall.press('h') == 'hysteresis off'
        assert all(node.hysteresis == 0.0 for node in hall.chains + hall.columns)
        assert hall.press('h') == 'hysteresis on'
        assert all(node.hysteresis == pytest.approx(0.1)
                   for node in hall.chains + hall.columns)

    def test_any_other_key_changes_nothing(self, hall):
        assert hall.press('q') == ''
        assert not hall.tinted


class TestTheCommand:
    def test_help_prints_the_keys_and_opens_no_window(self, capsys):
        with pytest.raises(SystemExit) as stopped:
            lod_demo.main(['--help'])
        assert stopped.value.code == 0
        said = capsys.readouterr().out
        assert 'usage: oglc-lod' in said
        for key in LODHall.KEYS:
            assert '  %s -- ' % (key,) in said
